"""Admin-safe view and validation for config.json MCP/LLM settings."""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse


ALLOWED_LLM_FIELDS = (
    "api_url",
    "model",
    "timeout",
    "max_retries",
    "temperature",
    "max_tokens",
    "api_key",
)


def redact_llm_config(llm: Dict[str, Any]) -> Dict[str, Any]:
    key = llm.get("api_key") or ""
    out = {k: v for k, v in llm.items() if k != "api_key"}
    out["api_key_set"] = bool(key)
    out["api_key"] = ""
    return out


def validate_mcp_config_update(payload: Dict[str, Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    mcp = payload.get("mcp_server")
    if mcp is not None:
        host = mcp.get("host", "localhost")
        port = mcp.get("port")
        try:
            port_i = int(port)
        except (TypeError, ValueError):
            raise ValueError("mcp_server.port must be an integer")
        if port_i < 1 or port_i > 65535:
            raise ValueError("mcp_server.port out of range")
        result["mcp_server"] = {"host": str(host), "port": port_i}
    llm = payload.get("llm")
    if llm is not None:
        cleaned = {}
        if "api_url" in llm:
            url = str(llm.get("api_url") or "")
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                raise ValueError("llm.api_url must start with http")
            cleaned["api_url"] = url
        for field in ALLOWED_LLM_FIELDS:
            if field == "api_url":
                continue
            if field in llm:
                cleaned[field] = llm[field]
        if "timeout" in cleaned:
            cleaned["timeout"] = int(cleaned["timeout"])
        if "max_retries" in cleaned:
            cleaned["max_retries"] = int(cleaned["max_retries"])
        if "max_tokens" in cleaned:
            cleaned["max_tokens"] = int(cleaned["max_tokens"])
        if "temperature" in cleaned:
            cleaned["temperature"] = float(cleaned["temperature"])
        result["llm"] = cleaned
    return result


def _slug(text: str, fallback: str = "item") -> str:
    raw = re.sub(r"[^a-zA-Z0-9_-]+", "-", (text or "").strip()).strip("-").lower()
    return raw or fallback


def _unique_id(existing: List[Dict[str, Any]], base: str) -> str:
    slug = _slug(base, "item")
    used = {str(p.get("id") or "") for p in existing}
    if slug not in used:
        return slug
    i = 2
    while f"{slug}-{i}" in used:
        i += 1
    return f"{slug}-{i}"


def ensure_profiles(cfg: Dict[str, Any]) -> Dict[str, Any]:
    cfg = copy.deepcopy(cfg)
    if not cfg.get("mcp_profiles"):
        ms = cfg.get("mcp_server") or {}
        cfg["mcp_profiles"] = [{
            "id": "default",
            "name": "本机 MCP",
            "host": ms.get("host") or "localhost",
            "port": int(ms.get("port") or 8001),
            "active": True,
        }]
    if not cfg.get("llm_profiles"):
        llm = cfg.get("llm") or {}
        cfg["llm_profiles"] = [{
            "id": "default",
            "name": llm.get("model") or "默认模型",
            "api_url": llm.get("api_url") or "",
            "model": llm.get("model") or "",
            "timeout": llm.get("timeout"),
            "max_retries": llm.get("max_retries"),
            "temperature": llm.get("temperature"),
            "max_tokens": llm.get("max_tokens"),
            "active": True,
        }]
    return cfg


def sync_active_into_root(cfg: Dict[str, Any]) -> None:
    for item in cfg.get("mcp_profiles") or []:
        if item.get("active"):
            cfg["mcp_server"] = {
                "host": item.get("host") or "localhost",
                "port": int(item.get("port") or 8001),
            }
            break
    for item in cfg.get("llm_profiles") or []:
        if item.get("active"):
            llm = cfg.setdefault("llm", {})
            for key in ("api_url", "model", "timeout", "max_retries", "temperature", "max_tokens"):
                if item.get(key) is not None:
                    llm[key] = item[key]
            if item.get("api_key"):
                llm["api_key"] = item["api_key"]
            break


def public_profile(kind: str, item: Dict[str, Any], root_llm: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    out = {k: v for k, v in item.items() if k != "api_key"}
    out["kind"] = kind
    if kind == "llm":
        if item.get("active") and root_llm is not None:
            out["api_key_set"] = bool(root_llm.get("api_key") or item.get("api_key"))
        else:
            out["api_key_set"] = bool(item.get("api_key"))
    return out


def list_public_profiles(cfg: Dict[str, Any]) -> Dict[str, Any]:
    cfg = ensure_profiles(cfg)
    llm = cfg.get("llm") or {}
    return {
        "mcp_profiles": [public_profile("mcp", p) for p in cfg["mcp_profiles"]],
        "llm_profiles": [public_profile("llm", p, llm) for p in cfg["llm_profiles"]],
    }


def _key(kind: str) -> str:
    if kind == "mcp":
        return "mcp_profiles"
    if kind == "llm":
        return "llm_profiles"
    raise ValueError("kind must be mcp or llm")


def find_profile(cfg: Dict[str, Any], kind: str, pid: str) -> Dict[str, Any]:
    cfg = ensure_profiles(cfg)
    for item in cfg[_key(kind)]:
        if item.get("id") == pid:
            return item
    raise FileNotFoundError(pid)


def _set_active(items: List[Dict[str, Any]], pid: str) -> None:
    found = False
    for item in items:
        on = item.get("id") == pid
        item["active"] = on
        if on:
            found = True
    if not found:
        raise FileNotFoundError(pid)


def create_profile(cfg: Dict[str, Any], payload: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    kind = payload.get("kind")
    cfg = ensure_profiles(cfg)
    items = cfg[_key(kind)]
    pid = _unique_id(items, payload.get("id") or payload.get("name") or kind)
    if kind == "mcp":
        host = str(payload.get("host") or "localhost")
        try:
            port = int(payload.get("port"))
        except (TypeError, ValueError):
            raise ValueError("port must be an integer")
        if port < 1 or port > 65535:
            raise ValueError("port out of range")
        item = {
            "id": pid,
            "name": payload.get("name") or pid,
            "host": host,
            "port": port,
            "active": False,
        }
    else:
        url = str(payload.get("api_url") or "")
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("api_url must start with http")
        item = {
            "id": pid,
            "name": payload.get("name") or payload.get("model") or pid,
            "api_url": url,
            "model": payload.get("model") or "",
            "timeout": int(payload["timeout"]) if payload.get("timeout") not in (None, "") else 600000,
            "max_retries": int(payload["max_retries"]) if payload.get("max_retries") not in (None, "") else 3,
            "temperature": float(payload["temperature"]) if payload.get("temperature") not in (None, "") else 0.0,
            "max_tokens": int(payload["max_tokens"]) if payload.get("max_tokens") not in (None, "") else 2048,
            "active": False,
        }
        if payload.get("api_key"):
            item["api_key"] = payload["api_key"]
    if payload.get("active"):
        for other in items:
            other["active"] = False
        item["active"] = True
    items.append(item)
    if item.get("active"):
        sync_active_into_root(cfg)
    return cfg, public_profile(kind, item, cfg.get("llm"))


def update_profile(cfg: Dict[str, Any], kind: str, pid: str, payload: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    cfg = ensure_profiles(cfg)
    items = cfg[_key(kind)]
    current = None
    for item in items:
        if item.get("id") == pid:
            current = item
            break
    if current is None:
        raise FileNotFoundError(pid)
    if kind == "mcp":
        if "name" in payload:
            current["name"] = payload["name"] or current["name"]
        if "host" in payload:
            current["host"] = str(payload.get("host") or "localhost")
        if "port" in payload and payload.get("port") not in (None, ""):
            port = int(payload["port"])
            if port < 1 or port > 65535:
                raise ValueError("port out of range")
            current["port"] = port
    else:
        if "name" in payload:
            current["name"] = payload["name"] or current["name"]
        if "api_url" in payload:
            url = str(payload.get("api_url") or "")
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                raise ValueError("api_url must start with http")
            current["api_url"] = url
        for field in ("model", "timeout", "max_retries", "temperature", "max_tokens"):
            if field in payload and payload.get(field) not in (None, ""):
                if field == "model":
                    current[field] = payload[field]
                elif field == "temperature":
                    current[field] = float(payload[field])
                else:
                    current[field] = int(payload[field])
        if payload.get("api_key"):
            current["api_key"] = payload["api_key"]
    if payload.get("active"):
        _set_active(items, pid)
    sync_active_into_root(cfg)
    return cfg, public_profile(kind, current, cfg.get("llm"))


def delete_profile(cfg: Dict[str, Any], kind: str, pid: str) -> Dict[str, Any]:
    cfg = ensure_profiles(cfg)
    items = cfg[_key(kind)]
    if len(items) <= 1:
        raise ValueError("至少保留一条配置")
    remaining = [p for p in items if p.get("id") != pid]
    if len(remaining) == len(items):
        raise FileNotFoundError(pid)
    was_active = any(p.get("id") == pid and p.get("active") for p in items)
    cfg[_key(kind)] = remaining
    if was_active and remaining:
        remaining[0]["active"] = True
    sync_active_into_root(cfg)
    return cfg
