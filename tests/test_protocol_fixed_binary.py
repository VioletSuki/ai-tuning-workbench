"""Tests for protocol layer: hex_utils, checksum, codec, FixedBinaryCodec."""

import struct
import pytest

from tuner.protocol.hex_utils import parse_hex_string, bytes_to_hex, is_hex_byte_token
from tuner.protocol.checksum import sum_u8, append_sum_u8
from tuner.protocol.codec import encode_fields, decode_fields, payload_size
from tuner.protocol.fixed_binary import FixedBinaryCodec, FrameDecodeResult


# ==============================================================
# hex_utils
# ==============================================================

class TestHexUtils:
    def test_parse_basic(self):
        assert parse_hex_string('AA 10 FF') == b'\xaa\x10\xff'

    def test_parse_with_0x_prefix(self):
        assert parse_hex_string('0xAA 0x10') == b'\xaa\x10'

    def test_parse_lowercase(self):
        assert parse_hex_string('aa bb') == b'\xaa\xbb'

    def test_parse_empty_raises(self):
        with pytest.raises(ValueError, match='empty'):
            parse_hex_string('')

    def test_parse_invalid_token_raises(self):
        with pytest.raises(ValueError, match='invalid hex'):
            parse_hex_string('AA XX FF')

    def test_bytes_to_hex(self):
        assert bytes_to_hex(b'\xaa\x10') == 'AA 10'
        assert bytes_to_hex(b'') == ''

    def test_is_hex_byte_token(self):
        assert is_hex_byte_token('AA') is True
        assert is_hex_byte_token('0xAA') is True
        assert is_hex_byte_token('XX') is False
        assert is_hex_byte_token('AAA') is False
        assert is_hex_byte_token('') is False


# ==============================================================
# checksum
# ==============================================================

class TestChecksum:
    def test_sum_u8_basic(self):
        assert sum_u8(b'\x10\x01\x02') == 19

    def test_sum_u8_wraparound(self):
        # 0xFF + 0x01 = 0x100 -> 0x00
        assert sum_u8(b'\xff\x01') == 0

    def test_sum_u8_empty(self):
        assert sum_u8(b'') == 0

    def test_append_sum_u8(self):
        result = append_sum_u8(b'\x10\x01\x02')
        assert result == b'\x10\x01\x02\x13'


# ==============================================================
# codec – encode_fields / decode_fields
# ==============================================================

TX_DEFS = [
    {'name': 'speed', 'type': 'uint16', 'wire_scale': 10},
    {'name': 'flag', 'type': 'uint8'},
    {'name': 'temp', 'type': 'int16', 'wire_scale': 100},
]


class TestCodec:
    def test_encode_big_endian_default(self):
        data = encode_fields({'speed': 800, 'flag': 1, 'temp': -50},
                             TX_DEFS, endian='big')
        # speed 800 -> wire 8000 = 0x1F40
        # flag 1 -> wire 1 = 0x01
        # temp -50 -> wire -5000 = 0xEC78 (int16)
        assert data == b'\x1F\x40\x01\xEC\x78'

    def test_encode_little_endian(self):
        data = encode_fields({'speed': 800, 'flag': 1, 'temp': -50},
                             TX_DEFS, endian='little')
        assert data == b'\x40\x1F\x01\x78\xEC'

    def test_decode_big_endian(self):
        data = b'\x1F\x40\x01\xEC\x78'
        decoded = decode_fields(data, TX_DEFS, endian='big')
        assert decoded['speed'] == 800.0
        assert decoded['flag'] == 1.0
        assert decoded['temp'] == -50.0

    def test_decode_little_endian(self):
        data = b'\x40\x1F\x01\x78\xEC'
        decoded = decode_fields(data, TX_DEFS, endian='little')
        assert decoded['speed'] == 800.0
        assert decoded['flag'] == 1.0
        assert decoded['temp'] == -50.0

    def test_roundtrip_float32(self):
        defs = [{'name': 'val', 'type': 'float32'}]
        encoded = encode_fields({'val': 3.14}, defs, endian='big')
        decoded = decode_fields(encoded, defs, endian='big')
        assert abs(decoded['val'] - 3.14) < 1e-6

    def test_uint8_range_check(self):
        defs = [{'name': 'x', 'type': 'uint8'}]
        with pytest.raises(ValueError, match='exceeds'):
            encode_fields({'x': 300}, defs)

    def test_missing_field_with_default(self):
        defs = [{'name': 'a', 'type': 'uint8', 'default': 42}]
        data = encode_fields({}, defs)
        assert data == b'\x2a'

    def test_missing_required_field_raises(self):
        defs = [{'name': 'a', 'type': 'uint8'}]
        with pytest.raises(ValueError, match='missing'):
            encode_fields({}, defs)

    def test_payload_size(self):
        defs = [
            {'name': 'a', 'type': 'uint8'},
            {'name': 'b', 'type': 'uint16'},
            {'name': 'c', 'type': 'float32'},
        ]
        assert payload_size(defs) == 7


# ==============================================================
# FixedBinaryCodec — full integration
# ==============================================================

TX_MANIFEST = {
    'header': 'AA',
    'tail': 'FF',
    'message_id': '10',
    'checksum': 'sum_u8',
    'endian': 'big',
    'payload': [
        {'name': 'speed', 'type': 'uint16', 'wire_scale': 10},
        {'name': 'flag', 'type': 'uint8'},
    ],
}

RX_MANIFEST = {
    'header': 'AB',
    'tail': 'FF',
    'message_id': '20',
    'checksum': 'sum_u8',
    'endian': 'big',
    'payload': [
        {'name': 'measured', 'type': 'uint16', 'wire_scale': 10},
        {'name': 'state', 'type': 'uint8'},
    ],
}

CODE = FixedBinaryCodec({'tx_frame': TX_MANIFEST, 'rx_frame': RX_MANIFEST})


class TestFixedBinaryCodec:
    def test_encode_tx_frame(self):
        raw, hex_str = CODE.encode_tx_frame({'speed': 800, 'flag': 1})
        # header(AA) + msg_id(10) + speed(0x1F40) + flag(01) + cksum + tail(FF)
        # mid+payload = 10 1F 40 01 -> sum = 0x10+0x1F+0x40+0x01 = 0x70
        assert raw[0] == 0xAA
        assert raw[-1] == 0xFF
        assert raw[-2] == 0x70  # checksum
        assert raw[1] == 0x10  # message_id
        assert raw[2:4] == b'\x1F\x40'  # speed
        assert raw[4] == 0x01  # flag
        assert hex_str == 'AA 10 1F 40 01 70 FF'

    def test_decode_rx_frame(self):
        # Build valid frame: AB 20 00 64(stop=10) 01 -> cksum = 0x20+0x00+0x64+0x01=0x85
        # measured=100/10=10.0 (wire_scale=10)
        frame = bytes.fromhex('AB 20 00 64 01 85 FF')
        decoded = CODE.decode_rx_frame(frame)
        assert decoded['measured'] == 10.0
        assert decoded['state'] == 1.0

    def test_decode_bad_checksum_raises(self):
        frame = bytes.fromhex('AB 20 00 64 01 00 FF')  # wrong cksum
        with pytest.raises(ValueError, match='checksum'):
            CODE.decode_rx_frame(frame)

    def test_decode_bad_header_raises(self):
        frame = bytes.fromhex('AC 20 00 64 01 85 FF')  # wrong header
        with pytest.raises(ValueError, match='header'):
            CODE.decode_rx_frame(frame)

    def test_decode_short_frame_raises(self):
        with pytest.raises(ValueError, match='too short'):
            CODE.decode_rx_frame(b'\xAB\x20')

    # -- feed stream parser ------------------------------------------------

    def test_feed_one_frame(self):
        code = _fresh_codec()
        data = bytes.fromhex('AB 20 00 64 01 85 FF')
        results = code.feed(data)
        assert len(results) == 1
        assert results[0].ok is True
        assert results[0].decoded['measured'] == 10.0  # 100/10

    def test_feed_partial_returns_empty(self):
        code = _fresh_codec()
        data = bytes.fromhex('AB 20 00')  # incomplete
        results = code.feed(data)
        assert len(results) == 0

    def test_feed_partial_then_complete(self):
        code = _fresh_codec()
        r1 = code.feed(bytes.fromhex('AB 20 00 64'))
        assert len(r1) == 0  # partial
        r2 = code.feed(bytes.fromhex('01 85 FF'))
        assert len(r2) == 1
        assert r2[0].ok is True
        assert r2[0].decoded['measured'] == 10.0  # 100/10

    def test_feed_sticky_two_frames(self):
        code = _fresh_codec()
        frame = bytes.fromhex('AB 20 00 64 01 85 FF')
        data = frame + frame  # two in a row
        results = code.feed(data)
        assert len(results) == 2
        assert all(r.ok for r in results)

    def test_feed_noise_before_header(self):
        code = _fresh_codec()
        data = b'\x00\x01\xAA\xBB' + bytes.fromhex('AB 20 00 64 01 85 FF')
        results = code.feed(data)
        assert len(results) == 1
        assert results[0].ok is True

    def test_feed_bad_checksum_does_not_crash(self):
        code = _fresh_codec()
        data = bytes.fromhex('AB 20 00 64 01 00 FF')  # bad cksum
        results = code.feed(data)
        assert len(results) == 1
        assert results[0].ok is False
        assert 'checksum' in (results[0].error or '')

    def test_feed_noise_between_frames(self):
        code = _fresh_codec()
        f1 = bytes.fromhex('AB 20 00 64 01 85 FF')
        noise = b'\xDE\xAD'
        # frame2: measured=50/10=5.0 -> wire=50=0x0032, state=0
        # checksum = sum_u8(0x20+0x00+0x32+0x00) = 0x52
        f2 = bytes.fromhex('AB 20 00 32 00 52 FF')
        results = code.feed(f1 + noise + f2)
        assert len(results) == 2
        assert results[0].ok is True
        assert results[0].decoded['measured'] == 10.0  # 100/10
        assert results[1].ok is True
        assert results[1].decoded['measured'] == 5.0  # 50/10

    def test_rx_frame_length_property(self):
        assert CODE.rx_frame_length == 7  # hdr1+mid1+pyl2+ck1+tail1

    def test_tx_frame_length_property(self):
        assert CODE.tx_frame_length == 7


# ==============================================================
# Helpers
# ==============================================================

def _fresh_codec() -> FixedBinaryCodec:
    return FixedBinaryCodec({'tx_frame': TX_MANIFEST, 'rx_frame': RX_MANIFEST})
