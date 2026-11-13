"""Compare interrupted and naturally completed frequency acquisitions."""
import argparse
import json
import time
from pathlib import Path

import numpy as np
import pyvisa

from laser_platform.visa_transport import configure_visa_termination

parser = argparse.ArgumentParser()
parser.add_argument('--settle', type=float, default=0)
parser.add_argument('--label', default='probe')
parser.add_argument('--snapshot', action='store_true')
args = parser.parse_args()
out = Path(__file__).resolve().parent
rm = pyvisa.ResourceManager()
inst = rm.open_resource('USB0::0x0957::0x1907::MY59220164::0::INSTR',
                        access_mode=pyvisa.constants.AccessModes.exclusive_lock, open_timeout=2000)
restore = {}
report = {"settle_s": args.settle, "runs": []}
modified = False
try:
    inst.timeout = 5000
    configure_visa_termination(inst)
    report['identity'] = inst.query('*IDN?').strip()
    if '53230A' not in report['identity'] or not inst.query('CONF?').startswith('"FREQ '):
        raise RuntimeError('Expected 53230A in frequency mode')
    if int(inst.query('STAT:OPER:COND?')) & 16 or int(inst.query('DATA:POIN?')):
        raise RuntimeError('Counter is measuring or has unread data')
    commands = ['FORM:DATA', 'FORM:BORD', 'SENS:FREQ:GATE:TIME', 'SAMP:COUN']
    restore = {c: inst.query(c + '?').strip() for c in commands}
    report['original'] = restore
    for index, (natural, rate, delay) in enumerate([
        (False, 50000, 1.12), (False, 50000, 1.23), (False, 50000, 1.36),
        (False, 50000, 1.49), (False, 50000, 1.62), (False, 50000, 1.75),
        (True, 50000, .1), (True, 50000, .1), (True, 50000, .1),
        (False, 1000, 1.23), (False, 1000, 1.49), (False, 1000, 1.75),
    ]):
        modified = True
        inst.write('FORM:DATA REAL,64')
        inst.write('FORM:BORD NORM')
        inst.write(f'SENS:FREQ:GATE:TIME {1/rate:.12g}')
        inst.write(f'SAMP:COUN {int(rate*delay) if natural else 1000000}')
        inst.write('INIT')
        if natural:
            assert inst.query('*OPC?').strip() in ('1', '+1')
        else:
            time.sleep(delay)
        before = int(inst.query('STAT:OPER:COND?'))
        completed_before_abort = int(inst.query('DATA:POIN?')) if args.snapshot else None
        inst.write('ABOR')
        assert inst.query('*OPC?').strip() in ('1', '+1')
        if args.settle:
            time.sleep(args.settle)
        available = int(inst.query('DATA:POIN?'))
        chunks = []
        while (count := int(inst.query('DATA:POIN?'))):
            chunks.append(inst.query_binary_values(f'R? {min(count, 10000)}', datatype='d',
                                                   is_big_endian=True, container=np.asarray))
        if not chunks:
            raise RuntimeError(f'No readings: {index=}, {before=}, {available=}, error={inst.query("SYST:ERR?")}')
        values = np.concatenate(chunks)
        np.save(out / f'{args.label}-{index:02d}.npy', values)
        row = dict(natural=natural, rate=rate, delay=delay, was_measuring=bool(before & 16),
                   count=available, received=int(values.size),
                   tail=values[-4:].tolist(), median=float(np.median(values)),
                   minimum=float(np.min(values)), min_before_last=float(np.min(values[:-1])) if values.size > 1 else None,
                   error=inst.query('SYST:ERR?').strip())
        if args.snapshot:
            saved = values[:completed_before_abort]
            row.update(completed_before_abort=completed_before_abort, saved_tail=saved[-4:].tolist(),
                       saved_minimum=float(np.min(saved)), discarded_count=int(values.size)-completed_before_abort)
            assert len(saved) == completed_before_abort and np.min(saved) > np.median(saved) * .1
        report['runs'].append(row)
        print(json.dumps(row), flush=True)
        if int(row['error'].split(',')[0]) or not np.all(np.isfinite(values) & (np.abs(values) < 1e36)):
            raise RuntimeError('Invalid input or instrument error; stopping probe')
finally:
    try:
        if modified:
            inst.write('ABOR')
            inst.query('*OPC?')
            for c, v in restore.items():
                inst.write(c + ' ' + v)
            report['restored'] = {c: inst.query(c + '?').strip() for c in restore}
            report['restore_error'] = inst.query('SYST:ERR?').strip()
    finally:
        (out / f'{args.label}.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        inst.close()
        rm.close()
