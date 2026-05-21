"""Field-level encoding/decoding for fixed-binary payload fields.

Supported types: uint8, int8, uint16, int16, uint32, int32, float32.
Endianness: big / little.
"""

import struct
from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Type -> struct format char mapping
# ---------------------------------------------------------------------------
_STRUCT_MAP: Dict[str, str] = {
    'uint8': 'B',
    'int8': 'b',
    'uint16': 'H',
    'int16': 'h',
    'uint32': 'I',
    'int32': 'i',
    'float32': 'f',
}

_TYPE_SIZES: Dict[str, int] = {
    'uint8': 1,
    'int8': 1,
    'uint16': 2,
    'int16': 2,
    'uint32': 4,
    'int32': 4,
    'float32': 4,
}

_MAX_VALUES = {
    'uint8': 0xFF,
    'int8': 0x7F,
    'uint16': 0xFFFF,
    'int16': 0x7FFF,
    'uint32': 0xFFFFFFFF,
    'int32': 0x7FFFFFFF,
}

_MIN_VALUES = {
    'uint8': 0,
    'int8': -128,
    'uint16': 0,
    'int16': -32768,
    'uint32': 0,
    'int32': -2147483648,
}


def payload_size(payload_defs: List[dict]) -> int:
    """Return total byte size of a payload declared via *payload_defs*."""
    return sum(_TYPE_SIZES[d['type']] for d in payload_defs)


def _endian_prefix(endian: str) -> str:
    if endian == 'little':
        return '<'
    return '>'  # big is default


def encode_fields(
    params: Dict[str, Any],
    payload_defs: List[dict],
    endian: str = 'big',
) -> bytes:
    """Encode a dictionary of human values into payload bytes.

    Each definition in *payload_defs* must at least have ``name`` and ``type``.
    ``wire_scale`` (default 1) is applied as:
        wire_value = round(human_value * wire_scale)
    """
    prefix = _endian_prefix(endian)
    result = bytearray()

    for field in payload_defs:
        name = field['name']
        typ = field['type']
        scale = float(field.get('wire_scale', 1))

        if name not in params:
            if 'default' in field:
                value = float(field['default'])
            else:
                raise ValueError(
                    f"missing required field {name!r} in params {params}"
                )
        else:
            value = float(params[name])

        if typ == 'float32':
            result.extend(struct.pack(prefix + 'f', value * scale))
        else:
            wire_value = _scale_encode(value, scale, typ, name)
            result.extend(struct.pack(prefix + _STRUCT_MAP[typ], wire_value))

    return bytes(result)


def decode_fields(
    data: bytes,
    payload_defs: List[dict],
    endian: str = 'big',
) -> Dict[str, Any]:
    """Decode payload bytes into a dictionary of human values.

    Returns dict mapping field name -> decoded value (``float`` for scaled
    integer fields, ``float`` for ``float32``).
    """
    prefix = _endian_prefix(endian)
    offset = 0
    result: Dict[str, Any] = {}

    for field in payload_defs:
        name = field['name']
        typ = field['type']
        scale = float(field.get('wire_scale', 1))
        size = _TYPE_SIZES[typ]
        fmt = prefix + _STRUCT_MAP[typ]

        chunk = data[offset:offset + size]
        if len(chunk) < size:
            raise ValueError(
                f"short read for field {name!r}: need {size} bytes, got {len(chunk)}"
            )

        wire_value = struct.unpack(fmt, chunk)[0]
        result[name] = _scale_decode(wire_value, scale, typ)
        offset += size

    return result


def _scale_encode(
    value: float, scale: float, typ: str, name: str,
) -> int:
    """Convert human value -> scaled integer with range clamp."""
    wire = round(value * scale)

    max_val = _MAX_VALUES.get(typ)
    min_val = _MIN_VALUES.get(typ)
    if max_val is not None and wire > max_val:
        raise ValueError(
            f"field {name!r} wire value {wire} exceeds {typ} max {max_val}"
        )
    if min_val is not None and wire < min_val:
        raise ValueError(
            f"field {name!r} wire value {wire} below {typ} min {min_val}"
        )
    return wire


def _scale_decode(wire_value: int, scale: float, typ: str) -> float:
    """Convert wire integer -> human float."""
    if typ == 'float32':
        return float(wire_value)
    if scale == 0:
        return float(wire_value)
    return wire_value / scale
