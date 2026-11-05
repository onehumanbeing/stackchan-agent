"""Minimal streaming client for any OpenAI-compatible /v1/chat/completions endpoint (stdlib only).

stream() calls on_think(text) for reasoning deltas and on_line(line) for every complete line of the
answer, so a caller can act on the first line while the model is still writing the rest.
"""
import json
import urllib.request

NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # LAN / localhost endpoints


def stream(url, model, messages, on_think=None, on_line=None, max_tokens=600, timeout=60, api_key=None):
    body = {"model": model, "messages": messages, "stream": True, "max_tokens": max_tokens, "temperature": 0.4}
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url.rstrip("/") + "/chat/completions", json.dumps(body).encode(), headers)
    buf, answer = "", ""
    for raw in NO_PROXY.open(req, timeout=timeout):
        line = raw.decode("utf-8", "replace").strip()
        if not line.startswith("data:") or line.endswith("[DONE]"):
            continue
        choices = json.loads(line[5:]).get("choices") or [{}]
        delta = choices[0].get("delta", {})
        think = delta.get("reasoning_content") or delta.get("reasoning")
        if think and on_think:
            on_think(think)
        text = delta.get("content") or ""
        answer += text
        buf += text
        while "\n" in buf:
            done, buf = buf.split("\n", 1)
            if done.strip() and on_line:
                on_line(done.strip())
    if buf.strip() and on_line:
        on_line(buf.strip())
    return answer
