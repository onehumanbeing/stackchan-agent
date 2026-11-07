"""Voice loop on the robot's own mic and speaker: wake word -> listen -> agent -> spoken reply.

Mic audio arrives as 16 kHz int16 chunks (robot.on_audio).  An energy VAD cuts it into utterances;
whisper.cpp (whisper-server, started here, local) transcribes them.  While idle, an utterance that
starts with the wake phrase ("Hey Buddy") wakes the robot: it answers "Listening", looks up and, when it has
nothing else to do, lifts its head a little and drops its arms to home (at attention) until the command is in.  The next utterance goes to the agent.
Replies are spoken with a CosyVoice 2 server when --tts-url is given (streamed: it starts talking on the first
chunk), else a local TTS (Kokoro, else macOS `say`), and streamed to the robot's speaker; the mic is off while it speaks (the board is half duplex).
"""
import array
import io
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import wave
from pathlib import Path

from talk_motion import Talk

RATE, CHUNK_S = 16000, 0.04
WAKE = re.compile(r"(?:^[\s,.!]*|(?:hey|hi|hay|hei|a|ay|eh|ok|okay|嘿|黑|嗨|哈)[\s,.!，。！、]*)(?<![a-z])(buddy|buddie|buddi|budy|bodhi|bodie|baddy|巴迪|巴蒂|八迪)(?![a-z])"
                  r"|(?:hey|hi|嘿|嗨)[\s,.!，。！、]*(body|bud|betty|birdie)(?![a-z])", re.I)
MUSIC = re.compile(r"\b(music|dance|dancing)\b|音乐|跳舞|跳个舞", re.I)    # a spoken command with this starts the dance (dance.py)
PREROLL_S = 0.4              # audio kept from before the level rises, so soft starts ("Hey") are not cut
# No whisper --prompt: with "Hey Buddy" as a prompt it hears "Buddy." in silence and servo noise.
HEARD = {"zh": "我在听", "en": "Listening"}
LIFT_DEG = 8
END_S = 0.5                  # silence that ends a command
WAKE_S, FOLLOW_S = 10, 8     # how long it waits for a command after the wake word / after answering


# What whisper tends to "hear" in silence or noise; never a command.
NOISE = {"thank you", "thanks", "thank you very much", "thanks for watching", "thank you for watching", "you", "bye",
         "bye bye", "okay", "ok", "so", "um", "uh", "hmm", "amen", "谢谢", "谢谢观看", "字幕"}


def wordy(text):
    """At least two words (or two CJK characters): shorter bits are usually noise or our own echo."""
    text = text.strip(" ,.!?，。！？")
    if text.lower() in NOISE:
        return False
    return len(text) >= 2 if not text.isascii() else len(text.split()) >= 2
NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class Whisper:
    """whisper-server child process on localhost; transcribe(pcm) -> text."""

    def __init__(self, model, port=8178, language="auto"):
        exe = shutil.which("whisper-server")
        if not exe or not Path(model).exists():
            raise RuntimeError("voice needs whisper.cpp (brew install whisper-cpp) and a ggml model (--whisper-model)")
        self.url = f"http://127.0.0.1:{port}/inference"
        self.proc = subprocess.Popen([exe, "-m", str(model), "--port", str(port), "-l", language, "-nt"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(120):                    # model load
            try:
                NO_PROXY.open(f"http://127.0.0.1:{port}/", timeout=1)
                return
            except OSError:
                time.sleep(0.5)
        raise RuntimeError("whisper-server did not start")

    def transcribe(self, pcm, language=None):
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE), w.writeframes(pcm)
        boundary = "stackchanvoice"
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.wav\"\r\n"
                "Content-Type: audio/wav\r\n\r\n").encode() + buf.getvalue() + \
               f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"response_format\"\r\n\r\njson".encode() + \
               (f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"language\"\r\n\r\n{language}".encode() if language else b"") + \
               f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(self.url, body, {"Content-Type": f"multipart/form-data; boundary={boundary}"})
        return json.loads(NO_PROXY.open(req, timeout=30).read()).get("text", "").strip()


KOKORO_DIR = Path.home() / ".cache" / "stackchan-agent"


class Kokoro:
    """Kokoro-82M (Apache-2.0) via kokoro-onnx: model files kokoro-v1.0.onnx + voices-v1.0.bin in KOKORO_DIR."""

    def __init__(self, voice="af_heart", zh_voice="zf_xiaoxiao"):
        from kokoro_onnx import Kokoro as K
        self.k, self.voice, self.zh_voice = K(str(KOKORO_DIR / "kokoro-v1.0.onnx"), str(KOKORO_DIR / "voices-v1.0.bin")), voice, zh_voice

    def pcm(self, text):
        import numpy as np
        zh = re.search(r"[\u4e00-\u9fff]", text)
        samples, sr = self.k.create(text, voice=self.zh_voice if zh else self.voice, speed=1.05, lang="cmn" if zh else "en-us")
        n = int(len(samples) * RATE / sr)
        out = np.interp(np.linspace(0, len(samples) - 1, n), np.arange(len(samples)), samples)
        return (np.clip(out, -1, 1) * 32767).astype("<i2").tobytes()


class CosyVoice:
    """CosyVoice 2 server (cosyvoice_server.py, e.g. on a GPU box behind an ssh tunnel): POST {"text"} -> 16 kHz int16
    PCM, chunked as it is synthesized.  When it is unreachable the local TTS speaks instead."""

    def __init__(self, url, fallback):
        self.url, self.fallback = url, fallback

    def stream(self, text):
        try:
            r = NO_PROXY.open(urllib.request.Request(self.url, json.dumps({"text": text}).encode(), {"Content-Type": "application/json"}), timeout=10)
        except OSError as e:
            print(json.dumps({"tts": f"cosyvoice unreachable ({e}), local TTS"}), file=sys.stderr, flush=True)
            yield self.fallback(text)
            return
        buf = b""
        while chunk := r.read1(65536):
            buf += chunk
            if len(buf) >= RATE:                 # half a second at a time, an even number of bytes
                n = len(buf) & ~1
                yield buf[:n]
                buf = buf[n:]
        if buf:
            yield buf

    def pcm(self, text):
        return b"".join(self.stream(text))


def make_tts(voice):
    """Kokoro when its model files are present, else macOS `say`."""
    if (KOKORO_DIR / "kokoro-v1.0.onnx").exists():
        try:
            return Kokoro(voice if voice and "_" in voice else "af_heart").pcm
        except ImportError:
            pass
    return lambda text: say_pcm(text, voice if voice and "_" not in voice else "Samantha")


def say_pcm(text, voice="Samantha"):
    """Fallback TTS: macOS `say` -> 16 kHz mono int16 via ffmpeg."""
    with tempfile.TemporaryDirectory() as d:
        aiff = Path(d) / "t.aiff"
        subprocess.run(["say", "-v", voice, "-o", str(aiff), text], check=True)
        return subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(aiff), "-f", "s16le", "-ac", "1", "-ar", str(RATE), "-"],
                              check=True, capture_output=True).stdout


class Voice(threading.Thread):
    def __init__(self, robot, agent, whisper_model, tts_voice=None, wake=WAKE, follow_s=FOLLOW_S, tts_url=None):
        super().__init__(daemon=True)
        self.robot, self.agent, self.wake, self.follow_s = robot, agent, wake, follow_s
        self.tts = self.local_tts = make_tts(tts_voice)     # the wake reply always uses the local voice
        self.tts_stream = lambda text: iter([self.tts(text)])
        if tts_url:
            cosy = CosyVoice(tts_url, self.tts)
            self.tts, self.tts_stream = cosy.pcm, cosy.stream
        self.cache = {}                          # wake replies, rendered once: TTS takes about a second
        threading.Thread(target=lambda: [self._pcm(t) for t in HEARD.values()], daemon=True).start()
        self.stt = Whisper(whisper_model)
        self.mode = "idle"                       # idle (wake word) | listening (command) | busy
        self.buf, self.speech, self.silence, self.floor = bytearray(), False, 0.0, 200.0
        self.utterances, self.lifted, self.deaf_until, self.pre, self.spoke_at = [], None, 0.0, b"", None
        self.talking = False                     # playing audio: the mic is off
        self.arms_before = None                  # {id: deg} before the wake word sent the arms home
        self.lock = threading.Condition()
        robot.on_audio = self.feed
        agent.speak = self.say

    # --- mic side -------------------------------------------------------------------------------
    def feed(self, pcm):
        if self.talking or time.monotonic() < self.deaf_until:   # speaking, or its echo (while it thinks it still listens)
            return
        self.pre = (self.pre + pcm)[-int(PREROLL_S * RATE) * 2:]
        a = array.array("h", pcm)
        level = math.sqrt(sum(x * x for x in a) / max(1, len(a)))
        loud = level > max(self.floor * 3.0, 400)
        if not self.speech:
            self.floor = 0.95 * self.floor + 0.05 * level
            if loud:
                self.speech, self.silence, self.buf = True, 0.0, bytearray(self.pre)
            return
        self.buf += pcm
        self.silence = 0.0 if loud else self.silence + CHUNK_S
        seconds = len(self.buf) / (2 * RATE)
        end = 0.5 if self.mode == "idle" else END_S    # the wake phrase is short: answer it sooner
        if self.silence >= end or seconds > 12:
            self.speech = False
            sound = seconds - PREROLL_S - self.silence
            if sound < (0.3 if self.mode == "idle" else 0.15):   # actual sound; a one-word command ("Dance") is short
                self._log(f"dropped {sound:.2f} s of sound (too short; floor {self.floor:.0f})")
            else:
                with self.lock:
                    self.utterances.append((bytes(self.buf), time.monotonic() - self.silence))   # + when the speech ended
                    self.lock.notify()

    def _mic(self, on):
        try:
            self.robot.request("mic.start" if on else "mic.stop")
        except (RuntimeError, TimeoutError):
            pass

    # --- speaker side ---------------------------------------------------------------------------
    def say(self, text):
        self.talking = True                      # the mic is off while it plays (half duplex)
        self.talk = None
        try:
            self._say(text)
        finally:
            self.talking = False
            if self.talk:
                self.talk.stop()
        self.deaf_until = time.monotonic() + (0.15 if text in HEARD.values() else 0.4)   # its own echo; short after
        self._mic(True)                                                                  # "Listening": people answer fast

    def _say(self, text):
        self.robot.request("face.set", say=text, ms=4000)
        chunks = iter([self._pcm(text)]) if text in HEARD.values() else self.tts_stream(text)
        pcm = next(chunks, b"")
        started = time.monotonic()
        if self.spoke_at and text not in HEARD.values():    # how long the person waited for the answer
            self._log(f"first sound {started - self.spoke_at:.2f} s after the speech ended")
            self.spoke_at = None
        self.robot.send_audio(pcm)
        self.robot.request("face.set", mouth=0.7)          # the eyes bob while it talks
        talk = None
        if self.agent.motion and text not in HEARD.values():   # small talking hands / nods (talk_motion.py)
            talk = self.talk = Talk(self.robot, self.agent, pcm).start()
        for more in chunks:                      # the rest as it is synthesized
            self.robot.send_audio(more)
            if talk:
                talk.more(more, len(pcm) / (2 * RATE))
            pcm += more
        time.sleep(max(0.0, started + len(pcm) / (2 * RATE) + 0.3 - time.monotonic()))
        for _ in range(30):                      # until the robot's queue is empty
            if not self.robot.request("speaker.status").get("playing"):
                break
            time.sleep(0.1)
        self.robot.request("face.set", mouth=0)

    # --- main loop ------------------------------------------------------------------------------
    def run(self):
        self._mic(True)
        while True:
            with self.lock:
                while not self.utterances:
                    if not self.lock.wait(timeout=2):
                        self._keep_mic()
                        self._give_up()
                pcm, self.spoke_at = self.utterances.pop(0)
            try:
                self._handle(pcm)
            except (RuntimeError, TimeoutError, OSError) as e:   # a dropped robot link: keep listening
                self._log(f"error: {e}")
                self.mode = "idle"

    def wake_up(self):
        """Wake up as if it heard the wake word (touch.py: the head lifted while asleep)."""
        with self.lock:
            self.utterances.append((None, None))
            self.lock.notify()

    def _handle(self, pcm):
        if not self.agent.on:
            return
        if pcm is None:
            if self.mode == "idle":
                self._wake()
            return
        t0 = time.monotonic()
        text = self.stt.transcribe(pcm, self.agent.lang)
        print(json.dumps({"at": time.strftime("%H:%M:%S"), "voice": self.mode, "heard": text, "audio_s": round(len(pcm) / (2 * RATE), 2),
                          "stt_s": round(time.monotonic() - t0, 2)}, ensure_ascii=False), file=sys.stderr, flush=True)
        if not text or text.strip()[:1] in ("[", "(", "*", "-"):  # [BLANK_AUDIO], (music), *cough*, "-": not speech
            return
        if self.mode == "idle":
            m = self.wake.search(text)
            if not m:
                return
            self.agent._pub(heard=text)          # only what it reacts to, not every noise
            rest = text[m.end():].strip(" ,.!?")
            self._wake()
            if not wordy(rest):
                return
            text = rest
        elif self.wake.match(text.strip()) and not wordy(text[self.wake.match(text.strip()).end():]):
            self._wake()                         # just the wake word again: answer again, wait for the command
            return
        elif not wordy(text):
            return
        self._unlift()
        self.arms_before = None                  # a command came: the arms stay where it leaves them
        self.mode = "busy"
        if MUSIC.search(text):                   # "Hey Buddy, music!": the default dance, no model involved
            self._dance(text)
        else:
            self.agent.hear(text)
            self.agent.idle.wait(60)
        self._mic(True)
        if self.follow_s:
            self._listen(self.follow_s)          # a conversation: the next sentence needs no wake word
        else:
            self.mode = "idle"                   # every command needs the wake word again
            self.agent._pub(status="idle")

    def _wake(self):
        self.mode = "listening"
        self.agent._pub(status="listening")
        self.robot.request("face.set", expression="listening")
        # A small "I heard you" head lift (also with --no-motion), only when it is free: no turn running, nothing in its hands.
        if self.agent.idle.is_set() and not self.agent.holding and self.lifted is None:
            s = self.robot.snapshot()
            pitch, sign = s.get("head", {}).get("pitch"), s.get("calibration", {}).get("head", {}).get("pitch_sign", 1)
            if pitch is not None:
                self.lifted = pitch
                self.robot.request("head.move", id=2, deg=pitch + sign * LIFT_DEG, ms=400)
            if self.agent.motion:
                self._arms_home(s)
        self.say(HEARD.get(self.agent.lang, HEARD["en"]))
        self._listen(WAKE_S)

    def _pcm(self, text):
        if text not in self.cache:
            self.cache[text] = self.local_tts(text)
        return self.cache[text]

    def _listen(self, seconds):
        self._log(f"listening {seconds} s")
        self.mode, self.listen_until = "listening", time.monotonic() + seconds
        self.agent._pub(status="listening")

    def _arms_home(self, snapshot):
        """Arms to home (hanging down, calibration zeros), quickly, like standing at attention: it is ready to listen.
        Where they were is kept: if no command comes, _give_up puts them back."""
        joints, servos = snapshot.get("calibration", {}).get("joints", {}), snapshot.get("servos", {})
        if self.arms_before is None:
            self.arms_before = {sid: servos[sid]["deg"] for sid in ("1", "5") if "deg" in servos.get(sid, {})}
        for sid in ("1", "5"):
            if sid in servos and sid in joints:
                try:
                    self.robot.request("servo.move", id=int(sid), deg=joints[sid]["zero"], speed=2400, acc=60)
                except (RuntimeError, TimeoutError):
                    pass

    def _give_up(self):
        """No command in time (after the wake word or after an answer): back to waiting for the wake word."""
        if self.mode == "listening" and time.monotonic() > self.listen_until and not self.speech:
            self._log("no command: back to waiting for the wake word")
            self.mode = "idle"
            self._unlift()
            self._arms_back()
            self.agent._pub(status="idle")
            try:
                self.robot.request("face.set", expression="neutral")
            except (RuntimeError, TimeoutError):
                pass

    def _arms_back(self):
        """The wake word came but no command: the arms go back to where they were before it."""
        before, self.arms_before = self.arms_before, None
        for sid, deg in (before or {}).items():
            try:
                self.robot.request("servo.move", id=int(sid), deg=deg, speed=1200, acc=40)
            except (RuntimeError, TimeoutError):
                pass

    def _log(self, what):
        print(json.dumps({"at": time.strftime("%H:%M:%S"), "voice": what}), file=sys.stderr, flush=True)

    def _dance(self, text):
        from dashboard import DANCING, dance_api
        self.agent._pub(heard=text, status="dancing", thinking="", say="", steps=[{"act": {"do": "gesture", "name": "dance"}, "ok": True}])
        r = dance_api(self.robot, self.agent, {})
        if r.get("ok"):
            DANCING["dance"].thread.join(60)

    def _unlift(self):
        if self.lifted is not None:
            pitch, self.lifted = self.lifted, None
            try:
                self.robot.request("head.move", id=2, deg=pitch, ms=300)
            except (RuntimeError, TimeoutError):
                pass

    def _keep_mic(self):
        if self.mode != "busy":
            try:
                if not self.robot.request("speaker.status").get("mic"):
                    self._mic(True)
            except (RuntimeError, TimeoutError):
                pass
