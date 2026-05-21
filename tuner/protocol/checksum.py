"""Checksum utilities for fixed-binary protocol."""

from typing import Optional


def sum_u8(data: bytes) -> int:
    """Compute sum-of-bytes modulo 256 (uint8).

    >>> sum_u8(b"\\x10\\x01\\x02")
    19
    """
    return sum(data) & 0xFF


def append_sum_u8(message_id_and_payload: bytes) -> bytes:
    """Append ``sum_u8(data)`` as a single byte to *data*.

    Returns a new ``bytes`` object; the input is not modified.
    """
    return message_id_and_payload + bytes([sum_u8(message_id_and_payload)])
