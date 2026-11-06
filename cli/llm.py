"""Minimal streaming LLM client (stdlib only): OpenAI-compatible /chat/completions or Anthropic /v1/messages.

stream() calls on_think(text) for reasoning deltas and on_line(line) for every complete line of the
answer, so a caller can act on the first line while the model is still writing the rest.
Messages are always in the OpenAI shape (system message, image_url data URLs); the Anthropic path converts them.
"""
import json
import urllib.request

NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # LAN / localhost endpoints
OPENER = urllib.request.build_opener()                                     # cloud APIs: honour the system proxy
THINK_BUDGET = 1024                                                        # Anthropic thinking tokens for think="high"


def stream(url, model, messages, on_think=None, on_line=None, max_tokens=600, timeout=60, api_key=None, think="low", api="openai"):
    """think: "low" (default: short reasoning, a few times faster), "high" (the server's default), "off".
    api: "openai" or "anthropic" (Claude models skip reasoning unless think="high")."""
    if api == "anthropic":
        req, opener, parse = _anthropic(url, model, messages, max_tokens, api_key, think), OPENER, _anthropic_delta
    else:
        req, opener, parse = _openai(url, model, messages, max_tokens, api_key, think), NO_PROXY, _openai_delta
    buf, answer = "", ""
    for raw in opener.open(req, timeout=timeout):
        line = raw.decode("utf-8", "replace").strip()
        if not line.startswith("data:") or line.endswith("[DONE]"):
            continue
        reasoning, text = parse(json.loads(line[5:]))
        if reasoning and on_think:
            on_think(reasoning)
        answer += text
        buf += text
        while "\n" in buf:
            done, buf = buf.split("\n", 1)
            if done.strip() and on_line:
                on_line(done.strip())
    if buf.strip() and on_line:
        on_line(buf.strip())
    return answer


def _openai(url, model, messages, max_tokens, api_key, think):
    body = {"model": model, "messages": messages, "stream": True, "max_tokens": max_tokens, "temperature": 0.4}
    if think == "off":
        body["chat_template_kwargs"] = {"enable_thinking": False}
    elif think == "low":
        body["reasoning_effort"] = "low"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return urllib.request.Request(url.rstrip("/") + "/chat/completions", json.dumps(body).encode(), headers)


def _openai_delta(event):
    delta = (event.get("choices") or [{}])[0].get("delta", {})
    return delta.get("reasoning_content") or delta.get("reasoning"), delta.get("content") or ""


def _anthropic(url, model, messages, max_tokens, api_key, think):
    system = "\n".join(m["content"] for m in messages if m["role"] == "system")
    chat = [{"role": m["role"], "content": _anthropic_content(m["content"])} for m in messages if m["role"] != "system"]
    body = {"model": model, "system": system, "messages": chat, "stream": True, "max_tokens": max_tokens}
    if think == "high":
        body["thinking"] = {"type": "enabled", "budget_tokens": THINK_BUDGET}
        body["max_tokens"] += THINK_BUDGET           # no temperature: newer Claude models reject it
    headers = {"Content-Type": "application/json", "anthropic-version": "2023-06-01", "x-api-key": api_key or "",
               "User-Agent": "stackchan-agent"}            # Cloudflare-fronted endpoints reject Python's default agent
    return urllib.request.Request(url.rstrip("/") + "/v1/messages", json.dumps(body).encode(), headers)


def _anthropic_content(content):
    if isinstance(content, str):
        return content
    parts = []
    for p in content:
        if p["type"] == "image_url":                 # data:image/jpeg;base64,....
            head, data = p["image_url"]["url"].split(",", 1)
            parts.append({"type": "image", "source": {"type": "base64", "media_type": head[5:].split(";")[0], "data": data}})
        else:
            parts.append(p)
    return parts


def _anthropic_delta(event):
    if event.get("type") == "error" or "error" in event:     # Anthropic: {"type": "error", ...}; relays: {"error": "...", "details": ...}
        err = event.get("error")
        raise RuntimeError(err.get("message") if isinstance(err, dict) else f"{err}: {event.get('details', '')}")
    delta = event.get("delta", {}) if event.get("type") == "content_block_delta" else {}
    return delta.get("thinking"), delta.get("text") or ""
