"""Simulation backend — first-version placeholder.

``SimBackend`` conforms to the ``Backend`` interface but raises
``NotImplementedError`` on ``open()`` to signal that simulation is not yet
implemented in this version.
"""

from __future__ import annotations

import logging

from tuner.backends.base import Backend

logger = logging.getLogger(__name__)


class SimBackend(Backend):
    """Placeholder simulation backend.

    This is a reserved stub for future use.  Calling ``open()`` raises
    ``NotImplementedError``.  Other methods are safe no-ops or return empty
    bytes.
    """

    def __init__(self) -> None:
        self._opened = False

    def open(self) -> None:
        msg = (
            "SimBackend is not implemented in this version. "
            "Use backend type 'mock' or 'serial' instead."
        )
        raise NotImplementedError(msg)

    def close(self) -> None:
        self._opened = False

    def write(self, data: bytes) -> None:
        logger.debug("SimBackend.write(%d bytes) — no-op", len(data))

    def read_available(self) -> bytes:
        return b""

    @property
    def is_open(self) -> bool:
        return self._opened
