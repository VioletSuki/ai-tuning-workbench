"""Serial port backend using pyserial."""

from __future__ import annotations

import logging

import serial

from tuner.backends.base import Backend

logger = logging.getLogger(__name__)

_PARITY_MAP = {
    "N": serial.PARITY_NONE,
    "E": serial.PARITY_EVEN,
    "O": serial.PARITY_ODD,
    "M": serial.PARITY_MARK,
    "S": serial.PARITY_SPACE,
}


class SerialBackend(Backend):
    """Backend that communicates over a physical serial port."""

    def __init__(
        self,
        port: str,
        baudrate: int = 115200,
        bytesize: int = 8,
        parity: str = "N",
        stopbits: int | float = 1,
        timeout_s: float = 0.1,
    ) -> None:
        self._port = port
        self._baudrate = baudrate
        self._bytesize = bytesize
        self._parity = parity.upper()
        self._stopbits = stopbits
        self._timeout_s = timeout_s
        self._ser: serial.Serial | None = None

    # -- Backend interface ------------------------------------------------

    def open(self) -> None:
        if self._ser is not None:
            logger.warning("Serial port %s is already open", self._port)
            return
        try:
            self._ser = serial.Serial(
                port=self._port,
                baudrate=self._baudrate,
                bytesize=self._bytesize,
                parity=_PARITY_MAP.get(self._parity, serial.PARITY_NONE),
                stopbits=self._stopbits,
                timeout=self._timeout_s,
            )
            logger.info(
                "Opened serial port %s @ %d baud", self._port, self._baudrate
            )
        except serial.SerialException as exc:
            raise serial.SerialException(
                f"Failed to open serial port {self._port}: {exc}"
            ) from exc

    def close(self) -> None:
        if self._ser is None:
            return
        try:
            self._ser.close()
        except serial.SerialException as exc:
            logger.warning("Error closing serial port %s: %s", self._port, exc)
        finally:
            self._ser = None
            logger.info("Closed serial port %s", self._port)

    def write(self, data: bytes) -> None:
        self._require_open()
        try:
            self._ser.write(data)  # type: ignore[union-attr]
        except serial.SerialException as exc:
            raise serial.SerialException(
                f"Serial write failed on {self._port}: {exc}"
            ) from exc

    def read_available(self) -> bytes:
        self._require_open()
        try:
            return self._ser.read(self._ser.in_waiting or 1)  # type: ignore[union-attr]
        except serial.SerialException as exc:
            raise serial.SerialException(
                f"Serial read failed on {self._port}: {exc}"
            ) from exc

    @property
    def is_open(self) -> bool:
        return self._ser is not None and self._ser.is_open

    # -- helpers ----------------------------------------------------------

    def _require_open(self) -> None:
        if self._ser is None or not self._ser.is_open:
            raise RuntimeError(
                f"Serial port {self._port} is not open. Call open() first."
            )
