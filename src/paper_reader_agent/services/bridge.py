from __future__ import annotations

import json
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest

from paper_reader_agent.config import AppConfig


def resolve_bridge_config(config: AppConfig, payload: dict[str, Any]) -> dict[str, str]:
    return {
        "api_url": str(payload.get("bridge_url") or config.bridge_url).strip(),
        "model": str(payload.get("model") or config.model).strip(),
        "api_key": str(payload.get("api_key") or config.api_key).strip(),
        "reasoning_effort": normalize_reasoning_effort(payload.get("reasoning_effort") or config.reasoning_effort),
    }


def normalize_reasoning_effort(value: Any) -> str:
    effort = str(value or "").strip().lower()
    if effort in {"", "default"}:
        return ""
    if effort == "median":
        return "medium"
    return effort


def request_chat_completion(
    bridge: dict[str, str],
    *,
    messages: list[dict[str, str]],
    max_tokens: int,
    temperature: float,
) -> str:
    endpoint = _normalize_chat_url(bridge["api_url"])
    headers = {"Content-Type": "application/json"}
    if bridge["api_key"]:
        headers["Authorization"] = f"Bearer {bridge['api_key']}"

    request_body: dict[str, Any] = {
        "model": bridge["model"],
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if bridge.get("reasoning_effort"):
        request_body["reasoning_effort"] = bridge["reasoning_effort"]

    body = json.dumps(request_body).encode("utf-8")

    request_obj = urlrequest.Request(endpoint, data=body, headers=headers, method="POST")
    try:
        with urlrequest.urlopen(request_obj, timeout=240) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urlerror.HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{error.code} - {_extract_api_error(raw)}") from error
    except urlerror.URLError as error:
        raise RuntimeError("无法连接到本地 bridge。请确认 bridge 已启动。") from error

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise RuntimeError("模型返回了无效 JSON。") from error

    content = _extract_message_content(payload)
    if not content:
        raise RuntimeError("模型返回了空结果。")
    return content


def _normalize_chat_url(raw_url: str) -> str:
    url = raw_url.strip().rstrip("/")
    if url.endswith("/chat/completions"):
        return url
    if url.endswith("/v1"):
        return f"{url}/chat/completions"
    return f"{url}/v1/chat/completions"


def _extract_api_error(raw: str) -> str:
    try:
        payload = json.loads(raw)
        message = payload.get("error", {}).get("message") or payload.get("message")
        if message:
            return str(message)
    except Exception:
        pass
    return raw.strip()[:400] or "Unknown API error"


def _extract_message_content(payload: dict[str, Any]) -> str:
    content = payload.get("choices", [{}])[0].get("message", {}).get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and part.get("type") == "text":
                parts.append(str(part.get("text") or ""))
        return "\n".join(parts).strip()
    return ""
