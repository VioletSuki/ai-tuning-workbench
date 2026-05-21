"""Tests for window manager, ring buffer, and recorder integration."""

import csv
import json
import tempfile
from pathlib import Path

from tuner.runtime.ring_buffer import RingBuffer
from tuner.runtime.recorder import RunRecorder
from tuner.runtime.window_manager import WindowManager


# ---------------------------------------------------------------------------
# RingBuffer tests
# ---------------------------------------------------------------------------

class TestRingBuffer:
    def test_append_and_count(self):
        buf = RingBuffer(max_seconds=10)
        buf.append({"a": 1})
        buf.append({"a": 2})
        assert buf.count() == 2

    def test_latest(self):
        buf = RingBuffer(max_seconds=10)
        assert buf.latest() is None
        buf.append({"a": 1})
        buf.append({"a": 2})
        assert buf.latest()["a"] == 2

    def test_get_all(self):
        buf = RingBuffer(max_seconds=10)
        buf.append({"a": 1})
        buf.append({"a": 2})
        assert len(buf.get_all()) == 2

    def test_get_last_seconds(self):
        buf = RingBuffer(max_seconds=60)
        buf.append({"a": 1})
        buf.append({"a": 2})
        # Both rows were just added, so get_last(60) should return both
        rows = buf.get_last(60)
        assert len(rows) == 2

    def test_get_last_zero(self):
        buf = RingBuffer(max_seconds=60)
        buf.append({"a": 1})
        assert buf.get_last(0) == []

    def test_clear(self):
        buf = RingBuffer(max_seconds=10)
        buf.append({"a": 1})
        buf.clear()
        assert buf.count() == 0

    def test_negative_max_seconds(self):
        try:
            RingBuffer(max_seconds=-1)
            assert False, "expected ValueError"
        except ValueError:
            pass

    def test_trim_behavior(self):
        """Old rows beyond max_seconds should be trimmed on append."""
        buf = RingBuffer(max_seconds=0.05)
        buf.append({"a": 1})
        import time
        time.sleep(0.06)
        buf.append({"a": 2})  # this append triggers trim of row 1
        assert buf.count() == 1


# ---------------------------------------------------------------------------
# RunRecorder tests
# ---------------------------------------------------------------------------

class TestRunRecorder:
    def test_start_new_run_creates_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            rec = RunRecorder(project_dir=project_dir)
            run_dir = rec.start_new_run(tag="test_run")
            assert run_dir.exists()
            assert (run_dir / "raw").exists()
            assert (run_dir / "decoded").exists()
            assert (run_dir / "windows").exists()
            assert (run_dir / "agent").exists()
            assert (run_dir / "runtime").exists()
            assert (run_dir / "run_config_snapshot").exists()

    def test_record_raw_frame(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            rec = RunRecorder(project_dir=project_dir)
            rec.start_new_run(tag="raw_test")
            rec.record_raw_frame({"hex": "AB01FF", "ok": True})
            raw_file = rec.run_dir / "raw" / "raw_frames.jsonl"
            assert raw_file.exists()
            lines = raw_file.read_text().strip().split("\n")
            assert len(lines) == 1
            assert json.loads(lines[0])["ok"] is True

    def test_record_decoded_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            rec = RunRecorder(project_dir=project_dir)
            rec.start_new_run(tag="decoded_test")
            rec.record_decoded_row({"a": 1, "b": 2.0})
            rec.record_decoded_row({"a": 3, "b": 4.0})
            csv_file = rec.run_dir / "decoded" / "telemetry.csv"
            assert csv_file.exists()
            rows = list(csv.DictReader(csv_file.open()))
            assert len(rows) == 2
            assert float(rows[1]["a"]) == 3

    def test_write_runtime_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            rec = RunRecorder(project_dir=project_dir)
            rec.start_new_run(tag="json_test")
            path = rec.write_runtime_json("test.json", {"key": "value"})
            assert path.exists()
            assert json.loads(path.read_text())["key"] == "value"

    def test_write_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            rec = RunRecorder(project_dir=project_dir)
            rec.start_new_run(tag="win_test")
            meta = {"tag": "t1", "row_count": 2}
            rows = [{"a": 1}, {"a": 2}]
            win_dir = rec.write_window("window_0001", rows, meta)
            assert win_dir.exists()
            assert (win_dir / "telemetry.csv").exists()
            assert (win_dir / "window_meta.json").exists()
            loaded_meta = json.loads((win_dir / "window_meta.json").read_text())
            assert loaded_meta["tag"] == "t1"

    def test_is_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            rec = RunRecorder(project_dir=project_dir)
            assert not rec.is_active
            rec.start_new_run(tag="active_test")
            assert rec.is_active

    def test_run_dir_property(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            rec = RunRecorder(project_dir=project_dir)
            assert rec.run_dir is None
            rec.start_new_run(tag="prop_test")
            assert rec.run_dir is not None


# ---------------------------------------------------------------------------
# WindowManager integration tests (with ring buffer + recorder)
# ---------------------------------------------------------------------------

class TestWindowManager:
    def test_mark_start_end_basic(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            buf = RingBuffer(max_seconds=60)
            rec = RunRecorder(project_dir=project_dir)
            rec.start_new_run(tag="wm_test")
            wm = WindowManager(ring_buffer=buf, recorder=rec)

            # Add some data
            buf.append({"x": 1})
            buf.append({"x": 2})
            buf.append({"x": 3})

            start_info = wm.mark_start(tag="trial_001")
            assert start_info["tag"] == "trial_001"
            assert "start_monotonic" in start_info

            buf.append({"x": 4})
            buf.append({"x": 5})

            end_info = wm.mark_end()
            assert end_info["window_id"] == "window_0001"
            assert end_info["row_count"] >= 2  # at least rows from after mark_start
            assert end_info["tag"] == "trial_001"

    def test_latest_window_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            buf = RingBuffer(max_seconds=60)
            rec = RunRecorder(project_dir=project_dir)
            rec.start_new_run(tag="latest_test")
            wm = WindowManager(ring_buffer=buf, recorder=rec)
            assert wm.latest_window_id is None

            buf.append({"x": 1})
            wm.mark_start()
            wm.mark_end()
            assert wm.latest_window_id == "window_0001"

            wm.mark_start()
            wm.mark_end()
            assert wm.latest_window_id == "window_0002"

    def test_mark_end_without_start_raises(self):
        buf = RingBuffer(max_seconds=60)
        rec = RunRecorder(project_dir=Path("/tmp/dummy"))
        wm = WindowManager(ring_buffer=buf, recorder=rec)
        try:
            wm.mark_end()
            assert False, "expected RuntimeError"
        except RuntimeError:
            pass

    def test_list_windows(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            buf = RingBuffer(max_seconds=60)
            rec = RunRecorder(project_dir=project_dir)
            rec.start_new_run(tag="list_test")
            wm = WindowManager(ring_buffer=buf, recorder=rec)

            buf.append({"x": 1})
            wm.mark_start()
            wm.mark_end()
            wm.mark_start()
            wm.mark_end()

            windows = wm.list_windows()
            assert len(windows) == 2
            assert windows[0]["window_id"] == "window_0001"
            assert windows[1]["window_id"] == "window_0002"

    def test_get_last_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            buf = RingBuffer(max_seconds=60)
            rec = RunRecorder(project_dir=project_dir)
            rec.start_new_run(tag="glw_test")
            wm = WindowManager(ring_buffer=buf, recorder=rec)

            buf.append({"x": 1})
            buf.append({"x": 2})
            import time
            time.sleep(0.01)
            rows = wm.get_last_window(0.02)  # last 20ms
            assert len(rows) >= 2

    def test_resolve_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            buf = RingBuffer(max_seconds=60)
            rec = RunRecorder(project_dir=project_dir)
            rec.start_new_run(tag="resolve_test")
            wm = WindowManager(ring_buffer=buf, recorder=rec)

            buf.append({"x": 1})
            wm.mark_start()
            wm.mark_end()

            assert wm.resolve_window("latest") == "window_0001"
            assert wm.resolve_window("window_0001") == "window_0001"
            assert wm.resolve_window("bogus") is None

    def test_get_window_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            buf = RingBuffer(max_seconds=60)
            rec = RunRecorder(project_dir=project_dir)
            rec.start_new_run(tag="gwr_test")
            wm = WindowManager(ring_buffer=buf, recorder=rec)

            buf.append({"x": 1})
            buf.append({"x": 2})
            wm.mark_start()
            buf.append({"x": 3})
            wm.mark_end()

            rows = wm.get_window_rows("window_0001")
            assert len(rows) >= 1  # at least the row added after start
