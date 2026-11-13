"""Exercise the actual acquisition worker, recording and final buffer drain."""
import json
import queue
import time
import urllib.request
from pathlib import Path

import numpy as np
import pyvisa

from laser_platform.library import PAYLOAD_OFFSET, read_metadata
from laser_platform.ufc.core import AcquisitionWorker, ErrorMessage, config_from_payload
from laser_platform.visa_transport import configure_visa_termination

out = Path(__file__).resolve().parent / 'app-validation'
out.mkdir(exist_ok=True)
resource = 'USB0::0x0957::0x1907::MY59220164::0::INSTR'
rm = pyvisa.ResourceManager()


def connect():
    inst = rm.open_resource(resource, access_mode=pyvisa.constants.AccessModes.exclusive_lock, open_timeout=2000)
    inst.timeout = 5000
    configure_visa_termination(inst)
    return inst


inst = connect()
try:
    assert not int(inst.query('STAT:OPER:COND?')) & 16 and int(inst.query('DATA:POIN?')) == 0
    configuration = inst.query('CONF?').strip()
    commands = ['FORM:DATA', 'FORM:BORD', 'SENS:FREQ:MODE', 'SENS:FREQ:GATE:SOUR',
                'SENS:FREQ:GATE:TIME', 'SAMP:COUN', 'TRIG:SOUR', 'TRIG:COUN']
    restore = {c: inst.query(c + '?').strip() for c in commands}
finally:
    inst.close()

report = {'original': restore, 'runs': []}
try:
    for index, delay in enumerate([.7, 1.17, 1.43, 2.13, .83, 1.67, 2.27, 1.91]):
        with urllib.request.urlopen('http://127.0.0.1:51974/api/instruments', timeout=2) as response:
            assert not any(i['running'] for i in json.load(response)['instruments']), 'User acquisition is running'
        messages = queue.Queue()
        worker = AcquisitionWorker(config_from_payload({
            'resource': resource, 'channel': 3, 'sample_rate_hz': 50000,
            'library_dir': str(out), 'display_name': f'Stop timing validation {index + 1}',
        }), messages)
        worker.start()
        try:
            time.sleep(delay)
        finally:
            stopped = time.perf_counter()
            worker.stop()
            worker.thread.join(timeout=35)
        assert not worker.thread.is_alive(), 'Worker failed to stop'
        errors = [m.text for m in list(messages.queue) if isinstance(m, ErrorMessage)]
        assert not errors, errors
        path = max(out.glob('*.lmp'), key=lambda p: p.stat().st_mtime)
        metadata = read_metadata(path)
        values = np.fromfile(path, dtype='<f8', offset=PAYLOAD_OFFSET)
        assert values.size > 2 and metadata['sample_count'] == values.size
        assert metadata['stop_drain']['complete'], metadata['stop_drain']
        median = float(np.median(values))
        assert np.all(np.isfinite(values)) and median < 1e36
        assert np.min(values) > median * .1, 'Abnormal low reading remains'
        row = dict(file=path.name, requested_stop_s=delay, stop_wall_s=time.perf_counter()-stopped,
                   count=int(values.size), tail=values[-3:].tolist(), median_hz=median,
                   minimum_hz=float(np.min(values)), stop_drain=metadata['stop_drain'])
        report['runs'].append(row)
        print(json.dumps(row), flush=True)
finally:
    inst = connect()
    try:
        inst.write('ABOR')
        inst.query('*OPC?')
        for c, v in restore.items():
            inst.write(c + ' ' + v)
        report['restored'] = {c: inst.query(c + '?').strip() for c in restore}
        report['configuration_restored'] = inst.query('CONF?').strip() == configuration
        report['restore_error'] = inst.query('SYST:ERR?').strip()
        report['remaining_readings'] = int(inst.query('DATA:POIN?'))
    finally:
        (out / 'results.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        inst.close()
        rm.close()
