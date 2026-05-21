"""RuntimeState — central runtime state aggregating ring buffer, recorder, and windows."""

import copy
import time
from pathlib import Path

from tuner.config.schema import ConfigBundle
from tuner.runtime.ring_buffer import RingBuffer
from tuner.runtime.recorder import RunRecorder
from tuner.runtime.window_manager import WindowManager
from tuner.utils.time_utils import utc_now_iso


class RuntimeState:
    """Aggregated runtime state for the daemon.

    Attributes
    ----------
    config : ConfigBundle
    current_params : dict
        Current TX parameter values.
    frame_index : int
        Monotonically increasing RX frame counter.
    latest_data_time : str | None
        ISO-8601 timestamp of the most recently decoded data.
    latest_metrics : dict | None
        Most recent metrics result (populated by eval-window).
    ring_buffer : RingBuffer
    recorder : RunRecorder
    windows : WindowManager
    """

    def __init__(self, config: ConfigBundle) -> None:
        self.config = config
        self.current_params: dict = {}
        self.frame_index: int = 0
        self.latest_data_time: str | None = None
        self.latest_metrics: dict | None = None

        rb_seconds = config.project.runtime.ring_buffer_seconds
        self.ring_buffer = RingBuffer(max_seconds=rb_seconds)
        self.recorder = RunRecorder(
            project_dir=config.project_dir,
            config_bundle=config,
            run_name=config.project.recording.default_run_name,
        )
        self.windows = WindowManager(
            ring_buffer=self.ring_buffer, recorder=self.recorder
        )

    # -- param management ----------------------------------------------------

    def merge_params(self, updates: dict) -> dict:
        """Merge *updates* into ``current_params`` and return the merged dict."""
        merged = copy.deepcopy(self.current_params)
        merged.update(updates)
        self.current_params = merged
        return merged

    # -- data ingestion ------------------------------------------------------

    def append_decoded(
        self, decoded: dict, raw_meta: dict | None = None
    ) -> dict:
        """Ingest one decoded telemetry row.

        Adds ``host_monotonic``, ``frame_index``, and ``host_time`` to the
        row, pushes it into the ring buffer, and records it if a run is active.

        Returns the enriched row.
        """
        now = time.monotonic()
        iso = utc_now_iso()
        self.frame_index += 1

        row = dict(decoded)
        row["host_monotonic"] = now
        row["frame_index"] = self.frame_index
        row["host_time"] = iso

        self.ring_buffer.append(row)
        self.latest_data_time = iso

        if self.recorder.run_dir is not None:
            meta = dict(raw_meta or {})
            meta["frame_index"] = self.frame_index
            self.recorder.record_raw_frame(meta)
            self.recorder.record_decoded_row(row)

        return row

    # -- status ---------------------------------------------------------------

    def status_dict(self) -> dict:
        """Return a JSON-serialisable status snapshot."""
        return {
            "project": self.config.project.project_name,
            "backend_type": self.config.project.backend.type,
            "run_active": self.recorder.run_dir is not None,
            "run_dir": str(self.recorder.run_dir) if self.recorder.run_dir else None,
            "frame_index": self.frame_index,
            "ring_buffer_count": self.ring_buffer.count(),
            "latest_data_time": self.latest_data_time,
        }
