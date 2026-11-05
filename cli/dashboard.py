"""`stackchan dash`: a live web page of the robot (camera, face, servos, faults) on this computer.

One WebSocket to the robot (state stream + camera frames + periodic info / face snapshots), shared
by any number of browsers.  Binds 0.0.0.0, so other machines on the LAN can open it.
Endpoints: /  /state.json  /events (SSE)  /camera.mjpg  /camera.jpg  /face.jpg
"""

import base64
import json
import queue
import socket
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).parent
PAGE = HERE / "dashboard.html"
STATIC = {"/twin/scene.js": ("twin/scene.js", "text/javascript"), "/twin/model.js": ("twin/model.js", "text/javascript"),
          "/model.json": ("model/r7.json", "application/json")}
CALIBRATION = HERE / "calibration.json"


class Reply:
    def __init__(self):
        self.done, self.msg = threading.Event(), {}


class Robot(threading.Thread):
    """Keeps one connection to the robot and the latest of everything; reconnects on errors."""

    def __init__(self, host, ids, hz, fps):
        super().__init__(daemon=True)
        self.host, self.ids, self.hz, self.fps = host, ids, hz, fps
        self.lock, self.changed = threading.Lock(), threading.Condition()
        cal = json.loads(CALIBRATION.read_text())
        self.state = {"connected": False, "info": {}, "servos": {}, "faults": [], "camera_fps": 0.0, "head": {},
                      "calibration": cal, "body": cal.get("body", "simple")}
        self.jpeg = self.face = None
        self.frames = []
        self.outbox = queue.Queue()          # (cmd, args, Reply) from other threads, e.g. the agent
        self.on_audio = None                 # callback(pcm bytes) for 'A' microphone frames

    def send_audio(self, pcm):
        """Queue 16 kHz mono int16 audio for the robot's speaker (sent as 'S' frames of <= 4 KB)."""
        for i in range(0, len(pcm), 4096):
            self.outbox.put((None, b"S" + pcm[i:i + 4096], None))

    def request(self, cmd, timeout=5.0, **args):
        """Thread-safe command over the shared connection; returns the result or raises RuntimeError."""
        reply = Reply()
        self.outbox.put((cmd, args, reply))
        if not reply.done.wait(timeout):
            raise TimeoutError(f"{cmd}: no reply in {timeout} s")
        if not reply.msg.get("ok"):
            raise RuntimeError(f"{cmd}: {reply.msg.get('error')}")
        return reply.msg.get("result", {})

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(self.state))

    def set_body(self, body):
        """3D body variant ("simple" | "full"), remembered in calibration.json."""
        cal = json.loads(CALIBRATION.read_text())
        cal["body"] = body
        CALIBRATION.write_text(json.dumps(cal, indent=2) + "\n")
        self._set(body=body, calibration=cal)

    def _set(self, **kv):
        with self.lock:
            self.state.update(kv)
        with self.changed:
            self.changed.notify_all()

    def run(self):
        while True:
            try:
                self._session()
            except Exception as e:  # noqa: BLE001 - any link error: show it, retry
                self._set(connected=False, error=str(e))
            time.sleep(2)

    def _session(self):
        from websockets.sync.client import connect
        ip = socket.getaddrinfo(self.host, 81, socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
        with connect(f"ws://{ip}:81", open_timeout=5, proxy=None, max_size=2**22) as ws:
            rid = iter(range(1, 1 << 30))
            pending = {}

            waiting = {}                     # request id -> Reply, for request()

            def ask(cmd, reply=None, **args):
                i = next(rid)
                pending[i] = cmd
                if reply:
                    waiting[i] = reply
                ws.send(json.dumps({"id": i, "cmd": cmd, "args": args}))

            ids = self.ids or []
            if ids:
                ask("stream.start", ids=ids, hz=self.hz)
            ask("camera.start", fps=self.fps)
            self._set(connected=True, error="", via=f"ws://{ip}:81")
            next_info = next_scan = next_head = 0.0
            while True:
                now = time.time()
                if not self.ids and now >= next_scan:   # servos come and go while the robot is assembled
                    ask("bus.scan", **{"from": 0, "to": 20})
                    next_scan = now + 5.0
                if now >= next_info:
                    ask("sys.info")
                    ask("face.snap")
                    next_info = now + 1.0
                if now >= next_head:
                    ask("head.read")
                    next_head = now + 0.2
                while not self.outbox.empty():
                    c, args, reply = self.outbox.get_nowait()
                    if c is None:
                        ws.send(args)            # raw binary frame
                    else:
                        ask(c, reply, **args)
                try:
                    msg = ws.recv(timeout=0.02)
                except TimeoutError:
                    continue
                if isinstance(msg, bytes) and msg[:1] == b"A":     # microphone chunk
                    if self.on_audio:
                        self.on_audio(msg[1:])
                    continue
                if isinstance(msg, bytes):          # camera frame ('J')
                    self.jpeg = msg[1:]
                    self.frames = [t for t in self.frames if now - t < 2] + [now]
                    self._set(camera_fps=round(len(self.frames) / 2, 1))
                    continue
                m = json.loads(msg)
                cmd = pending.pop(m.get("id"), None)
                if m.get("id") in waiting:
                    r = waiting.pop(m["id"])
                    r.msg = m
                    r.done.set()
                    continue
                if m.get("ev") == "state":
                    with self.lock:
                        self.state["servos"] = {str(s["id"]): s for s in m["servos"]}
                        self.state["t"] = m["t"]
                    self._set()
                elif m.get("ev") == "fault":
                    with self.lock:
                        self.state["faults"] = (self.state["faults"] + [{**m, "at": time.strftime("%H:%M:%S")}])[-20:]
                elif cmd == "bus.scan" and m.get("ok"):
                    if m["result"]["ids"] != ids:
                        ids = m["result"]["ids"]
                        ask("stream.start", ids=ids, hz=self.hz) if ids else ask("stream.stop")
                        self._set(ids=ids)
                elif cmd == "head.read" and m.get("ok"):
                    self._set(head={("yaw" if h["id"] == 1 else "pitch"): h["deg"] for h in m["result"]["servos"]})
                elif cmd == "sys.info" and m.get("ok"):
                    self._set(info=m["result"])
                elif cmd == "face.snap" and m.get("ok"):
                    self.face = base64.b64decode(m["result"]["jpeg"])


def lan_ips():
    out = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            out.add(info[4][0])
    except OSError:
        pass
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.168.0.1", 9))       # no packet is sent: just picks the LAN interface
        out.add(s.getsockname()[0])
    except OSError:
        pass
    finally:
        s.close()
    return sorted(ip for ip in out if not ip.startswith("127."))


def make_handler(robot, agent=None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, body, ctype, code=200):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            path = self.path.split("?")[0]
            if path == "/":
                self._send(PAGE.read_bytes(), "text/html; charset=utf-8")
            elif path == "/api/agent":
                if not agent:
                    return self._send(b'{"ok":false,"error":"no agent: start dash with --llm-url"}', "application/json", 400)
                q = {k: urllib.parse.unquote_plus(v) for k, v in (p.split("=", 1) for p in self.path.partition("?")[2].split("&") if "=" in p)}
                if "on" in q:
                    agent.switch(q["on"] in ("1", "true", "on"))
                if q.get("lang"):
                    try:
                        agent.set_lang(q["lang"])
                    except ValueError as e:
                        return self._send(json.dumps({"ok": False, "error": str(e)}).encode(), "application/json", 400)
                if q.get("say"):
                    agent.hear(q["say"])
                self._send(json.dumps({"ok": True, **agent.view}).encode(), "application/json")
            elif path == "/api/body":
                body = dict(p.split("=", 1) for p in self.path.partition("?")[2].split("&") if "=" in p).get("set")
                if body not in ("simple", "full"):
                    return self._send(b'{"ok":false,"error":"set=simple|full"}', "application/json", 400)
                robot.set_body(body)
                self._send(json.dumps({"ok": True, "body": body}).encode(), "application/json")
            elif path in STATIC:
                self._send((HERE / STATIC[path][0]).read_bytes(), STATIC[path][1])
            elif path == "/state.json":
                self._send(json.dumps(robot.snapshot()).encode(), "application/json")
            elif path in ("/camera.jpg", "/face.jpg"):
                img = robot.jpeg if path == "/camera.jpg" else robot.face
                self._send(img, "image/jpeg") if img else self._send(b"no image yet", "text/plain", 404)
            elif path == "/camera.mjpg":
                self._mjpeg()
            elif path == "/events":
                self._sse()
            else:
                self._send(b"not found", "text/plain", 404)

        def _mjpeg(self):
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            last = None
            try:
                while True:
                    img = robot.jpeg
                    if img is not None and img is not last:
                        self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % len(img) + img + b"\r\n")
                        last = img
                    time.sleep(0.03)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _sse(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                while True:
                    with robot.changed:
                        robot.changed.wait(timeout=1.0)
                    self.wfile.write(b"data: " + json.dumps(robot.snapshot()).encode() + b"\n\n")
                    self.wfile.flush()
                    time.sleep(0.1)                 # <= 10 updates/s per browser
            except (BrokenPipeError, ConnectionResetError):
                pass

    return Handler


def serve(host, ids, hz, fps, listen, port, llm=None, qr=None):
    """llm: None, or dict(url, model, api_key, on, record) to run the agent in this process.
    qr: a link shown as a QR code in the page corner (e.g. where to follow the project)."""
    robot = Robot(host, ids, hz, fps)
    robot.state["qr"] = qr
    robot.start()
    agent = None
    if llm:
        from agent import Agent
        agent = Agent(robot, llm["url"], llm["model"], llm.get("api_key"), llm.get("record", True), llm.get("motion", True),
                      llm.get("lang", "en"), llm.get("think", "low"))
        agent.start()
        agent.switch(llm.get("on", False))
        if llm.get("whisper_model"):
            from voice import Voice
            Voice(robot, agent, llm["whisper_model"], llm.get("tts_voice")).start()
    httpd = ThreadingHTTPServer((listen, port), make_handler(robot, agent))
    httpd.daemon_threads = True
    urls = [f"http://{ip}:{port}/" for ip in (lan_ips() if listen == "0.0.0.0" else [listen])]
    print(json.dumps({"ok": True, "dashboard": urls, "robot": host}), flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
