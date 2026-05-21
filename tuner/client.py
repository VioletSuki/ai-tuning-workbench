"""HTTP client for the ai-tuning-workbench daemon API."""

from __future__ import annotations

from typing import Any

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:8765"
DEFAULT_TIMEOUT = 5.0


class DaemonNotRunningError(ConnectionError):
    """Raised when the daemon is not reachable."""


class TunerClient:
    """HTTP client that speaks to the local daemon API.

    All methods return the parsed JSON dict from the daemon response.
    If the daemon is not reachable, *DaemonNotRunningError* is raised.
    """

    def __init__(self, base_url: str = DEFAULT_BASE_URL, timeout: float = DEFAULT_TIMEOUT):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = httpx.Client(timeout=timeout, trust_env=False)

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            r = self._client.get(f"{self._base_url}{path}", params=params)
            r.raise_for_status()
            return r.json()
        except httpx.ConnectError:
            raise DaemonNotRunningError(
                "Daemon is not running. Start it with: tuner serve --project <project_dir>"
            )

    def _post(
        self, path: str, json_body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            r = self._client.post(f"{self._base_url}{path}", json=json_body)
            r.raise_for_status()
            return r.json()
        except httpx.ConnectError:
            raise DaemonNotRunningError(
                "Daemon is not running. Start it with: tuner serve --project <project_dir>"
            )

    # -- public API methods ---------------------------------------------------

    def health(self) -> dict[str, Any]:
        return self._get("/health")

    def status(self) -> dict[str, Any]:
        return self._get("/status")

    def send_hex(self, hex_string: str) -> dict[str, Any]:
        return self._post("/send-hex", {"hex": hex_string})

    def set_param(self, params: dict[str, Any], force: bool = False) -> dict[str, Any]:
        body: dict[str, Any] = {"params": params}
        if force:
            body["force"] = True
        return self._post("/set-param", body)

    def get_current_params(self) -> dict[str, Any]:
        return self._get("/current-params")

    def start_record(self, tag: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if tag is not None:
            body["tag"] = tag
        return self._post("/start-record", body)

    def stop_record(self) -> dict[str, Any]:
        return self._post("/stop-record")

    def mark_window_start(self, tag: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if tag is not None:
            body["tag"] = tag
        return self._post("/mark-window-start", body)

    def mark_window_end(self) -> dict[str, Any]:
        return self._post("/mark-window-end")

    def wait(self, seconds: float) -> dict[str, Any]:
        return self._post("/wait", {"seconds": seconds})

    def get_raw(self, **kwargs: Any) -> dict[str, Any]:
        return self._get("/raw", params=_drop_none(kwargs))

    def get_data(self, **kwargs: Any) -> dict[str, Any]:
        # Join list-type vars into a comma-separated string for the query param
        if "vars" in kwargs and isinstance(kwargs["vars"], list):
            kwargs["vars"] = ",".join(kwargs["vars"])
        return self._get("/data", params=_drop_none(kwargs))

    def get_data_rows(self, last: str = "5s") -> list[dict[str, Any]]:
        """Fetch latest telemetry rows for live plotting."""
        resp = self._get("/data", params={"last": last})
        return resp.get("rows", [])

    def stream_snapshot(self, **kwargs: Any) -> dict[str, Any]:
        if "vars" in kwargs and isinstance(kwargs["vars"], list):
            kwargs["vars"] = ",".join(kwargs["vars"])
        return self._get("/stream", params=_drop_none(kwargs))

    def eval_window(self, **kwargs: Any) -> dict[str, Any]:
        return self._post("/eval-window", kwargs)

    def plot(self, **kwargs: Any) -> dict[str, Any]:
        return self._post("/plot", kwargs)

    def get_runtime_context(self) -> dict[str, Any]:
        return self._get("/runtime-context")

    def get_summary(self, latest: bool = False) -> dict[str, Any]:
        return self._get("/summary", params={"latest": str(latest).lower()})


def _drop_none(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}
