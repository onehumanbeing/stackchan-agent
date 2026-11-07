"""Minimal streaming LLM client (stdlib only): OpenAI-compatible /chat/completions or Anthropic /v1/messages.

stream() calls on_think(text) for reasoning deltas and on_line(line) for every complete line of the
answer, so a caller can act on the first line while the model is still writing the rest.
Messages are always in the OpenAI shape (system message, image_url data URLs); the Anthropic path converts them.
The Anthropic path can also use tools: call_tool(name, input) -> text runs one, and the model goes on with its result.
"""
import json
import urllib.error
import urllib.request

NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # LAN / localhost endpoints
OPENER = urllib.request.build_opener()                                     # cloud APIs: honour the system proxy
THINK_BUDGET = 1024                                                        # Anthropic thinking tokens for think="high"
TOOL_ROUNDS = 4                                                            # model calls per turn when it uses tools
NO_THINK = {"type": "between_tools"}    # newer Claude models think by default (about 2 s more with an image); older ones
_think_field_rejected = set()           # reject this field, so it is dropped for them after the first 400


def stream(url, model, messages, on_think=None, on_line=None, max_tokens=600, timeout=60, api_key=None, think="low", api="openai",
           tools=None, call_tool=None):
    """think: "low" (default: short reasoning, a few times faster), "high" (the server's default), "off".
    api: "openai" or "anthropic" (Claude models skip reasoning unless think="high").
    tools (Anthropic only): tool definitions [{name, description, input_schema}], run with call_tool(name, input)."""
    lines = Lines(on_line)
    if api != "anthropic":
        req = _openai(url, model, messages, max_tokens, api_key, think)
        for event in _events(NO_PROXY.open(req, timeout=timeout)):
            reasoning, text = _openai_delta(event)
            if reasoning and on_think:
                on_think(reasoning)
            lines.add(text)
        return lines.end()
    chat = [{"role": m["role"], "content": _anthropic_content(m["content"])} for m in messages if m["role"] != "system"]
    system = "\n".join(m["content"] for m in messages if m["role"] == "system")
    for k in range(TOOL_ROUNDS):
        blocks, stop = _anthropic_round(url, model, system, chat, max_tokens, api_key, think, tools, timeout, on_think, lines,
                                        last=k == TOOL_ROUNDS - 1)
        lines.add("\n")                              # a line never runs on into the next call
        uses = [b for b in blocks if b["type"] == "tool_use"]
        if stop != "tool_use" or not uses or not call_tool:
            break
        results = [{"type": "tool_result", "tool_use_id": b["id"], "content": _tool_content(call_tool(b["name"], b["input"]))} for b in uses]
        chat += [{"role": "assistant", "content": blocks}, {"role": "user", "content": results}]
    return lines.end()


def _tool_content(out):
    """A tool's result: text, or a list of content blocks (e.g. an image)."""
    return out if isinstance(out, list) else str(out)


class Lines:
    """Answer text in, complete lines out (on_line), as soon as each one ends."""

    def __init__(self, on_line):
        self.on_line, self.buf, self.answer = on_line, "", ""

    def add(self, text):
        self.answer += text
        self.buf += text
        while "\n" in self.buf:
            done, self.buf = self.buf.split("\n", 1)
            if done.strip() and self.on_line:
                self.on_line(done.strip())

    def end(self):
        self.add("\n")
        return self.answer.strip()


def _events(response):
    for raw in response:
        line = raw.decode("utf-8", "replace").strip()
        if line.startswith("data:") and not line.endswith("[DONE]"):
            yield json.loads(line[5:])


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


def _anthropic_round(url, model, system, chat, max_tokens, api_key, think, tools, timeout, on_think, lines, last=False):
    """One /v1/messages call: text goes to lines as it streams; returns (content blocks, stop_reason)."""
    body = {"model": model, "system": system, "messages": chat, "stream": True, "max_tokens": max_tokens}
    if tools:
        body["tools"] = tools
        if last:
            body["tool_choice"] = {"type": "none"}     # the last call has to answer
    if think == "high":
        body["thinking"] = {"type": "enabled", "budget_tokens": THINK_BUDGET}
        body["max_tokens"] += THINK_BUDGET           # no temperature: newer Claude models reject it
    elif model not in _think_field_rejected:
        body["thinking"] = NO_THINK
    headers = {"Content-Type": "application/json", "anthropic-version": "2023-06-01", "x-api-key": api_key or "",
               "User-Agent": "stackchan-agent"}            # Cloudflare-fronted endpoints reject Python's default agent
    req = urllib.request.Request(url.rstrip("/") + "/v1/messages", json.dumps(body).encode(), headers)
    try:
        response = OPENER.open(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        if e.code == 400 and body.get("thinking") is NO_THINK and "thinking" in e.read().decode("utf-8", "replace"):
            _think_field_rejected.add(model)
            return _anthropic_round(url, model, system, chat, max_tokens, api_key, think, tools, timeout, on_think, lines, last)
        raise
    blocks, stop = [], None
    for event in _events(response):
        kind = event.get("type")
        if kind == "error" or "error" in event:     # Anthropic: {"type": "error", ...}; relays: {"error": "...", "details": ...}
            err = event.get("error")
            raise RuntimeError(err.get("message") if isinstance(err, dict) else f"{err}: {event.get('details', '')}")
        if kind == "content_block_start":
            blocks.append(dict(event["content_block"]))
        elif kind == "content_block_delta":
            b, d = blocks[-1], event["delta"]
            if d.get("type") == "text_delta":
                b["text"] = b.get("text", "") + d["text"]
                lines.add(d["text"])
            elif d.get("type") == "thinking_delta":
                b["thinking"] = b.get("thinking", "") + d["thinking"]
                if on_think:
                    on_think(d["thinking"])
            elif d.get("type") == "signature_delta":
                b["signature"] = b.get("signature", "") + d["signature"]
            elif d.get("type") == "input_json_delta":
                b["partial"] = b.get("partial", "") + d["partial_json"]
        elif kind == "content_block_stop" and blocks and blocks[-1]["type"] == "tool_use":
            blocks[-1]["input"] = json.loads(blocks[-1].pop("partial", "") or "{}")
        elif kind == "message_delta":
            stop = event.get("delta", {}).get("stop_reason") or stop
    return blocks, stop


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
