"""RunRecorder — manages run directory and data file I/O."""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path
from typing import Any

from tuner.utils.file_utils import ensure_dir, append_jsonl
from tuner.utils.time_utils import local_timestamp_for_dir


class RunRecorder:
    """Creates and manages a structured run directory for one recording session.

    Parameters
    ----------
    project_dir : Path
        Path to the project root (contains ``manifests/`` and ``runs/``).
    project_name : str
        Project name used as fallback run name.
    config_bundle
        The ``ConfigBundle`` (or any object with ``.project_dir`` and
        ``.project.recording.default_run_name``), used for snapshot.
        Pass ``None`` to skip manifest snapshot (testing only).
    run_name : str | None
        Explicit run name.  Falls back to ``config_bundle.project.recording.default_run_name``
        or ``"default_run"``.
    """

    def __init__(
        self,
        project_dir: Path,
        *,
        project_name: str = "project",
        config_bundle: Any = None,
        run_name: str | None = None,
    ) -> None:
        self._project_dir = Path(project_dir)
        self._runs_dir = self._project_dir / "runs"
        self._config_bundle = config_bundle

        # Resolve run name
        if run_name:
            self._run_name = run_name
        elif config_bundle is not None:
            self._run_name = getattr(
                config_bundle.project.recording, "default_run_name", "default_run"
            )
        else:
            self._run_name = "default_run"

        self._run_dir: Path | None = None
        self._raw_frames_file: Path | None = None
        self._decoded_csv_file: Path | None = None
        self._decoded_jsonl_file: Path | None = None
        self._csv_writer: Any = None
        self._csv_file_handle: Any = None

    # -- properties ---------------------------------------------------------

    @property
    def run_dir(self) -> Path | None:
        """Current run directory, or ``None`` if no run has been started."""
        return self._run_dir

    @property
    def runs_dir(self) -> Path:
        return self._runs_dir

    @property
    def is_active(self) -> bool:
        """Whether a run directory has been created and is ready for recording."""
        return self._run_dir is not None

    # -- run lifecycle ------------------------------------------------------

    def start_new_run(self, tag: str | None = None) -> Path:
        """Create a new run directory and snapshot manifests.

        If a previous run was active, its file handles are closed first.

        Returns the path to the new run directory.
        """
        self._close_files()

        timestamp = local_timestamp_for_dir()
        name_part = tag if tag else self._run_name
        dir_name = f"{timestamp}_{name_part}"
        self._run_dir = ensure_dir(self._runs_dir / dir_name)

        # Create sub-directories
        self._snapshot_dir = ensure_dir(self._run_dir / "run_config_snapshot")
        self._raw_dir = ensure_dir(self._run_dir / "raw")
        self._decoded_dir = ensure_dir(self._run_dir / "decoded")
        self._windows_dir = ensure_dir(self._run_dir / "windows")
        self._agent_dir = ensure_dir(self._run_dir / "agent")
        self._runtime_dir = ensure_dir(self._run_dir / "runtime")

        # Snapshot manifests
        self._snapshot_manifests()

        # File paths
        self._raw_frames_file = self._raw_dir / "raw_frames.jsonl"
        self._decoded_csv_file = self._decoded_dir / "telemetry.csv"
        self._decoded_jsonl_file = self._decoded_dir / "telemetry.jsonl"
        self._csv_writer = None
        self._csv_fieldnames: list[str] | None = None

        return self._run_dir

    # -- recording methods --------------------------------------------------

    def record_raw_frame(self, frame: dict[str, Any]) -> None:
        """Append a raw frame dict as a JSON line."""
        if self._raw_frames_file is None:
            return
        append_jsonl(self._raw_frames_file, frame)

    def record_decoded_row(self, row: dict[str, Any]) -> None:
        """Append a decoded row to both CSV and JSONL files.

        The CSV header is written on the first call (from the row keys).
        Subsequent calls append without repeating the header.
        """
        if self._decoded_csv_file is None or self._decoded_jsonl_file is None:
            return

        # JSONL
        append_jsonl(self._decoded_jsonl_file, row)

        # CSV — append mode with lazy header init
        fieldnames = list(row.keys())
        if self._csv_fieldnames is None:
            self._csv_fieldnames = fieldnames
            self._csv_file_handle = open(
                self._decoded_csv_file, "w", newline="", encoding="utf-8"
            )
            writer = csv.DictWriter(self._csv_file_handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerow(row)
            self._csv_file_handle.flush()
        else:
            file_exists = self._decoded_csv_file.exists()
            with open(self._decoded_csv_file, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=self._csv_fieldnames)
                if not file_exists or self._decoded_csv_file.stat().st_size == 0:
                    writer.writeheader()
                writer.writerow(row)

    # -- runtime / agent files ----------------------------------------------

    def write_runtime_json(self, name: str, data: dict[str, Any]) -> Path:
        """Write *data* as JSON to ``runtime/<name>`` under the run directory.

        Returns the path of the written file.
        """
        if self._run_dir is None:
            raise RuntimeError("no active run; call start_new_run() first")
        path = self._runtime_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        return path

    def write_agent_jsonl(self, name: str, row: dict[str, Any]) -> Path:
        """Append a JSON line to ``agent/<name>``.

        Returns the path of the file.
        """
        if self._run_dir is None:
            raise RuntimeError("no active run; call start_new_run() first")
        path = self._agent_dir / name
        append_jsonl(path, row)
        return path

    # -- window persistence -------------------------------------------------

    def write_window(
        self,
        window_id: str,
        rows: list[dict[str, Any]],
        meta: dict[str, Any],
    ) -> Path:
        """Persist a window slice to ``windows/<window_id>/``.

        Writes ``telemetry.csv`` and ``window_meta.json``.

        Returns the window directory path.
        """
        if self._run_dir is None:
            raise RuntimeError("no active run; call start_new_run() first")
        win_dir = ensure_dir(self._windows_dir / window_id)

        # telemetry.csv
        if rows:
            csv_path = win_dir / "telemetry.csv"
            fieldnames = list(rows[0].keys())
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

        # window_meta.json
        meta_path = win_dir / "window_meta.json"
        meta_path.write_text(
            json.dumps(meta, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

        return win_dir

    # -- internals ----------------------------------------------------------

    def _snapshot_manifests(self) -> None:
        """Copy manifest YAML files into run_config_snapshot/."""
        if self._config_bundle is None:
            return
        src = self._config_bundle.project_dir
        for name in ("project_manifest.yaml", "protocol_manifest.yaml", "metrics_manifest.yaml"):
            src_file = src / "manifests" / name
            if src_file.exists():
                shutil.copy2(src_file, self._snapshot_dir / name)

    def _close_files(self) -> None:
        """Close any open file handles."""
        if self._csv_file_handle is not None:
            self._csv_file_handle.close()
            self._csv_file_handle = None
        self._csv_writer = None
        self._csv_fieldnames = None

    def close_run(self) -> None:
        """Close the active run by closing file handles and resetting run state."""
        self._close_files()
        self._run_dir = None
