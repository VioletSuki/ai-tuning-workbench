"""Mock backend — generates protocol-conformant RX frames without hardware.

The mock backend reads the protocol manifest's ``rx_frame`` definition to
dynamically construct telemetry frame bytes.  If a ``mock_config`` dict with
``response_model`` / ``tx_to_rx_map`` is provided (from the example-level
``project_manifest.yaml``), it simulates first-order-lag responses; otherwise
all numeric RX fields get a slowly-varying sine wave.
"""

from __future__ import annotations

import logging
import math
import struct
import time
from typing import Any

from tuner.backends.base import Backend

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# struct format lookup
# ---------------------------------------------------------------------------

_FMT = {
    "uint8": "B",
    "int8": "b",
    "uint16": "H",
    "int16": "h",
    "uint32": "I",
    "int32": "i",
    "float32": "f",
}

_SIZEOF = {name: struct.calcsize(fmt) for name, fmt in _FMT.items()}


def _default_min_max(typ: str) -> tuple[float, float]:
    """Return a plausible (min, max) for a numeric type."""
    ranges: dict[str, tuple[float, float]] = {
        "uint8": (0, 255),
        "int8": (-128, 127),
        "uint16": (0, 65535),
        "int16": (-32768, 32767),
        "uint32": (0, 4294967295),
        "int32": (-2147483648, 2147483647),
        "float32": (-1e6, 1e6),
    }
    return ranges.get(typ, (0.0, 1.0))


# ---------------------------------------------------------------------------
# helpers for frame building
# ---------------------------------------------------------------------------


def _sum_u8(data: bytes) -> int:
    """sum_u8 checksum used by the fixed-binary protocol."""
    return sum(data) & 0xFF


def _parse_hex_token(token: str) -> int:
    """Parse a hex string like ``\"AB\"`` into an integer byte."""
    return int(token, 16)


# ---------------------------------------------------------------------------
# MockBackend
# ---------------------------------------------------------------------------


class MockBackend(Backend):
    """Backend that simulates a device generating protocol-conformant frames.

    Parameters
    ----------
    protocol_manifest : dict
        The protocol manifest dict.  Must contain an ``rx_frame`` key with
        ``header``, ``message_id``, ``tail``, ``checksum``, ``payload``, etc.
    codec : optional
        A ``FixedBinaryCodec`` instance used to decode TX frames on write.
    mock_config : dict, optional
        Mock-specific configuration:

        - ``sample_interval_s``: seconds between frames (default 0.05)
        - ``tx_to_rx_map``: ``{tx_param_name: rx_field_name}``
        - ``response_model``: dict with keys ``target``, ``measured``,
          ``output``, ``motion_flag`` that name RX fields
        - ``seed_values``: optional ``{field_name: initial_value}`` overrides
    """

    def __init__(
        self,
        protocol_manifest: dict,
        codec: Any = None,
        mock_config: dict | None = None,
    ) -> None:
        self._manifest = protocol_manifest
        self._codec = codec
        self._cfg = mock_config or {}

        # rx frame layout
        rx: dict = self._manifest.get("rx_frame", {})
        self._rx_header = _parse_hex_token(rx.get("header", "AB"))
        self._rx_message_id = _parse_hex_token(rx.get("message_id", "20"))
        self._rx_tail = _parse_hex_token(rx.get("tail", "FF"))
        self._rx_endian: str = rx.get("endian", "big")
        self._rx_payload: list[dict] = rx.get("payload", [])

        self._endian_prefix = "<" if self._rx_endian == "little" else ">"

        # internal state
        self._opened = False
        self._mock_time: float = 0.0
        self._last_real_time: float = 0.0
        self._sample_interval: float = self._cfg.get("sample_interval_s", 0.05)
        self._buf = bytearray()

        # tx->rx param mapping
        self._tx_to_rx: dict[str, str] = self._cfg.get("tx_to_rx_map", {})
        # response model
        self._resp: dict[str, str] = self._cfg.get("response_model", {})

        # current tx-side parameter values (updated by write())
        self._tx_params: dict[str, float] = {}

        # rx field state (current value for each field)
        self._rx_values: dict[str, float] = {}
        self._rx_phases: dict[str, float] = {}
        seed = self._cfg.get("seed_values", {})
        for f in self._rx_payload:
            name = f["name"]
            if name in seed:
                self._rx_values[name] = seed[name]
            elif f.get("default") is not None:
                self._rx_values[name] = float(f["default"])
            else:
                lo, hi = _default_min_max(f.get("type", "float32"))
                self._rx_values[name] = (lo + hi) / 2.0
            self._rx_phases[name] = math.pi * 2 * (hash(name) % 1000) / 1000.0  # deterministic offset [0, 2π)

        # track frames generated so we can add variation
        self._frame_count = 0

        # PID controller state
        self._pid_integral = 0.0
        self._prev_measured = 0.0

        # Second-order plant state:  G(s) = ωₙ² / (s² + 2ζωₙ·s + ωₙ²)
        self._plant_x1 = 0.0  # output (= measured_speed)
        self._plant_x2 = 0.0  # internal velocity
        self._plant_omega_n = 6.0   # natural frequency (rad/s)
        self._plant_zeta = 0.35     # damping ratio (underdamped → overshoot)
        self._max_output = 1000.0   # PWM saturation ceiling

    # -- Backend interface -------------------------------------------------

    def open(self) -> None:
        self._opened = True
        self._last_real_time = time.monotonic()
        self._buf.clear()
        logger.info("MockBackend opened (sample_interval=%.3f s)", self._sample_interval)

    def close(self) -> None:
        self._opened = False
        self._buf.clear()
        logger.info("MockBackend closed")

    @property
    def is_open(self) -> bool:
        return self._opened

    def write(self, data: bytes) -> None:
        """Write TX frame bytes to the mock.

        Attempts to decode *data* using the FixedBinaryCodec; on success the
        extracted TX parameters update the mock's internal state and influence
        subsequent RX frame values via the response model.
        """
        if not self._opened:
            raise RuntimeError("MockBackend is not open")

        if not data:
            return

        decoded: dict = {}
        if self._codec is not None:
            try:
                decoded = self._codec.decode_tx_frame(data)
            except Exception as exc:
                logger.debug("MockBackend TX decode failed: %s", exc)
        if not decoded:
            logger.debug(
                "MockBackend received %d bytes (not decoded)", len(data)
            )

        # store tx params and apply response model
        for tx_name, value in decoded.items():
            self._tx_params[tx_name] = value

        self._apply_response_model()

    def read_available(self) -> bytes:
        """Return accumulated RX frame bytes generated since last call."""
        if not self._opened:
            return b""

        now = time.monotonic()
        elapsed = now - self._last_real_time
        self._last_real_time = now
        self._mock_time += elapsed

        frames_to_generate = int(elapsed / self._sample_interval) + 1
        for _ in range(frames_to_generate):
            self._step_simulation()
            self._buf.extend(self._build_frame())
            self._frame_count += 1
            self._mock_time += self._sample_interval

        result = bytes(self._buf)
        self._buf.clear()
        return result

    # -- internal simulation -----------------------------------------------

    def _step_simulation(self) -> None:
        """Advance one tick of the mock simulation state."""
        # If we have a response_model, the _rx_values are driven by
        # _apply_response_model() during write().  But between write calls
        # the "measured" field should drift towards target.
        self._apply_pid_plant_step()

        # Fields that are NOT assigned a response-model role get a sine wave
        # so they produce plausible fluctuating telemetry (requirement 4.3-4).
        # Timestamp fields are excluded — they get real mock time instead.
        resp_field_names = set(self._resp.values())
        time_field_names = {"time_ms"}
        for field in self._rx_payload:
            name = field["name"]
            if name in resp_field_names or name in time_field_names:
                continue  # response-model fields handled above; time fields below
            typ = field.get("type", "float32")
            if typ not in _FMT:
                continue
            lo, hi = _default_min_max(typ)
            amp = (hi - lo) * 0.4
            phase = self._mock_time * 0.5 + self._rx_phases.get(name, 0)
            # Oscillate around the initial value so defaults are reflected.
            # Clamp amplitude to stay within the type range.
            center = self._rx_values.get(name, (lo + hi) / 2.0)
            max_down = center - lo
            max_up = hi - center
            safe_amp = max(min(amp, max_down, max_up), 1.0)
            self._rx_values[name] = center + safe_amp * math.sin(phase)

        # Set timestamp fields from mock wall-clock time
        self._rx_values["time_ms"] = (self._mock_time * 1000.0) % (2**32)

    def _apply_response_model(self) -> None:
        """Apply TX params to RX fields according to the response model."""
        target_key = self._resp.get("target")
        measured_key = self._resp.get("measured")
        output_key = self._resp.get("output")
        motion_flag_key = self._resp.get("motion_flag")

        # resolve which TX param maps to which response field
        def _resolve_tx(response_field: str) -> float | None:
            if response_field is None:
                return None
            # find the TX param that maps to this response field
            for tx_name, rx_name in self._tx_to_rx.items():
                if rx_name == response_field:
                    return self._tx_params.get(tx_name)
            return None

        target_val = _resolve_tx(target_key) if target_key else None
        motion_val = _resolve_tx(motion_flag_key) if motion_flag_key else None

        if target_val is not None and target_key:
            self._rx_values[target_key] = target_val

        # pwm is driven by the PID controller in _apply_pid_plant_step()

        if motion_flag_key and motion_val is not None:
            self._rx_values[motion_flag_key] = 1.0 if motion_val > 0 else 0.0

    def _apply_pid_plant_step(self) -> None:
        """PID controller + second-order plant model (one simulation tick)."""
        measured_key = self._resp.get("measured")
        target_key = self._resp.get("target")
        output_key = self._resp.get("output")
        motion_key = self._resp.get("motion_flag")

        if not (measured_key and target_key and output_key):
            return

        dt = self._sample_interval
        target = self._rx_values.get(target_key, 0.0)
        measured = self._rx_values.get(measured_key, 0.0)
        motion = self._rx_values.get(motion_key, 0.0) if motion_key else 1.0

        # PID gains from TX params (user-facing values, already wire-scaled)
        kp = self._tx_params.get("kp", 1.0)
        ki = self._tx_params.get("ki", 0.02)
        kd = self._tx_params.get("kd", 0.01)

        # When motion is disabled, stop PID and let plant decay to zero
        if motion == 0.0:
            self._pid_integral = 0.0
            self._prev_measured = measured
            self._plant_x1 += self._plant_x2 * dt
            self._plant_x2 += (
                -self._plant_omega_n**2 * self._plant_x1
                - 2 * self._plant_zeta * self._plant_omega_n * self._plant_x2
            ) * dt
            new_measured = self._plant_x1
            self._rx_values[measured_key] = new_measured
            self._rx_values[output_key] = 0.0
            return

        # --- PID controller ---
        error = target - measured
        p_term = kp * error

        # Integral term with conditional anti-windup
        raw_output = p_term + self._pid_integral
        saturated_high = raw_output >= self._max_output and error > 0
        saturated_low = raw_output <= 0.0 and error < 0
        if not (saturated_high or saturated_low):
            self._pid_integral += ki * error * dt

        # Derivative on measurement (avoids setpoint-change kick)
        d_measured = (measured - self._prev_measured) / max(dt, 1e-6)
        d_term = -kd * d_measured
        self._prev_measured = measured

        pid_output = p_term + self._pid_integral + d_term
        pid_output = max(0.0, min(self._max_output, pid_output))

        # --- Second-order plant ---
        # G(s) = ωₙ² / (s² + 2ζωₙ·s + ωₙ²), forward-Euler discretized
        self._plant_x1 += self._plant_x2 * dt
        self._plant_x2 += (
            -self._plant_omega_n**2 * self._plant_x1
            - 2 * self._plant_zeta * self._plant_omega_n * self._plant_x2
            + self._plant_omega_n**2 * pid_output
        ) * dt

        # Small measurement noise
        noise = (hash(str(self._frame_count)) % 100 - 50) / 500.0
        new_measured = self._plant_x1 + noise

        self._rx_values[measured_key] = new_measured
        self._rx_values[output_key] = pid_output

    # -- frame building ---------------------------------------------------

    def _build_frame(self) -> bytes:
        """Build one RX frame bytes from current simulation state."""
        payload = bytearray()
        for field in self._rx_payload:
            name = field["name"]
            typ = field.get("type", "float32")

            # generate value
            value = self._rx_values.get(name)
            if value is None:
                if name == "time_ms":
                    value = (self._mock_time * 1000.0) % (2**32)
                else:
                    phase = self._mock_time * 0.5 + self._rx_phases.get(name, 0)
                    lo, hi = _default_min_max(typ)
                    mid = (lo + hi) / 2.0
                    amp = (hi - lo) * 0.4
                    value = mid + amp * math.sin(phase)

            scale = field.get("wire_scale", 1)
            payload.extend(self._pack_value(value, typ, scale))

        checksum = _sum_u8(bytes([self._rx_message_id]) + bytes(payload))

        frame = bytearray()
        frame.append(self._rx_header)
        frame.append(self._rx_message_id)
        frame.extend(payload)
        frame.append(checksum)
        frame.append(self._rx_tail)
        return bytes(frame)

    def _pack_value(self, value: float, typ: str, scale: float) -> bytes:
        """Pack a single value into bytes according to type and endianness."""
        fmt_key = _FMT.get(typ)
        if fmt_key is None:
            return b"\x00" * _SIZEOF.get("uint8", 1)

        fmt = self._endian_prefix + fmt_key
        scaled = int(value * scale) if typ != "float32" else value

        try:
            return struct.pack(fmt, scaled)
        except (struct.error, OverflowError):
            lo, hi = _default_min_max(typ)
            clamped = max(lo, min(hi, scaled))
            if typ == "float32":
                return struct.pack(fmt, float(clamped))
            return struct.pack(fmt, int(clamped))
