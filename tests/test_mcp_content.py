import pytest

from forgelab.mcp.content import decode_content, encode_bytes


def test_text_round_trips_as_utf8():
    enc = encode_bytes(b"(kicad_pcb (version 20211014))")
    assert enc["encoding"] == "utf-8"
    assert enc["content"] == "(kicad_pcb (version 20211014))"
    assert decode_content(enc["content"], enc["encoding"]) == b"(kicad_pcb (version 20211014))"


def test_binary_round_trips_as_base64():
    raw = bytes([0x50, 0x4B, 0x03, 0x04, 0x80, 0xFF, 0x00])  # zip header + non-utf8
    enc = encode_bytes(raw)
    assert enc["encoding"] == "base64"
    assert decode_content(enc["content"], enc["encoding"]) == raw


def test_decode_rejects_unknown_encoding():
    with pytest.raises(ValueError, match="unsupported encoding"):
        decode_content("x", "rot13")
