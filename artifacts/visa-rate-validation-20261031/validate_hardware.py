"""Exercise the real acquisition worker, disk writer, ADEV and event serialization.

Requires an idle counter with no unread data. Takes an exclusive VISA lock and
restores the instrument's learned setup in finally. Does not change app settings.
"""
import hashlib
import argparse
import json
from pathlib import Path
import queue
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from laser_platform.library import PAYLOAD_OFFSET, read_metadata
from laser_platform.ufc import core
from laser_platform.ufc.instrument import CounterConfig, Keysight53230A
from pyvisa.constants import ResourceAttribute

OUT = Path(__file__).resolve().parent
RESOURCE = 'USB0::0x0957::0x1907::MY59220164::0::INSTR'
SECONDS = 35
RATES = [100000, 500000, 5000, 10000, 50000]
QUERIES = ['CONF', 'FORM:DATA', 'FORM:BORD', 'SENS:FREQ:MODE',
           'SENS:FREQ:GATE:SOUR', 'SENS:FREQ:GATE:TIME', 'SAMP:COUN',
           'TRIG:SOUR', 'TRIG:COUN', 'DISP']


def errors(inst):
    replies = []
    for _ in range(20):
        reply = inst.query('SYST:ERR?').strip()
        if int(reply.split(',')[0]) == 0:
            return replies
        replies.append(reply)
    raise RuntimeError(f'Error queue did not clear: {replies}')


class ProbedCounter(Keysight53230A):
    def __init__(self, inst, identity):
        super().__init__()
        self._inst = inst
        self.identity = identity
        self.starts = []
        self.reads = []
        self.setup = []
        self.stopped_at = None

    def connect(self):
        return self.identity

    def close(self):
        pass  # Outer scope owns the exclusive connection and restoration.

    def configure(self, config):
        super().configure(config)
        result = {'gate_s': float(self._inst.query('SENS:FREQ:GATE:TIME?')),
                  'errors': errors(self._inst)}
        self.setup.append(result)
        if result['errors']:
            raise RuntimeError(f'Configuration rejected: {result}')

    def start(self):
        super().start()
        self.starts.append(time.perf_counter())

    def read_chunk(self, count, **kwargs):
        before = time.perf_counter()
        try:
            values = super().read_chunk(count, **kwargs)
        except Exception as exc:
            self.reads.append({'start': before, 'end': time.perf_counter(),
                               'requested': count, 'error': repr(exc)})
            raise
        self.reads.append({'start': before, 'end': time.perf_counter(),
                           'requested': count, 'received': int(values.size)})
        return values

    def stop_and_drain(self):
        self.stopped_at = time.perf_counter()
        yield from super().stop_and_drain()


def run(inst, identity, rate, repetition):
    source = ProbedCounter(inst, identity)
    core.Keysight53230A = lambda: source
    messages = queue.Queue()
    worker = core.AcquisitionWorker(core.config_from_payload({
        'resource': RESOURCE, 'channel': 3, 'sample_rate_hz': rate,
        'library_dir': str(OUT / 'recordings'),
        'display_name': f'{rate}Hz validation {repetition}',
        'divide_adev_by_optical_frequency': False, 'divide_adev_by_sqrt2': False,
    }), messages)
    row = {'nominal_rate_hz': rate, 'repetition': repetition,
           'target_wall_s': SECONDS, 'statuses': [], 'failures': [], 'adev_updates': 0}
    digest = hashlib.sha256()
    received = 0
    path = None
    deadline = time.perf_counter() + SECONDS + 90
    worker.start()
    try:
        while worker.thread.is_alive() or not messages.empty():
            if source.starts and time.perf_counter() - source.starts[0] >= SECONDS:
                worker.stop()
            if time.perf_counter() > deadline:
                raise TimeoutError('Worker did not finish within its validation budget')
            try:
                message = messages.get(timeout=.05)
            except queue.Empty:
                continue
            # Exercise conversion and JSON encoding used for frontend delivery.
            event = core.event_from_message(message)
            json.dumps(event)
            if isinstance(message, core.DataMessage):
                received += int(message.frequency_hz.size)
                digest.update(message.frequency_hz.astype('<f8', copy=False).tobytes())
                path = message.library_file
            elif isinstance(message, core.AdevMessage):
                row['adev_updates'] += 1
            elif isinstance(message, core.StatusMessage):
                row['statuses'].append(message.text)
            elif isinstance(message, (core.ErrorMessage, core.RecoverableAcquisitionErrorMessage)):
                row['failures'].append(event)
            elif isinstance(message, core.DoneMessage):
                row['done'] = message.text
                path = message.library_file
    finally:
        worker.stop()
        worker.thread.join(timeout=90)
        if worker.thread.is_alive():
            raise RuntimeError('Worker is still active; unsafe to restore concurrently')
    row.update(setup=source.setup, read_calls=len(source.reads),
               received_samples=received, instrument_errors=errors(inst),
               questionable_event=int(inst.query('STAT:QUES:EVEN?')),
               pending_readings=int(inst.query('DATA:POIN?')),
               recording_finalized=worker.recording_finalized.is_set())
    if source.starts and source.stopped_at:
        row['acquisition_wall_s'] = source.stopped_at - source.starts[0]
        row['effective_readings_per_s'] = received / row['acquisition_wall_s']
        row['restart_count'] = len(source.starts) - 1
        row['full_segment_wall_s'] = np.diff(source.starts).tolist()
    if path:
        metadata = read_metadata(path)
        values = np.fromfile(path, dtype='<f8', offset=PAYLOAD_OFFSET)
        row.update(recording=str(path), saved_samples=int(values.size),
                   valid_samples=int(np.sum(np.isfinite(values) & (values > 0) & (values < 1e36))),
                   received_matches_saved=(digest.hexdigest() == hashlib.sha256(values.tobytes()).hexdigest()),
                   stop_drain=metadata.get('stop_drain'),
                   segment_starts=metadata.get('ufc_segment_starts'),
                   mean_frequency_hz=float(np.mean(values)))
    label = f'{rate}Hz-run{repetition}'
    (OUT / (label + '-reads.json')).write_text(json.dumps(source.reads, indent=2), encoding='utf-8')
    row['integrity_pass'] = bool(
        row.get('saved_samples', 0) == received == row.get('valid_samples', -1)
        and row.get('received_matches_saved') and row.get('stop_drain', {}).get('complete')
        and not row['failures'] and not row['instrument_errors']
        and not row['questionable_event'] and not row['pending_readings'])
    return row


def main():
    global SECONDS
    parser = argparse.ArgumentParser()
    parser.add_argument('--rates', nargs='+', type=int, default=RATES)
    parser.add_argument('--repetitions', nargs='+', type=int, default=[1, 2])
    parser.add_argument('--seconds', type=float, default=SECONDS)
    parser.add_argument('--output', default='results.json')
    args = parser.parse_args()
    SECONDS = args.seconds
    report_path = OUT / args.output
    connection = Keysight53230A()
    connection.configure(CounterConfig(RESOURCE))
    identity = connection.connect()
    inst = connection._inst
    report = {'identity': identity, 'resource': RESOURCE, 'tests': [],
              'method': 'Real AcquisitionWorker, disk recording, live ADEV and JSON events; no live GUI rendering.'}
    modified = False
    learned = None
    original_factory = core.Keysight53230A
    try:
        inst.lock_excl(timeout=2000)
        if '53230A' not in identity:
            raise RuntimeError('Expected 53230A')
        if int(inst.query('STAT:OPER:COND?')) & 16 or int(inst.query('DATA:POIN?')):
            raise RuntimeError('Counter is active or has unread data; refusing to disturb it')
        report['original_settings'] = {q: inst.query(q + '?').strip() for q in QUERIES}
        if '(@3)' not in report['original_settings']['CONF']:
            raise RuntimeError('Expected existing active input on channel 3')
        learned = inst.query('*LRN?').strip()
        (OUT / 'original-settings.scpi').write_text(learned, encoding='utf-8')
        report['preexisting_errors'] = errors(inst)
        report['termchar_enabled'] = bool(inst.get_visa_attribute(ResourceAttribute.termchar_enabled))
        if report['termchar_enabled']:
            raise RuntimeError('App USB termination policy was not applied')
        print(json.dumps({'connected': identity, 'termchar_enabled': False}), flush=True)
        for repetition in args.repetitions:
            for rate in args.rates:
                modified = True
                print(f'TEST {rate} Hz run {repetition}', flush=True)
                row = run(inst, identity, rate, repetition)
                report['tests'].append(row)
                report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
                print(json.dumps({k: v for k, v in row.items() if k not in ('statuses', 'setup')}), flush=True)
                if not row['integrity_pass']:
                    raise RuntimeError('Data integrity check failed; stopping tests')
    except Exception as exc:
        report['failure'] = repr(exc)
        raise
    finally:
        core.Keysight53230A = original_factory
        try:
            if modified:
                inst.write('ABOR')
                inst.query('*OPC?')
                inst.write(learned)
                inst.query('*OPC?')
                report['restore_errors'] = errors(inst)
                report['restored_settings'] = {q: inst.query(q + '?').strip() for q in QUERIES}
                report['restored_matches_original'] = report['restored_settings'] == report['original_settings']
                report['final_pending_readings'] = int(inst.query('DATA:POIN?'))
                print('RESTORED ' + str(report['restored_matches_original']), flush=True)
        finally:
            report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
            connection.close()


if __name__ == '__main__':
    main()
