"""Hex string parsing and formatting utilities."""

import re

_HEX_BYTE_RE = re.compile(r'^(?:0x)?([0-9a-fA-F]{2})$')


def is_hex_byte_token(token: str) -> bool:
    """Return True if *token* is a valid hex byte (with or without 0x prefix)."""
    return _HEX_BYTE_RE.match(token.strip()) is not None


def parse_hex_string(text: str) -> bytes:
    """Parse a hex string into bytes.

    Supports space-separated tokens, ``0x`` prefix, upper/lower case.
    Raises ``ValueError`` on the first invalid token.
    """
    if not text or not text.strip():
        raise ValueError("empty hex string")

    result = bytearray()
    for i, token in enumerate(text.strip().split()):
        stripped = token.strip()
        m = _HEX_BYTE_RE.match(stripped)
        if not m:
            raise ValueError(
                f"invalid hex byte token #{i}: {token!r}"
            )
        result.append(int(m.group(1), 16))
    return bytes(result)


def bytes_to_hex(data: bytes) -> str:
    """Convert bytes to space-separated uppercase hex string.

    >>> bytes_to_hex(b"\\xaa\\x10")
    "AA 10"
    """
    return ' '.join(f'{b:02X}' for b in data)
