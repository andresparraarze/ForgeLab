"""Encode/decode native file bytes for MCP transport (text or base64)."""

from __future__ import annotations

import base64
import binascii


def encode_bytes(data: bytes) -> dict[str, str]:
    """Encode bytes as UTF-8 text when possible, else base64.

    Returns ``{"encoding": "utf-8"|"base64", "content": <str>}``.
    """
    try:
        return {"encoding": "utf-8", "content": data.decode("utf-8")}
    except UnicodeDecodeError:
        return {"encoding": "base64", "content": base64.b64encode(data).decode("ascii")}


def decode_content(content: str, encoding: str) -> bytes:
    """Inverse of :func:`encode_bytes`."""
    if encoding == "utf-8":
        return content.encode("utf-8")
    if encoding == "base64":
        try:
            return base64.b64decode(content, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError(f"invalid base64 content: {exc}") from exc
    raise ValueError(f"unsupported encoding: {encoding!r} (expected 'utf-8' or 'base64')")
