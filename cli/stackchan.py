"""stackchan: control the StackChan agent firmware over USB or Wi-Fi.  Every command prints JSON.

Transport: --host (WebSocket ws://HOST:81), else --port, else the first /dev/cu.usbmodem*, else
stackchan.local over Wi-Fi.  The wire protocol is docs/protocol.md (one JSON object per line).
"""

import argparse
import base64
import getpass
import glob
import json
import os
import sys
import time

DEFAULT_HOST = "stackchan.local"


class Link:
    """One connection; request() returns the reply to its id, events are queued."""

    def __init__(self, port=None, host=None, timeout=5.0):
        self.timeout, self.next_id, self.events = timeout, 1, []
        if host is None and port is None:
            ports = sorted(glob.glob("/dev/cu.usbmodem*") + glob.glob("/dev/ttyACM*"))
            port = ports[0] if ports else None
            host = None if port else DEFAULT_HOST
        if host:
            from websockets.sync.client import connect
            import socket
            ip = socket.getaddrinfo(host, 81, socket.AF_INET, socket.SOCK_STREAM)[0][4][0]   # IPv4: .local AAAA lookups stall ~5 s
            self.via = f"ws://{ip}:81"
            self.ws = connect(self.via, open_timeout=timeout, proxy=None).__enter__()   # LAN only: skip any system proxy
            self.ser = None
        else:
            import serial
            self.ser = serial.Serial()
            self.ser.port, self.ser.baudrate, self.ser.timeout = port, 115200, 0.1
            # leave DTR/RTS at pyserial's default (both high): RTS high with DTR low resets the ESP32-S3
            self.ser.open()
            self.ws, self.via, self.buf = None, port, b""

    def send(self, obj):
        line = json.dumps(obj, separators=(",", ":"))
        if self.ws:
            self.ws.send(line)
        else:
            self.ser.write(line.encode() + b"\n")

    def recv(self, timeout):
        """Next message (dict) or None after `timeout` s."""
        end = time.time() + timeout
        while time.time() < end:
            if self.ws:
                try:
                    return json.loads(self.ws.recv(timeout=max(0.01, end - time.time())))
                except TimeoutError:
                    return None
            self.buf += self.ser.read(4096)
            while b"\n" in self.buf:
                line, self.buf = self.buf.split(b"\n", 1)
                try:
                    return json.loads(line)
                except ValueError:
                    continue      # boot log or partial line
        return None

    def request(self, cmd, timeout=None, **args):
        rid, self.next_id = self.next_id, self.next_id + 1
        self.send({"id": rid, "cmd": cmd, "args": args})
        end = time.time() + (timeout or self.timeout)
        while time.time() < end:
            m = self.recv(end - time.time())
            if m is None:
                break
            if m.get("id") == rid:
                if not m.get("ok"):
                    raise RuntimeError(f"{cmd}: {m.get('error')}")
                return m.get("result", {})
            if "ev" in m:
                self.events.append(m)
        raise TimeoutError(f"{cmd}: no reply in {timeout or self.timeout} s via {self.via}")


def wait_still(link, sid, seconds=3.0):
    """Poll until servo `sid` stops moving; returns its last state."""
    end, s = time.time() + seconds, None
    time.sleep(0.15)
    while time.time() < end:
        s = link.request("servo.read", id=sid)
        if not s["moving"]:
            break
        time.sleep(0.05)
    return s


def selftest(link, ids, deg):
    """Each servo: hold where it is, half torque, slow +-deg toward mid-travel, back; check it got there."""
    report = []
    for sid in ids:
        r = {"id": sid}
        try:
            s0 = link.request("servo.read", id=sid)
            r.update(start_deg=s0["deg"], volt=s0["volt"], temp=s0["temp"])
            link.request("servo.torque_limit", id=sid, permille=500)
            link.request("servo.move", id=sid, deg=s0["deg"], speed=300, acc=10)   # goal = where it is, then torque
            link.request("servo.torque", id=sid, on=True)
            target = s0["deg"] + (deg if s0["deg"] < 0 else -deg)                 # toward the middle of travel
            link.request("servo.move", id=sid, deg=target, speed=300, acc=10)
            s1 = wait_still(link, sid)
            link.request("servo.move", id=sid, deg=s0["deg"], speed=300, acc=10)
            s2 = wait_still(link, sid)
            r.update(target_deg=target, reached_deg=s1["deg"], back_deg=s2["deg"], peak_load=max(abs(s1["load"]), abs(s2["load"])),
                     error_deg=round(max(abs(s1["deg"] - target), abs(s2["deg"] - s0["deg"])), 1))
            r["ok"] = r["error_deg"] < 2.0
        except (RuntimeError, TimeoutError) as e:
            r.update(ok=False, error=str(e))
        finally:
            try:
                link.request("servo.torque_limit", id=sid, permille=1000)
            except (RuntimeError, TimeoutError):
                pass
        report.append(r)
    ok = all(r["ok"] for r in report) and bool(report)
    link.request("face.set", expression="happy" if ok else "doubt", say="selftest ok" if ok else "selftest failed", ms=4000)
    return {"ok": ok, "servos": report}


def parse_ids(text):
    return [int(x) for x in text.split(",") if x]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="stackchan", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", help="USB serial port")
    ap.add_argument("--host", help=f"Wi-Fi: hostname or IP (default {DEFAULT_HOST} when no USB)")
    ap.add_argument("--timeout", type=float, default=5.0)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("info", help="firmware, Wi-Fi, bus")
    p = sub.add_parser("scan", help="ping servo ids on the bus")
    p.add_argument("--from", dest="lo", type=int, default=0)
    p.add_argument("--to", dest="hi", type=int, default=253)
    sub.add_parser("detect", help="search the Grove ports for the servo bus again")
    p = sub.add_parser("read", help="servo state")
    p.add_argument("id", type=int)
    p = sub.add_parser("move", help="move one servo to an angle (deg, 0 = raw 2048)")
    p.add_argument("id", type=int)
    p.add_argument("deg", type=float)
    p.add_argument("--speed", type=int, default=600, help="steps/s (4096 steps = 360 deg)")
    p.add_argument("--acc", type=int, default=20)
    p.add_argument("--wait", action="store_true", help="wait until it stops, print the final state")
    p = sub.add_parser("sync", help="move several servos together: ID=DEG ...")
    p.add_argument("targets", nargs="+")
    p.add_argument("--speed", type=int, default=600)
    p.add_argument("--acc", type=int, default=20)
    p = sub.add_parser("torque", help="torque on/off (off = limp, move by hand)")
    p.add_argument("id", type=int)
    p.add_argument("state", choices=["on", "off"])
    p = sub.add_parser("set-id", help="change a servo id (only that servo on the bus if ids collide)")
    p.add_argument("id", type=int)
    p.add_argument("new_id", type=int)
    p = sub.add_parser("limits", help="read or set soft limits (deg)")
    p.add_argument("id", type=int)
    p.add_argument("lo", type=float, nargs="?")
    p.add_argument("hi", type=float, nargs="?")
    p = sub.add_parser("face", help="set an expression; `face --list` lists them, `face demo` plays them all")
    p.add_argument("expression", nargs="?")
    p.add_argument("--list", action="store_true")
    p.add_argument("--idle", choices=["on", "off"], help="daydream on its own after 15 s without input")
    p.add_argument("--say")
    p.add_argument("--ms", type=int, default=0)
    p.add_argument("--gaze", type=float, nargs=2, metavar=("V", "H"))
    p.add_argument("--mouth", type=float)
    p = sub.add_parser("stream", help="state events as NDJSON on stdout")
    p.add_argument("--ids", required=True, help="e.g. 1,2,3")
    p.add_argument("--hz", type=int, default=20)
    p.add_argument("--seconds", type=float, default=0, help="0 = until Ctrl-C")
    p = sub.add_parser("gesture", help="play a gesture (wave, nod, shake): keyframes sent as primitive moves")
    p.add_argument("name")
    p = sub.add_parser("watch", help="react (face + gesture) when what the camera sees changes; NDJSON events")
    p.add_argument("--gesture", default="wave")
    p.add_argument("--threshold", type=float, help="mean gray difference 0..255 (default: from the camera noise)")
    p.add_argument("--times", type=int, default=0, help="stop after N reactions (0 = run until Ctrl-C)")
    p = sub.add_parser("view", help="3D body on the live page: simple (two shoulder servos) | full (r7 arms)")
    p.add_argument("body", choices=["simple", "full"])
    p.add_argument("--dash", default="http://127.0.0.1:8765", help="live page address")
    p = sub.add_parser("calibrate", help="robot in its home pose (arms hanging down, head straight): save the angles as zero")
    p.add_argument("--arms", action="store_true", help="only the arms (leave the head zeros)")
    p = sub.add_parser("selftest", help="move each servo a little and check it got there")
    p.add_argument("--ids", help="default: every id on the bus")
    p.add_argument("--deg", type=float, default=10.0)
    p = sub.add_parser("status", help="one look at everything: info + every servo's state")
    p.add_argument("--ids", help="default: every id on the bus")
    p = sub.add_parser("snap", help="camera picture -> JPEG file")
    p.add_argument("-o", "--out", default="stackchan_camera.jpg")
    p.add_argument("--quality", type=int)
    p = sub.add_parser("face-snap", help="what the screen shows -> JPEG file")
    p.add_argument("-o", "--out", default="stackchan_face.jpg")
    p = sub.add_parser("dash", help="live web page (camera, face, servos) for any browser on the LAN")
    p.add_argument("--listen", default="0.0.0.0")
    p.add_argument("--http-port", type=int, default=8765)
    p.add_argument("--qr", default=os.environ.get("STACKCHAN_QR"), help="show this link as a QR code in the page corner")
    p.add_argument("--ids", help="default: every id on the bus")
    p.add_argument("--hz", type=int, default=10)
    p.add_argument("--fps", type=int, default=5)
    p.add_argument("--llm-url", default=os.environ.get("STACKCHAN_LLM_URL"),
                   help="OpenAI-compatible endpoint (e.g. http://localhost:8000/v1): enables the agent")
    p.add_argument("--llm-model", default=os.environ.get("STACKCHAN_LLM_MODEL", "default"))
    p.add_argument("--agent", action="store_true", help="start with the agent switched on")
    p.add_argument("--no-record", action="store_true", help="do not write episodes to ~/.stackchan/episodes")
    p.add_argument("--no-motion", action="store_true", help="agent thinks and changes faces but never moves a servo (except a small head lift on wake-up)")
    p.add_argument("--whisper-model", default=os.environ.get("STACKCHAN_WHISPER_MODEL"),
                   help="whisper.cpp ggml model: enables voice (wake word 'Hey Grok', robot mic + speaker)")
    p.add_argument("--tts-voice", default=os.environ.get("STACKCHAN_TTS_VOICE"),
                   help="Kokoro voice (default af_heart / zf_xiaoxiao by language) or a macOS `say` voice")
    p.add_argument("--llm-think", choices=["low", "high", "off"], default="low",
                   help="how much the model reasons before acting: low (fast, default), high, off (fastest)")
    p.add_argument("--lang", choices=["zh", "en"], default=os.environ.get("STACKCHAN_LANG", "en"),
                   help="language the agent speaks; switch at runtime with `stackchan agent lang zh|en`")
    p = sub.add_parser("dance", help="the default dance with its music, through a running dash; `dance stop` = emergency stop")
    p.add_argument("action", nargs="?", choices=["stop"])
    p.add_argument("--dry-run", action="store_true", help="print the timeline and check limits; no robot")
    p.add_argument("--amp", type=float, default=1.0, help="amplitude 0..1 (0.5 for a first careful run)")
    p.add_argument("--loop", type=int, default=1)
    p.add_argument("--dash", default="http://127.0.0.1:8765")
    p = sub.add_parser("agent", help="control the agent of a running dash: on | off | say TEXT | lang zh|en")
    p.add_argument("action", choices=["on", "off", "say", "status", "lang"])
    p.add_argument("text", nargs="*")
    p.add_argument("--dash", default="http://127.0.0.1:8765")
    p = sub.add_parser("wifi", help="scan | list | status | set SSID | forget SSID")
    p.add_argument("action", choices=["scan", "list", "status", "set", "forget"])
    p.add_argument("ssid", nargs="?")
    p.add_argument("--pass-stdin", action="store_true", help="read the password from stdin (no prompt)")
    p = sub.add_parser("raw", help="send one protocol command: CMD [JSON args]")
    p.add_argument("command")
    p.add_argument("args", nargs="?", default="{}")
    sub.add_parser("reboot")
    a = ap.parse_args(argv)

    out = lambda obj: print(json.dumps(obj, ensure_ascii=False), flush=True)   # noqa: E731
    if a.cmd == "dance" and a.dry_run:
        import dance
        return 0 if dance.dry_run(a.amp) else 1
    if a.cmd in ("view", "agent", "dance"):     # these talk to a running `dash`, not to the robot
        import urllib.parse
        import urllib.request
        if a.cmd == "view":
            q = f"/api/body?set={a.body}"
        elif a.cmd == "dance":
            q = "/api/dance?stop=1" if a.action == "stop" else f"/api/dance?amp={a.amp}&loop={a.loop}"
        else:
            q = "/api/agent?" + {"on": "on=1", "off": "on=0", "status": "", "lang": "lang=" + "".join(a.text)}.get(
                a.action, "say=" + urllib.parse.quote_plus(" ".join(a.text)))
        try:
            out(json.loads(urllib.request.urlopen(a.dash + q, timeout=5).read()))
        except OSError as e:
            out({"ok": False, "error": f"live page not reachable at {a.dash}: {e}"})
        return 0
    if a.cmd == "dash":     # needs Wi-Fi: camera frames only go over WebSocket
        from dashboard import serve
        llm = a.llm_url and {"url": a.llm_url, "model": a.llm_model, "api_key": os.environ.get("STACKCHAN_LLM_KEY"),
                             "on": a.agent, "record": not a.no_record, "motion": not a.no_motion,
                             "whisper_model": a.whisper_model, "tts_voice": a.tts_voice, "lang": a.lang, "think": a.llm_think}
        serve(a.host or DEFAULT_HOST, parse_ids(a.ids) if a.ids else None, a.hz, a.fps, a.listen, a.http_port, llm, a.qr)
        return 0
    try:
        link = Link(a.port, a.host, a.timeout)
    except Exception as e:   # serial / socket / WebSocket handshake errors  # noqa: BLE001
        out({"ok": False, "error": f"cannot connect ({a.host or a.port or 'auto'}): {e}"})
        return 1
    rq = link.request
    try:
        if a.cmd == "info":
            out({"via": link.via, **rq("sys.info")})
        elif a.cmd == "scan":
            out(rq("bus.scan", timeout=10, **{"from": a.lo, "to": a.hi}))
        elif a.cmd == "detect":
            out(rq("bus.detect", timeout=10))
        elif a.cmd == "read":
            out(rq("servo.read", id=a.id))
        elif a.cmd == "move":
            r = rq("servo.move", id=a.id, deg=a.deg, speed=a.speed, acc=a.acc)
            out({**r, "final": wait_still(link, a.id, 10)} if a.wait else r)
        elif a.cmd == "sync":
            targets = [{"id": int(i), "deg": float(d)} for i, d in (t.split("=") for t in a.targets)]
            out(rq("servo.sync_move", targets=targets, speed=a.speed, acc=a.acc))
        elif a.cmd == "torque":
            out(rq("servo.torque", id=a.id, on=a.state == "on"))
        elif a.cmd == "set-id":
            out(rq("servo.set_id", id=a.id, new_id=a.new_id))
        elif a.cmd == "limits":
            args = {"lo_deg": a.lo, "hi_deg": a.hi} if a.hi is not None else {}
            out(rq("servo.limits", id=a.id, **args))
        elif a.cmd == "face" and a.list:
            out(rq("face.expressions"))
        elif a.cmd == "face" and a.expression == "demo":
            for e in rq("face.expressions")["expressions"]:
                rq("face.set", expression=e, say=e, ms=2200)
                out({"expression": e})
                time.sleep(2.5)
            out(rq("face.set", expression="neutral", say=""))
        elif a.cmd == "face":
            args = {k: v for k, v in {"expression": a.expression, "say": a.say, "gaze": a.gaze, "mouth": a.mouth}.items() if v is not None}
            if a.idle:
                args["idle"] = a.idle == "on"
            out(rq("face.set", ms=a.ms, **args))
        elif a.cmd == "stream":
            rq("stream.start", ids=parse_ids(a.ids), hz=a.hz)
            end = time.time() + a.seconds if a.seconds else float("inf")
            for e in link.events:
                out(e)
            while time.time() < end:
                m = link.recv(min(1.0, end - time.time()))
                if m and "ev" in m:
                    out(m)
            rq("stream.stop")
        elif a.cmd == "gesture":
            from gestures import GESTURES, play
            if a.name not in GESTURES:
                raise RuntimeError(f"unknown gesture {a.name!r}; known: {', '.join(GESTURES)}")
            out(play(link, a.name))
        elif a.cmd == "watch":
            from watch import watch
            watch(link, a.gesture, a.threshold, a.times)
        elif a.cmd == "calibrate":
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calibration.json")
            cal = json.load(open(path))
            done = {}
            for sid, j in cal["joints"].items():
                try:
                    j["zero"] = done[sid] = link.request("servo.read", id=int(sid))["deg"]
                except (RuntimeError, TimeoutError):
                    pass                      # not connected yet: keep the old zero
            for h in [] if a.arms else link.request("head.read")["servos"]:
                cal["head"]["yaw_zero" if h["id"] == 1 else "pitch_zero"] = done["head_" + str(h["id"])] = h["deg"]
            json.dump(cal, open(path, "w"), indent=2)
            out({"file": path, "zero": done})
        elif a.cmd == "selftest":
            ids = parse_ids(a.ids) if a.ids else rq("bus.scan", timeout=10)["ids"]
            out(selftest(link, ids, a.deg))
        elif a.cmd == "status":
            info = rq("sys.info")
            ids = parse_ids(a.ids) if a.ids else (rq("bus.scan", timeout=10, **{"from": 0, "to": 20})["ids"] if info["bus"]["ok"] else [])
            servos = []
            for sid in ids:
                try:
                    servos.append(rq("servo.read", id=sid))
                except (RuntimeError, TimeoutError) as e:
                    servos.append({"id": sid, "error": str(e)})
            out({"via": link.via, **info, "servos": servos})
        elif a.cmd in ("snap", "face-snap"):
            args = {"quality": a.quality} if a.cmd == "snap" and a.quality else {}
            r = rq("camera.snap" if a.cmd == "snap" else "face.snap", timeout=10, **args)
            with open(a.out, "wb") as f:
                f.write(base64.b64decode(r["jpeg"]))
            out({"file": os.path.abspath(a.out), "bytes": r["bytes"]})
        elif a.cmd == "wifi":
            if a.action in ("set", "forget") and not a.ssid:
                ap.error(f"wifi {a.action} needs an SSID")
            if a.action == "set":
                pw = sys.stdin.readline().rstrip("\n") if a.pass_stdin else getpass.getpass(f"password for {a.ssid}: ")
                out(rq("wifi.set", ssid=a.ssid, **{"pass": pw}))
            elif a.action == "forget":
                out(rq("wifi.forget", ssid=a.ssid))
            else:
                out(rq(f"wifi.{a.action}", timeout=15))
        elif a.cmd == "raw":
            out(rq(a.command, **json.loads(a.args)))
        elif a.cmd == "reboot":
            link.send({"cmd": "sys.reboot"})
            out({"ok": True})
    except (RuntimeError, TimeoutError) as e:
        out({"ok": False, "error": str(e)})
        return 1
    except KeyboardInterrupt:
        if a.cmd == "stream":
            rq("stream.stop")
    return 0


if __name__ == "__main__":
    sys.exit(main())
