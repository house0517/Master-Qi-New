"""Validate OpenAI-compatible responses before treating them as streamed text."""

import json
from urllib.parse import urlsplit, urlunsplit


class ResponseFormatError(RuntimeError):
    pass


def normalize_base_url(value):
    value = value.strip().rstrip("/")
    parts = urlsplit(value)
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise ValueError("Base URL格式不正确，请填写完整的http或https地址。")
    path = parts.path.rstrip("/")
    if path.endswith("/chat/completions"):
        path = path[:-len("/chat/completions")]
    needs_v1 = {"api.moshushi.xyz", "api.moonshot.cn", "api.moonshot.ai", "api.openai.com"}
    if not path and parts.hostname.lower() in needs_v1:
        path = "/v1"
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))


def content_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(
            item.get("text", "") for item in value
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        )
    return ""


def iter_chat_text(client, kwargs):
    """Yield visible content and finish reasons; never render hidden reasoning."""
    with client.chat.completions.with_streaming_response.create(**kwargs) as response:
        content_type = response.headers.get("content-type", "").lower()
        if "text/event-stream" in content_type:
            with response.parse() as stream:
                for chunk in stream:
                    for choice in chunk.choices[:1]:
                        yield content_text(getattr(choice.delta, "content", None)), choice.finish_reason
        elif "application/json" in content_type:
            try:
                body = json.loads(response.read())
            except (ValueError, UnicodeError):
                raise ResponseFormatError("接口返回的JSON无法解析，请核对接口服务。") from None
            if not isinstance(body, dict) or not body.get("choices"):
                raise ResponseFormatError("接口返回了JSON，但没有聊天正文choices；请核对模型与/chat/completions接口的兼容性。")
            choice = body["choices"][0]
            yield content_text(choice.get("message", {}).get("content")), choice.get("finish_reason")
        elif "text/html" in content_type:
            raise ResponseFormatError("接口返回了网页HTML，没有返回模型正文。请核对Base URL是否包含/v1；不要填写网站首页。")
        else:
            raise ResponseFormatError("接口返回的格式不是聊天文本流或JSON，请核对Base URL和模型接口类型。")


def is_kimi_k3_model(model):
    return str(model or "").strip().lower() == "kimi-k3"

def build_chat_completion_kwargs(model, messages, stream=False, max_tokens=None, temperature=None):
    """Build provider-compatible chat completion kwargs.

    Kimi K3 docs recommend fixed sampling params and use max_completion_tokens
    instead of max_tokens. Keep other OpenAI-compatible providers unchanged.
    """
    kwargs = {
        "model": model,
        "messages": messages,
        "stream": stream,
    }
    if is_kimi_k3_model(model):
        kwargs["reasoning_effort"] = "low"
        if max_tokens is not None:
            kwargs["max_completion_tokens"] = max(8192, max_tokens + 4096)
    else:
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
    return kwargs
