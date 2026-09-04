"""Minimal Chat Completions client using config.json LLM settings."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional


def complete_chat(system: str, user: str, extra_messages: Optional[List[Dict[str, Any]]] = None) -> str:
    from http_api_extra import load_full_config

    llm = (load_full_config().get("llm") or {})
    api_url = llm.get("api_url") or ""
    api_key = llm.get("api_key") or ""
    if not api_url or not api_key:
        raise RuntimeError("LLM 未配置")
    messages = [{"role": "system", "content": system}]
    for msg in extra_messages or []:
        role = msg.get("role")
        content = msg.get("content")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": str(content)[:4000]})
    messages.append({"role": "user", "content": user})
    payload = {
        "model": llm.get("model") or "deepseek-chat",
        "messages": messages,
        "temperature": float(llm.get("temperature") or 0.2),
        "max_tokens": int(llm.get("max_tokens") or 4096),
        "stream": False,
    }
    req = urllib.request.Request(
        api_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    timeout = max(30, int((llm.get("timeout") or 600000) / 1000))
    with urllib.request.urlopen(req, timeout=min(timeout, 180)) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("LLM 无返回")
    return ((choices[0].get("message") or {}).get("content") or "").strip()
