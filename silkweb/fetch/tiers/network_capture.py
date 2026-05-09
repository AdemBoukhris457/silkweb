from __future__ import annotations

import json
from typing import Any

_SENSITIVE_HEADER_KEYS = {
    "authorization",
    "proxy-authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "x-auth-token",
}


def redact_headers(headers: dict[str, Any] | None) -> dict[str, str]:
    """
    Redact sensitive headers for safe logging/debugging.
    """
    if not headers:
        return {}
    out: dict[str, str] = {}
    for k, v in headers.items():
        key = str(k).strip()
        low = key.lower()
        if low in _SENSITIVE_HEADER_KEYS:
            out[key] = "<redacted>"
        else:
            out[key] = str(v)
    return out


def capture_body_json(
    body_text: str | None,
    *,
    content_type: str | None,
    max_bytes: int,
) -> dict[str, Any] | None:
    """
    Best-effort JSON-only body capture with size cap.

    Returns a small dict with either:
    - {"json": <parsed json>} or
    - {"truncated": true, "size": N} or
    - None (not JSON / empty / parse failed)
    """
    if not body_text:
        return None
    ct = (content_type or "").lower()
    if "application/json" not in ct and "+json" not in ct:
        return None
    raw = body_text.encode("utf-8", errors="ignore")
    if max_bytes > 0 and len(raw) > max_bytes:
        return {"truncated": True, "size": len(raw)}
    try:
        return {"json": json.loads(body_text)}
    except Exception:
        return None
