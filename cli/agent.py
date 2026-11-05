"""The agent: hears a sentence, looks through the camera, asks an LLM, streams primitive steps to the robot.

The model answers one JSON object per line, and each line runs as soon as it arrives:
  {"say": "text"}                       speak / show a caption
  {"do": "face", "expression": "happy"} neutral happy sad angry doubt sleepy surprised
  {"do": "gesture", "name": "wave"}     any name in gestures.py
  {"do": "head", "yaw": 10, "pitch": 5} degrees from the head's home pose (yaw +-30, pitch -10..15)
  {"do": "arm", "side": "left", "deg": 30}  0 = home, up to 60 toward the middle of travel
  {"do": "wait", "s": 1}
Motion steps are paced at about one per second.  State for the live page is published through robot._set().
"""
import base64
import json
import queue
import threading
import time

import gestures
import llm
from journal import Journal

STEP_S = 1.0
SYSTEM = """You are StackChan, a small, cute desk robot: a cube head with two eyes on a screen, two arms, wheels.
You see through the camera in your face. Reply ONLY with JSON objects, one per line, no other text:
{"say": "..."} {"do": "face", "expression": E} {"do": "gesture", "name": G} {"do": "head", "yaw": deg, "pitch": deg}
{"do": "arm", "side": "left"|"right", "deg": 0..60} {"do": "wait", "s": seconds}
E: neutral happy sad angry doubt sleepy surprised.  G: %s.  head yaw -30..30 (+ = your left), pitch -10..15 (+ = up).
Start with a short "say" (one sentence), then at most 5 steps. Think briefly. %s"""
LANGS = {"zh": "Always speak Mandarin Chinese (简体中文), whatever language you hear.", "en": "Always speak English."}


class Agent(threading.Thread):
    def __init__(self, robot, url, model, api_key=None, record=True, motion=True, lang="en"):
        super().__init__(daemon=True)
        self.robot, self.url, self.model, self.api_key = robot, url, model, api_key
        self.heard, self.on, self.history = queue.Queue(), False, []
        self.idle = threading.Event()             # set between turns (voice.py waits on it)
        self.idle.set()
        self.holding = False                      # set while a gripper holds something (no idle head cues)
        self.journal, self.motion, self.lang = Journal(record), motion, lang
        self.speak = lambda text: robot.request("face.set", say=text, ms=4000)   # voice.py replaces this
        self.view = {"on": False, "lang": lang, "status": "off", "heard": "", "thinking": "", "say": "", "steps": [], "turns": 0}

    def _pub(self, **kv):
        self.view.update(kv)
        self.robot._set(agent=dict(self.view, steps=list(self.view["steps"])))

    def switch(self, on):
        self.on = on
        self._pub(on=on, status="idle" if on else "off")

    def set_lang(self, lang):
        if lang not in LANGS:
            raise ValueError(f"lang must be one of {', '.join(LANGS)}")
        self.lang = lang
        self._pub(lang=lang)

    def hear(self, text):
        self.heard.put(text)

    def run(self):
        while True:
            text = self.heard.get()
            if not self.on:
                continue
            self.idle.clear()
            try:
                self.turn(text)
            except Exception as e:  # noqa: BLE001 - keep the agent alive, show the error
                self._pub(status=f"error: {e}")
            finally:
                self.idle.set()

    def turn(self, text):
        cal = self.robot.snapshot().get("calibration", {})
        jpeg = self.robot.jpeg
        self._pub(status="thinking", heard=text, thinking="", say="", steps=[])
        self.robot.request("face.set", expression="thinking")
        content = [{"type": "text", "text": f"Heard: {text!r}\nState: {json.dumps(self._state())}"}]
        if jpeg:
            content.append({"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()}})
        messages = [{"role": "system", "content": SYSTEM % (", ".join(gestures.GESTURES), LANGS[self.lang])}, *self.history[-6:],
                    {"role": "user", "content": content}]
        t0, steps = time.time(), []

        def think(delta):
            self._pub(thinking=self.view["thinking"] + delta)

        def line(raw):
            try:
                act = json.loads(raw)
            except ValueError:
                return
            self._pub(status="acting")
            steps.append(self.step(act, cal))

        answer = llm.stream(self.url, self.model, messages, think, line, api_key=self.api_key)
        self.history += [{"role": "user", "content": f"Heard: {text!r}"}, {"role": "assistant", "content": answer}]
        self.journal.write({"heard": text, "thinking": self.view["thinking"], "answer": answer, "steps": steps,
                            "state": self._state(), "seconds": round(time.time() - t0, 2)}, jpeg)
        self._pub(status="idle", turns=self.view["turns"] + 1)
        if not any(s["act"].get("do") == "face" for s in steps):
            self.robot.request("face.set", expression="neutral")

    def _state(self):
        s = self.robot.snapshot()
        return {"servos": {k: v.get("deg") for k, v in s.get("servos", {}).items()}, "head": s.get("head", {})}

    def step(self, act, cal):
        t0, rec = time.time(), {"act": act, "ok": True}
        self._pub(steps=self.view["steps"] + [rec])
        try:
            self.run_step(act, cal)
        except Exception as e:  # noqa: BLE001 - one bad step must not stop the turn
            rec.update(ok=False, error=str(e))
        rec["ms"] = int((time.time() - t0) * 1000)
        self._pub(steps=self.view["steps"])
        return rec

    def run_step(self, act, cal):
        r, do = self.robot, act.get("do")
        if not self.motion and do in ("gesture", "head", "arm"):
            act["skipped"] = "no-motion"
            return
        if "say" in act:
            self._pub(say=act["say"])
            self.speak(str(act["say"]))
        elif do == "face":
            r.request("face.set", expression=act.get("expression", "neutral"))
        elif do == "gesture":
            gestures.play(r, act.get("name", "wave"))
        elif do == "head":
            h = cal.get("head", {})
            for hid, key, lo, hi in ((1, "yaw", -30, 30), (2, "pitch", -10, 15)):
                if key in act:
                    v = max(lo, min(hi, float(act[key])))
                    r.request("head.move", id=hid, deg=h.get(f"{key}_zero", 0) + h.get(f"{key}_sign", 1) * v, ms=500)
            time.sleep(STEP_S)
        elif do == "arm":
            sid = {"left": 1, "right": 5}.get(act.get("side"))
            j = cal.get("joints", {}).get(str(sid))
            if not j or str(sid) not in r.snapshot().get("servos", {}):
                raise RuntimeError(f"arm {act.get('side')!r} is not connected")
            deg = max(0.0, min(60.0, float(act.get("deg", 0))))
            toward_mid = -1 if j["zero"] > 0 else 1
            r.request("servo.move", id=sid, deg=j["zero"] + toward_mid * deg, speed=800, acc=30)
            time.sleep(STEP_S)
        elif do == "wait":
            time.sleep(max(0.0, min(3.0, float(act.get("s", 1)))))
        else:
            raise RuntimeError(f"unknown step {act}")
