"""FixedBinaryCodec — manifest-driven encode/decode/parse for fixed-binary frames.

Frame layout
------------
::

    header | message_id | payload fields... | checksum | tail

Checksum (per shared contract):
    sum_u8(message_id + payload bytes) & 0xFF
    (does NOT include header, checksum byte, or tail)
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from tuner.protocol.checksum import sum_u8
from tuner.protocol.codec import encode_fields, decode_fields, payload_size
from tuner.protocol.hex_utils import parse_hex_string, bytes_to_hex


# ---------------------------------------------------------------------------
# FrameDecodeResult
# ---------------------------------------------------------------------------

@dataclass
class FrameDecodeResult:
    """Result of decoding a single frame from a byte stream."""

    raw: bytes
    hex: str
    ok: bool
    decoded: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# FixedBinaryCodec
# ---------------------------------------------------------------------------

class FixedBinaryCodec:
    """Codec driven by a ``protocol_manifest`` dict (or equivalent object).

    Parameters
    ----------
    manifest : dict
        Must contain keys ``tx_frame`` and ``rx_frame`` as described in the
        shared contract (00_shared_contracts.md).  At minimum each frame
        descriptor must have:
          - ``header`` (hex string without spaces, e.g. ``"AA"``)
          - ``tail`` (hex string)
          - ``message_id`` (hex string)
          - ``checksum`` (string, currently only ``"sum_u8"`` is supported)
          - ``endian`` (``"big"`` | ``"little"``)
          - ``payload`` (list of field dicts)
    """

    def __init__(self, manifest: dict) -> None:
        self._raw = copy.deepcopy(manifest)

        tx = manifest['tx_frame']
        rx = manifest['rx_frame']

        self._tx_header = parse_hex_string(tx['header'])
        self._tx_tail = parse_hex_string(tx['tail'])
        self._tx_message_id = parse_hex_string(tx['message_id'])
        self._tx_endian = tx.get('endian', 'big')
        self._tx_payload = tx['payload']

        self._rx_header = parse_hex_string(rx['header'])
        self._rx_tail = parse_hex_string(rx['tail'])
        self._rx_message_id = parse_hex_string(rx['message_id'])
        self._rx_endian = rx.get('endian', 'big')
        self._rx_payload = rx['payload']

        # Pre-computed lengths
        self._rx_payload_len = payload_size(self._rx_payload)
        self._tx_payload_len = payload_size(self._tx_payload)
        # frame = header(1) + message_id(1) + payload + checksum(1) + tail(1)
        self._rx_frame_len = len(self._rx_header) + len(self._rx_message_id) \
            + self._rx_payload_len + 1 + len(self._rx_tail)
        self._tx_frame_len = len(self._tx_header) + len(self._tx_message_id) \
            + self._tx_payload_len + 1 + len(self._tx_tail)

        # Internal buffer for feed()
        self._buffer = bytearray()

    # -- Properties ---------------------------------------------------------

    @property
    def rx_frame_length(self) -> int:
        return self._rx_frame_len

    @property
    def tx_frame_length(self) -> int:
        return self._tx_frame_len

    # -- Encode (TX) --------------------------------------------------------

    def encode_tx_frame(self, params: dict) -> tuple[bytes, str]:
        """Encode a TX frame from human-readable *params*.

        Returns ``(raw_bytes, hex_string)``.
        """
        payload = encode_fields(params, self._tx_payload, self._tx_endian)
        mid_and_payload = self._tx_message_id + payload
        ck = sum_u8(mid_and_payload)
        frame = self._tx_header + mid_and_payload + bytes([ck]) + self._tx_tail
        return frame, bytes_to_hex(frame)

    # -- Decode single frame (TX) -------------------------------------------

    def decode_tx_frame(self, frame: bytes) -> dict:
        """Decode a complete TX *frame* (including header, checksum, tail).

        Validates header, message_id, checksum, and tail.
        Raises ``ValueError`` on any mismatch.

        Returns decoded payload dict.
        """
        if len(frame) < self._tx_frame_len:
            raise ValueError(
                f"frame too short: {len(frame)} < {self._tx_frame_len}"
            )

        # Validate header
        hdr = frame[:len(self._tx_header)]
        if hdr != self._tx_header:
            raise ValueError(
                f"header mismatch: expected {bytes_to_hex(self._tx_header)}, "
                f"got {bytes_to_hex(hdr)}"
            )

        # Validate message_id
        off = len(self._tx_header)
        mid = frame[off:off + len(self._tx_message_id)]
        if mid != self._tx_message_id:
            raise ValueError(
                f"message_id mismatch: expected "
                f"{bytes_to_hex(self._tx_message_id)}, got {bytes_to_hex(mid)}"
            )

        # Extract payload
        off += len(self._tx_message_id)
        payload_bytes = frame[off:off + self._tx_payload_len]

        # Validate checksum
        off += self._tx_payload_len
        mid_and_payload = mid + payload_bytes
        expected_ck = sum_u8(mid_and_payload)
        actual_ck = frame[off]
        if actual_ck != expected_ck:
            raise ValueError(
                f"checksum mismatch: expected {expected_ck:#04x}, "
                f"got {actual_ck:#04x}"
            )

        # Validate tail
        off += 1
        tail = frame[off:off + len(self._tx_tail)]
        if tail != self._tx_tail:
            raise ValueError(
                f"tail mismatch: expected {bytes_to_hex(self._tx_tail)}, "
                f"got {bytes_to_hex(tail)}"
            )

        return decode_fields(payload_bytes, self._tx_payload, self._tx_endian)

    # -- Decode single frame (RX) -------------------------------------------

    def decode_rx_frame(self, frame: bytes) -> dict:
        """Decode a complete RX *frame* (including header, checksum, tail).

        Validates header, message_id, checksum, and tail.
        Raises ``ValueError`` on any mismatch.

        Returns decoded payload dict.
        """
        if len(frame) < self._rx_frame_len:
            raise ValueError(
                f"frame too short: {len(frame)} < {self._rx_frame_len}"
            )

        # Validate header
        hdr = frame[:len(self._rx_header)]
        if hdr != self._rx_header:
            raise ValueError(
                f"header mismatch: expected {bytes_to_hex(self._rx_header)}, "
                f"got {bytes_to_hex(hdr)}"
            )

        # Validate message_id
        off = len(self._rx_header)
        mid = frame[off:off + len(self._rx_message_id)]
        if mid != self._rx_message_id:
            raise ValueError(
                f"message_id mismatch: expected "
                f"{bytes_to_hex(self._rx_message_id)}, got {bytes_to_hex(mid)}"
            )

        # Extract payload
        off += len(self._rx_message_id)
        payload_bytes = frame[off:off + self._rx_payload_len]

        # Validate checksum
        off += self._rx_payload_len
        mid_and_payload = mid + payload_bytes
        expected_ck = sum_u8(mid_and_payload)
        actual_ck = frame[off]
        if actual_ck != expected_ck:
            raise ValueError(
                f"checksum mismatch: expected {expected_ck:#04x}, "
                f"got {actual_ck:#04x}"
            )

        # Validate tail
        off += 1
        tail = frame[off:off + len(self._rx_tail)]
        if tail != self._rx_tail:
            raise ValueError(
                f"tail mismatch: expected {bytes_to_hex(self._rx_tail)}, "
                f"got {bytes_to_hex(tail)}"
            )

        return decode_fields(payload_bytes, self._rx_payload, self._rx_endian)

    # -- Stream parser (feed) -----------------------------------------------

    def feed(self, data: bytes) -> list[FrameDecodeResult]:
        """Feed raw bytes into the internal stream parser.

        Returns a list of ``FrameDecodeResult`` — one per complete frame
        found.  Incomplete data is held in an internal buffer; call this
        method again with more data to continue.
        """
        self._buffer.extend(data)
        results: list[FrameDecodeResult] = []

        while True:
            result = self._try_extract_one()
            if result is None:
                break
            results.append(result)

        return results

    def _try_extract_one(self) -> Optional[FrameDecodeResult]:
        """Try to extract one frame from ``self._buffer``.

        Returns ``None`` if not enough data is available.
        """
        buf = self._buffer
        hdr_len = len(self._rx_header)

        # --- 1. Skip noise until we find header ---
        idx = _find_bytes(buf, self._rx_header)
        if idx < 0:
            self._buffer.clear()
            return None
        if idx > 0:
            # Discard noise bytes before header
            del buf[:idx]

        # --- 2. Check we have at least a full frame ---
        if len(buf) < self._rx_frame_len:
            return None  # wait for more data

        candidate = bytes(buf[:self._rx_frame_len])

        # --- 3. Validate ---
        result = self._validate_frame(candidate)

        # Consume the frame length (even on bad checksum/tail, we advance)
        del buf[:self._rx_frame_len]

        return result

    def _validate_frame(self, frame: bytes) -> FrameDecodeResult:
        """Validate and decode a complete frame.

        Returns a ``FrameDecodeResult``.  On checksum/tail error, the result
        has ``ok=False`` and ``error`` populated, but *never* raises.
        """
        try:
            decoded = self.decode_rx_frame(frame)
            return FrameDecodeResult(
                raw=frame,
                hex=bytes_to_hex(frame),
                ok=True,
                decoded=decoded,
            )
        except ValueError as exc:
            # Still try to extract what we can
            partial: Optional[Dict[str, Any]] = None
            try:
                off = len(self._rx_header) + len(self._rx_message_id)
                payload_bytes = frame[off:off + self._rx_payload_len]
                partial = decode_fields(
                    payload_bytes, self._rx_payload, self._rx_endian
                )
            except Exception:
                pass
            return FrameDecodeResult(
                raw=frame,
                hex=bytes_to_hex(frame),
                ok=False,
                decoded=partial,
                error=str(exc),
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_bytes(haystack: bytearray, needle: bytes) -> int:
    """Return index of first occurrence of *needle* in *haystack*, or -1."""
    if len(needle) == 0:
        return 0
    try:
        return haystack.index(needle)
    except ValueError:
        return -1
