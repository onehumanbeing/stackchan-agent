"""Voice loop on the robot's own mic and speaker: wake word -> listen -> agent -> spoken reply.

Mic audio arrives as 16 kHz int16 chunks (robot.on_audio).  An energy VAD cuts it into utterances;
whisper.cpp (whisper-server, started here, local) transcribes them.  While idle, an utterance that
starts with the wake phrase ("Hey Buddy") wakes the robot: it answers, looks up and, when it has nothing
else to do, lifts its head a little until the command is in.  The next utterance goes to the agent.
Replies are spoken with a local TTS (Kokoro, else macOS `say`) and
streamed to the robot's speaker; the mic is off while it speaks (the board is half duplex).
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

RATE, CHUNK_S = 16000, 0.04
WAKE = re.compile(r"(?:^[\s,.!]*|(?:hey|hi|hay|hei|a|ay|eh|ok|okay|嘿|黑|嗨|哈)[\s,.!，。！、]*)(?<![a-z])(buddy|buddie|buddi|budy|bodhi|bodie|baddy|巴迪|巴蒂|八迪)(?![a-z])"
                  r"|(?:hey|hi|嘿|嗨)[\s,.!，。！、]*(body|bud|betty|birdie)(?![a-z])", re.I)
MUSIC = re.compile(r"\bmusic\b|音乐", re.I)    # a spoken command with this starts the dance (dance.py)
PREROLL_S = 0.4              # audio kept from before the level rises, so soft starts ("Hey") are not cut
# No whisper --prompt: with "Hey Buddy" as a prompt it hears "Buddy." in silence and servo noise.
HEARD = {"zh": "我在听", "en": "Listening"}
LIFT_DEG = 8
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
    def __init__(self, robot, agent, whisper_model, tts_voice=None, wake=WAKE):
        super().__init__(daemon=True)
        self.robot, self.agent, self.wake = robot, agent, wake
        self.tts = make_tts(tts_voice)
        self.cache = {}                          # wake replies, rendered once: TTS takes about a second
        threading.Thread(target=lambda: [self._pcm(t) for t in HEARD.values()], daemon=True).start()
        self.stt = Whisper(whisper_model)
        self.mode = "idle"                       # idle (wake word) | listening (command) | busy
        self.buf, self.speech, self.silence, self.floor = bytearray(), False, 0.0, 200.0
        self.utterances, self.lifted, self.deaf_until, self.pre = [], None, 0.0, b""     # pitch to go back to after a wake-up lift
        self.lock = threading.Condition()
        robot.on_audio = self.feed
        agent.speak = self.say

    # --- mic side -------------------------------------------------------------------------------
    def feed(self, pcm):
        if self.mode == "busy" or time.monotonic() < self.deaf_until:   # speaking, or its echo
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
        end = 0.5 if self.mode == "idle" else 0.8     # the wake phrase is short: answer it sooner
        if self.silence >= end or seconds > 12:
            self.speech = False
            if seconds - PREROLL_S - self.silence >= 0.3:   # at least 0.3 s of actual sound
                with self.lock:
                    self.utterances.append(bytes(self.buf))
                    self.lock.notify()

    def _mic(self, on):
        try:
            self.robot.request("mic.start" if on else "mic.stop")
        except (RuntimeError, TimeoutError):
            pass

    # --- speaker side ---------------------------------------------------------------------------
    def say(self, text):
        self.robot.request("face.set", say=text, ms=4000)
        pcm = self._pcm(text) if text in HEARD.values() else self.tts(text)
        prev, self.mode = self.mode, "busy"
        self.robot.send_audio(pcm)
        self.robot.request("face.set", mouth=0.7)          # the eyes bob while it talks
        time.sleep(len(pcm) / (2 * RATE) + 0.3)
        for _ in range(30):                      # until the robot's queue is empty
            if not self.robot.request("speaker.status").get("playing"):
                break
            time.sleep(0.1)
        self.robot.request("face.set", mouth=0)
        self.mode = prev if prev != "busy" else "idle"
        self.deaf_until = time.monotonic() + 0.4
        self._mic(True)

    def _pcm(self, text):
        if text not in self.cache:
            self.cache[text] = self.tts(text)
        return self.cache[text]

    # --- main loop ------------------------------------------------------------------------------
    def run(self):
        self._mic(True)
        while True:
            with self.lock:
                while not self.utterances:
                    if not self.lock.wait(timeout=2):
                        self._keep_mic()
                        self._give_up()
                pcm = self.utterances.pop(0)
            if not self.agent.on:
                continue
            t0 = time.monotonic()
            text = self.stt.transcribe(pcm, self.agent.lang)
            print(json.dumps({"voice": self.mode, "heard": text, "audio_s": round(len(pcm) / (2 * RATE), 2),
                              "stt_s": round(time.monotonic() - t0, 2)}, ensure_ascii=False), file=sys.stderr, flush=True)
            if not text or text.startswith("["):  # [BLANK_AUDIO], [Music] ...
                continue
            if self.mode == "idle":
                m = self.wake.search(text)
                if not m:
                    continue
                self.agent._pub(heard=text)          # only what it reacts to, not every noise
                rest = text[m.end():].strip(" ,.!?")
                self._wake()
                if not wordy(rest):
                    continue
                text = rest
            elif self.wake.match(text.strip()) and not wordy(text[self.wake.match(text.strip()).end():]):
                self._wake()                         # just the wake word again: answer again, wait for the command
                continue
            elif not wordy(text):
                continue
            self._unlift()
            self.mode = "busy"
            if MUSIC.search(text):                   # "Hey Buddy, music!": the default dance, no model involved
                self._dance(text)
            else:
                self.agent.hear(text)
                self.agent.idle.wait(60)
            self._mic(True)
            self._listen(FOLLOW_S)                   # a conversation: the next sentence needs no wake word

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
                self.robot.request("head.move", id=2, deg=pitch + sign * LIFT_DEG, ms=250)
            if self.agent.motion:
                self._arms_home(s)
        self.say(HEARD.get(self.agent.lang, HEARD["en"]))
        self._listen(WAKE_S)

    def _listen(self, seconds):
        self.mode, self.listen_until = "listening", time.monotonic() + seconds
        self.agent._pub(status="listening")

    def _arms_home(self, snapshot):
        """Arms back to home (hanging down, calibration zeros), quickly: it is ready to listen."""
        joints = snapshot.get("calibration", {}).get("joints", {})
        for sid in ("1", "5"):
            if sid in snapshot.get("servos", {}) and sid in joints:
                try:
                    self.robot.request("servo.move", id=int(sid), deg=joints[sid]["zero"], speed=2400, acc=60)
                except (RuntimeError, TimeoutError):
                    pass

    def _give_up(self):
        """No command in time (after the wake word or after an answer): back to waiting for the wake word."""
        if self.mode == "listening" and time.monotonic() > self.listen_until and not self.speech:
            self.mode = "idle"
            self._unlift()
            self.agent._pub(status="idle")
            try:
                self.robot.request("face.set", expression="neutral")
            except (RuntimeError, TimeoutError):
                pass

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
