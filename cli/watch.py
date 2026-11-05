"""watch: react when what the camera sees changes (e.g. something in front of the robot is taken away).

Compares each camera frame with a reference frame (small grayscale, mean absolute difference).  When the
scene stays changed for a few frames: surprised face, then the gesture with a happy face, then the new
scene becomes the reference.  Prints one JSON line per event.
"""
import base64
import io
import json
import time

from PIL import Image, ImageChops, ImageStat

from gestures import play


def frame(link):
    jpeg = base64.b64decode(link.request("camera.snap", timeout=5)["jpeg"])
    return Image.open(io.BytesIO(jpeg)).convert("L").resize((80, 60))


def diff(a, b):
    return ImageStat.Stat(ImageChops.difference(a, b)).mean[0]


def emit(**ev):
    print(json.dumps({"t": round(time.time(), 2), **ev}), flush=True)


def settle(link, frames=3, warmup=1.5):
    """Reference frame once the scene is still (auto exposure settles first); returns (reference, noise)."""
    end = time.time() + warmup
    while time.time() < end:
        frame(link)
    prev, noise = frame(link), []
    for _ in range(frames):
        time.sleep(0.15)
        cur = frame(link)
        noise.append(diff(prev, cur))
        prev = cur
    return prev, max(noise)


def watch(link, gesture="wave", threshold=None, times=0):
    ref, noise = settle(link)
    limit = threshold or max(12.0, noise * 4)
    link.request("face.set", expression="neutral", say="watching", ms=1500)
    emit(ev="watching", threshold=round(limit, 1), noise=round(noise, 1))
    hits = reacted = 0
    while not times or reacted < times:
        d = diff(ref, frame(link))
        hits = hits + 1 if d > limit else 0
        if hits < 2:
            continue
        emit(ev="changed", diff=round(d, 1))
        link.request("face.set", expression="surprised")
        time.sleep(0.4)
        link.request("face.set", expression="happy", say="hi!", ms=2000)
        emit(ev="gesture", **play(link, gesture))
        link.request("face.set", expression="neutral")
        ref, noise = settle(link)
        limit = threshold or max(12.0, noise * 4)
        hits, reacted = 0, reacted + 1
        emit(ev="watching", threshold=round(limit, 1), noise=round(noise, 1))
