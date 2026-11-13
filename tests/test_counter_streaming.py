"""Timing, disk backpressure, and discontinuity regression coverage without hardware."""

import queue
import threading
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from laser_platform import library
from laser_platform.ufc import core
from laser_platform.ufc.allan import frequency_adev, frequency_file_adev
from laser_platform.ufc.instrument import CounterConfig
from laser_platform.ufc.recording import FrequencyRecorder


class SimulatedClock:
    def __init__(self):
        self.now = 0.0
        self.stopped = False

    def is_set(self):
        return self.stopped

    def set(self):
        self.stopped = True

    def wait(self, seconds):
        self.now += max(0, seconds)
        return self.stopped


def simulated_worker(tmp_path, monkeypatch, sample_count=2500):
    clock = SimulatedClock()
    client = Mock(connect=Mock(return_value="Keysight,53230A,TEST,1"), stop_drain_discarded_samples=0)
    client.stop_and_drain.side_effect = lambda: iter(())
    monkeypatch.setattr(core, "time", SimpleNamespace(monotonic=lambda: clock.now))
    monkeypatch.setattr(core, "Keysight53230A", lambda: client)
    monkeypatch.setattr(core, "CounterConfig", lambda **kw: replace(CounterConfig(**kw), sample_count=sample_count))
    monkeypatch.setattr(core, "DiskAdevWorker", lambda **kw: Mock(thread=Mock(is_alive=Mock(return_value=False))))
    worker = core.AcquisitionWorker(core.config_from_payload({
        "resource": "USB::TEST", "library_dir": str(tmp_path),
    }), queue.Queue())
    worker.stop_event = clock
    return worker, client, clock


@pytest.mark.parametrize("empty_tail", [False, True])
def test_restart_deadlines_partial_tail_and_slow_disk(tmp_path, monkeypatch, empty_tail):
    worker, client, clock = simulated_worker(tmp_path, monkeypatch)
    disk_entered, disk_release = threading.Event(), threading.Event()
    original_append = library.LmpWriter.append_ufc_frequency
    written = []

    def slow_append(storage, values):
        disk_entered.set()
        assert disk_release.wait(3), "normal restart waited for disk I/O"
        original_append(storage, values)
        written.extend(values.tolist())

    monkeypatch.setattr(library.LmpWriter, "append_ufc_frequency", slow_append)
    sizes = iter([900, 1000, *([0] if empty_tail else []), 600, 1000])
    reads, restarts = [], []
    offset = 0

    def read(count):
        nonlocal offset
        reads.append((clock.now, count))
        clock.now += 0.1  # Transport delay must not accumulate between batches.
        size = next(sizes)
        values = np.arange(offset, offset + size, dtype=float)
        offset += size
        if offset == 3500:
            worker.stop()
        return values

    def start():
        restarts.append(clock.now)
        if len(restarts) == 2:
            assert disk_entered.wait(2)
            assert written == []  # INIT can proceed while earlier file writes wait.
            assert offset == 2500  # Includes the entire final partial transfer.
            assert client.configure.call_count == 2  # Only initial setup.
            client.abort.assert_not_called()
            client.stop_and_drain.assert_not_called()
            disk_release.set()

    client.read_chunk.side_effect = read
    client.start.side_effect = start
    try:
        worker._run()
    finally:
        disk_release.set()
    messages = list(worker.out_queue.queue)
    assert not any(isinstance(m, core.ErrorMessage) for m in messages), messages
    assert [r[1] for r in reads] == ([1000, 1000, 600, 600, 1000] if empty_tail else [1000, 1000, 600, 1000])
    assert [r[0] for r in reads] == pytest.approx([1, 1.9, 2.5, 2.85, 3.95] if empty_tail else [1, 1.9, 2.5, 3.6])
    assert restarts == pytest.approx([0, 2.95 if empty_tail else 2.6])
    path = next(tmp_path.glob("*.lmp"))
    np.testing.assert_array_equal(np.fromfile(path, dtype="<f8", offset=library.PAYLOAD_OFFSET), np.arange(3500))
    metadata = library.read_metadata(path)
    assert metadata["ufc_segment_starts"] == [0, 2500]
    assert metadata["stop_drain"]["complete"]
    assert [m.segment_start for m in messages if isinstance(m, core.DataMessage)] == [True, False, False, True]
    assert worker.recording_finalized.is_set()


@pytest.mark.parametrize("drain_failure", [False, True])
def test_error_recovery_drains_before_reconfiguration(tmp_path, monkeypatch, drain_failure):
    worker, client, clock = simulated_worker(tmp_path, monkeypatch)
    operations = []

    def read(count):
        call = client.read_chunk.call_count
        if call == 1:
            return np.arange(1000.)
        if call == 2:
            clock.now = 5.0
            raise OSError("interrupted reply")
        worker.stop()
        return np.arange(1002., 2002.)

    def drain():
        operations.append("drain")
        if client.stop_and_drain.call_count == 1:
            yield np.array([1000., 1001.])
            if drain_failure:
                raise OSError("remaining buffer unavailable")

    client.configure.side_effect = lambda config: operations.append("configure")
    client.start.side_effect = lambda: operations.append("INIT")
    client.read_chunk.side_effect = read
    client.stop_and_drain.side_effect = drain
    worker._run()
    path = next(tmp_path.glob("*.lmp"))
    metadata = library.read_metadata(path)
    np.testing.assert_array_equal(np.fromfile(path, dtype="<f8", offset=library.PAYLOAD_OFFSET),
                                  np.arange(1002 if drain_failure else 2002))
    assert metadata["ended_at"]
    if drain_failure:
        assert operations == ["configure", "configure", "INIT", "drain"]
        assert "remaining buffer unavailable" in metadata["acquisition_error"]
        assert isinstance(list(worker.out_queue.queue)[-1], core.ErrorMessage)
    else:
        assert operations == ["configure", "configure", "INIT", "drain", "configure", "INIT", "drain"]
        assert metadata["ufc_segment_starts"] == [0, 1000, 1002]


def make_storage(tmp_path):
    return library.LmpWriter(tmp_path, "ufc", "ufc", "test", "counter", "USB::TEST", "Hz",
                             {"kind": "ufc_frequency_f64", "record_size": 8, "dtype": "<f8", "adev_semantic": "adev"},
                             {"sample_rate_hz": 10, "optical_frequency_hz": 3.5e14, "divide_adev_by_optical_frequency": False,
                              "divide_adev_by_sqrt2": False})


def test_slow_active_counter_is_not_restarted_at_nominal_deadline(tmp_path, monkeypatch):
    worker, client, clock = simulated_worker(tmp_path, monkeypatch)
    client.is_measuring.return_value = True

    def read(count):
        if client.read_chunk.call_count == 1:
            clock.now = 10  # Beyond the nominal segment deadline plus tolerance.
            return np.array([])
        worker.stop()
        return np.arange(1000.)

    client.read_chunk.side_effect = read
    worker._run()
    client.is_measuring.assert_called_once()
    client.start.assert_called_once()
    assert client.stop_and_drain.call_count == 1  # Only the final user stop.


@pytest.mark.parametrize("failure", [False, True])
def test_bounded_writer_backpressure_and_disk_error(tmp_path, monkeypatch, failure):
    storage = make_storage(tmp_path)
    entered, release, submitted = threading.Event(), threading.Event(), threading.Event()
    original_append = storage.append_ufc_frequency
    events, errors = [], []

    def append(values):
        entered.set()
        assert release.wait(3)
        if failure:
            raise OSError("disk full")
        original_append(values)

    monkeypatch.setattr(storage, "append_ufc_frequency", append)
    recorder = FrequencyRecorder(storage, lambda *args: events.append(args), queue_size=1)
    recorder.submit(np.array([1.]), 1, True)
    assert entered.wait(2)
    recorder.submit(np.array([2.]), 2)

    def submit():
        try:
            recorder.submit(np.array([3.]), 3)
        except RuntimeError as exc:
            errors.append(str(exc))
        finally:
            submitted.set()

    producer = threading.Thread(target=submit)
    producer.start()
    try:
        assert not submitted.wait(0.05)
        assert recorder.snapshot() == (0, (0,))
    finally:
        release.set()
        producer.join(timeout=3)
    assert not producer.is_alive()
    if failure:
        with pytest.raises(RuntimeError, match="disk full"):
            recorder.finish()
        assert errors and not events
        assert library.read_metadata(storage.path)["recording_error"] == "disk full"
    else:
        recorder.finish()
        assert [event[1] for event in events] == [1, 2, 3]
        assert recorder.snapshot() == (3, (0,))
        np.testing.assert_array_equal(np.fromfile(storage.path, dtype="<f8", offset=library.PAYLOAD_OFFSET), [1, 2, 3])
    assert recorder.finished.is_set() and storage._file.closed


def test_segmented_adev_excludes_cross_boundary_blocks_and_pairs(tmp_path):
    parts = [np.array([0., 0, 2, 2, 0]), np.array([100., 100, 104, 104, 100, 100]), np.array([1000., 1004, 1000])]
    values = np.concatenate(parts)
    path = tmp_path / "frequency.f64"
    values.astype("<f8").tofile(path)
    options = dict(sample_rate_hz=10, m_values=[1, 2, 3, 4], segment_starts=[0, 5, 11],
                   divide_by_optical_frequency=False, divide_by_sqrt2=False)
    memory = frequency_adev(values, **options)
    disk = frequency_file_adev(path, len(values), max_chunk_samples=2, **options)
    expected, counts = [], []
    for m in [1, 2, 3]:
        diffs = np.concatenate([np.diff(part[:len(part) // m * m].reshape(-1, m).mean(axis=1)) for part in parts])
        expected.append(np.sqrt(0.5 * np.mean(diffs ** 2)))
        counts.append(len(diffs))
    np.testing.assert_allclose(memory.adev, expected)
    np.testing.assert_allclose(disk.adev, expected)
    np.testing.assert_array_equal(disk.pairs, counts)
    np.testing.assert_array_equal(memory.m, [1, 2, 3])


def test_segment_boundaries_survive_library_preview_and_exports(tmp_path):
    storage = make_storage(tmp_path)
    storage.append_ufc_frequency(np.ones(20))
    storage.mark_ufc_segment_start()
    storage.append_ufc_frequency(np.full(20, 100.))
    storage.close()
    preview = library.library_item_preview(tmp_path, storage.path.name, max_points=4)
    points = preview["waveform"]["points"]
    assert [p["y"] for p in points] == [1, 1, None, 100, 100]
    for max_samples in (None, 8):
        result = library._calculate_adev(storage.path, storage.metadata, 40, max_samples)
        assert result.adev.size and np.all(result.adev == 0)
    output = tmp_path / "adev.csv"
    library.export_library_series(tmp_path, storage.path.name, "adev", output)
    exported = np.loadtxt(output, delimiter=",", skiprows=1)
    assert np.all(exported[:, 1] == 0)
    waveform = tmp_path / "waveform.csv"
    library.export_library_series(tmp_path, storage.path.name, "waveform", waveform)
    assert waveform.read_text().splitlines()[0] == "sample_index,time_s,frequency_hz,segment_index"
    exported_waveform = np.loadtxt(waveform, delimiter=",", skiprows=1)
    np.testing.assert_array_equal(exported_waveform[:, 3], [0] * 20 + [1] * 20)


def test_live_adev_uses_committed_snapshot_and_segment_boundaries(tmp_path):
    storage = make_storage(tmp_path)
    storage.append_ufc_frequency(np.ones(20))
    storage.mark_ufc_segment_start()
    storage.append_ufc_frequency(np.full(20, 100.))
    storage.close()
    messages = queue.Queue()
    worker = core.DiskAdevWorker(storage.path, 10, 1, False, False, messages,
                                 recording_snapshot=lambda: (30, (0, 20)))
    assert worker._calculate_once(force=True) == 30
    message = messages.get_nowait()
    assert isinstance(message, core.AdevMessage)
    assert message.sample_count == 30
    assert message.adev.adev.size and np.all(message.adev.adev == 0)
    assert message.adev.pairs[0] == 28
