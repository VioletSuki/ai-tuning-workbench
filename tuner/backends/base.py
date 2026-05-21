"""Backend abstract base class and factory function."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable


class Backend(ABC):
    """Abstract communication backend.

    All backends (serial, mock, sim) implement this interface so the daemon
    and client can switch between them transparently.
    """

    @abstractmethod
    def open(self) -> None:
        """Open / initialise the backend connection."""

    @abstractmethod
    def close(self) -> None:
        """Close the backend connection and release resources."""

    @abstractmethod
    def write(self, data: bytes) -> None:
        """Write raw bytes to the backend."""

    @abstractmethod
    def read_available(self) -> bytes:
        """Read all currently available bytes (non-blocking).

        Returns empty bytes if nothing is available.
        """

    @property
    @abstractmethod
    def is_open(self) -> bool:
        """Whether the backend connection is currently open."""


def create_backend(
    backend_type: str,
    *,
    codec: Any = None,
    protocol_manifest: dict | None = None,
    mock_config: dict | None = None,
    serial_config: dict | None = None,
) -> Backend:
    """Factory: create a Backend instance by type name.

    Parameters
    ----------
    backend_type : str
        One of ``"mock"``, ``"serial"``, or ``"sim"``.
    codec : optional
        FixedBinaryCodec instance (needed by MockBackend for TX decode).
    protocol_manifest : dict, optional
        Protocol manifest dict (needed by MockBackend for RX frame generation).
    mock_config : dict, optional
        Mock-specific configuration (tx_to_rx_map, response_model, etc.).
    serial_config : dict, optional
        Serial port configuration (port, baudrate, bytesize, parity, …).

    Returns
    -------
    Backend instance.
    """
    if backend_type == "mock":
        from tuner.backends.mock_backend import MockBackend

        return MockBackend(
            protocol_manifest=protocol_manifest or {},
            codec=codec,
            mock_config=mock_config,
        )
    if backend_type == "serial":
        from tuner.backends.serial_backend import SerialBackend

        cfg = serial_config or {}
        return SerialBackend(
            port=cfg.get("port", ""),
            baudrate=cfg.get("baudrate", 115200),
            bytesize=cfg.get("bytesize", 8),
            parity=cfg.get("parity", "N"),
            stopbits=cfg.get("stopbits", 1),
            timeout_s=cfg.get("timeout_s", 0.1),
        )
    if backend_type == "sim":
        from tuner.backends.sim_backend import SimBackend

        return SimBackend()

    msg = f"Unknown backend_type: {backend_type!r} (expected mock/serial/sim)"
    raise ValueError(msg)
