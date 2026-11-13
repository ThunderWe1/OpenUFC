"""Hardware rate probe. Uses the existing frequency channel; restores touched settings."""
import argparse
import json
import time
from pathlib import Path

import numpy as np
import pyvisa

OUT = Path(__file__).resolve().parent
RESOURCE = 'USB0::0x0957::0x1907::MY59220164::0::INSTR'


def errors(inst):
    result = []
    for _ in range(20):
        reply = inst.query('SYST:ERR?').strip()
        if int(reply.split(',')[0]) == 0:
            return result
        result.append(reply)
    raise RuntimeError('Error queue did not clear: ' + str(result))


def run(inst, rate, seconds, stream, display, interval):
    count = min(1_000_000, int(rate * seconds))
    row = dict(requested_rate_hz=rate, requested_gate_s=1/rate,
               requested_count=count, streaming=stream, display=display, target_read_interval_s=interval)
    inst.write('ABOR')
    inst.query('*OPC?')
    inst.write('FORM:DATA REAL,64')
    inst.write('FORM:BORD NORM')
    inst.write('SENS:FREQ:MODE CONT')
    inst.write('SENS:FREQ:GATE:SOUR TIME')
    inst.write('TRIG:SOUR IMM')
    inst.write('TRIG:COUN 1')
    inst.write(f'DISP {display}')
    inst.write(f'SAMP:COUN {count}')
    inst.write(f'SENS:FREQ:GATE:TIME {1/rate:.12g}')
    row['accepted_gate_s'] = float(inst.query('SENS:FREQ:GATE:TIME?'))
    row['setup_errors'] = errors(inst)
    if row['setup_errors']:
        return row
    inst.write('*CLS')
    chunks, timings = [], []
    total = 0
    start = time.perf_counter()
    inst.write('INIT')
    if not stream:
        inst.query('*OPC?')
        row['acquisition_wall_s'] = time.perf_counter() - start
        row['buffer_count_before_read'] = int(inst.query('DATA:POIN?'))
    deadline = start + max(20, count * row['accepted_gate_s'] * 3 + 10)
    batch = max(1, int(rate * interval)) if stream else count
    next_read = start + interval
    while total < count:
        if time.perf_counter() > deadline:
            raise TimeoutError(f'Incomplete acquisition: {total}/{count}')
        if stream:
            time.sleep(max(0, next_read-time.perf_counter()))
        before = time.perf_counter()
        values = inst.query_binary_values(f'R? {min(batch,count-total)}', datatype='d',
                                           is_big_endian=True, container=np.asarray)
        after = time.perf_counter()
        timings.append({'start_s': before-start, 'duration_s': after-before, 'count': int(values.size)})
        if values.size:
            chunks.append(values)
            total += values.size
        next_read = max(start + (total + min(batch, count-total))*row['accepted_gate_s'], before + .01)
        if not values.size:
            next_read = after + .05
    row['total_wall_s'] = time.perf_counter()-start
    if stream:
        inst.query('*OPC?')
    row['buffer_count_after_read'] = int(inst.query('DATA:POIN?'))
    row['questionable_event'] = int(inst.query('STAT:QUES:EVEN?'))
    row['errors'] = errors(inst)
    row['final_gate_s'] = float(inst.query('SENS:FREQ:GATE:TIME?'))
    values = np.concatenate(chunks)
    row.update(received_count=int(values.size), valid_count=int(np.sum(np.isfinite(values) & (abs(values)<1e36))),
               mean_frequency_hz=float(np.mean(values)), std_frequency_hz=float(np.std(values)),
               min_frequency_hz=float(np.min(values)), max_frequency_hz=float(np.max(values)),
               usb_transfer_s=sum(t['duration_s'] for t in timings), read_calls=len(timings))
    row['wall_readings_per_s'] = total / row.get('acquisition_wall_s', row['total_wall_s'])
    row['usb_readings_per_s'] = total / row['usb_transfer_s']
    label = f'{rate:g}Hz_{"stream" if stream else "buffer"}_display{display}_{time.time_ns()}'
    np.save(OUT / (label + '.npy'), values)
    (OUT / (label + '-reads.json')).write_text(json.dumps(timings, indent=2), encoding='utf-8')
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--rates', nargs='+', type=float, default=[1000, 2000, 5000, 10000, 20000, 50000, 100000])
    parser.add_argument('--seconds', type=float, default=3)
    parser.add_argument('--stream', action='store_true')
    parser.add_argument('--display', type=int, choices=[0,1], default=1)
    parser.add_argument('--label', default='sweep')
    parser.add_argument('--no-termchar', action='store_true')
    parser.add_argument('--chunk-bytes', type=int, default=20480)
    parser.add_argument('--interval', type=float, default=0.1)
    args = parser.parse_args()
    rm = pyvisa.ResourceManager()
    inst = rm.open_resource(RESOURCE, access_mode=pyvisa.constants.AccessModes.exclusive_lock, open_timeout=2000)
    inst.timeout = 30000
    inst.read_termination = inst.write_termination = '\n'
    inst.chunk_size = args.chunk_bytes
    if args.no_termchar:
        # USBTMC supplies message boundaries. Keep PyVISA's expected trailing
        # newline length, but do not split binary payload on embedded 0x0A bytes.
        inst.set_visa_attribute(pyvisa.constants.ResourceAttribute.termchar_enabled, False)
    restore = {}
    modified = False
    rows = []
    report = {'resource':RESOURCE, 'tests':rows, 'termchar_enabled': not args.no_termchar,
              'chunk_bytes':args.chunk_bytes}
    try:
        report['identity'] = inst.query('*IDN?').strip()
        report['configuration'] = inst.query('CONF?').strip()
        if '53230A' not in report['identity'] or not report['configuration'].startswith('"FREQ '):
            raise RuntimeError('Expected 53230A in frequency mode')
        if int(inst.query('STAT:OPER:COND?')) & 16 or int(inst.query('DATA:POIN?')):
            raise RuntimeError('Counter is measuring or has unread data; refusing to overwrite it')
        for command in ['FORM:DATA','FORM:BORD','SENS:FREQ:MODE','SENS:FREQ:GATE:SOUR',
                        'SENS:FREQ:GATE:TIME','SAMP:COUN','TRIG:SOUR','TRIG:COUN','DISP']:
            restore[command]=inst.query(command+'?').strip()
        report['original_settings'] = restore
        report['preexisting_errors'] = errors(inst)
        for rate in args.rates:
            modified = True
            row = run(inst, rate, args.seconds, args.stream, args.display, args.interval)
            rows.append(row)
            print(json.dumps(row),flush=True)
            (OUT/(args.label+'.json')).write_text(json.dumps(report,indent=2), encoding='utf-8')
            if row.get('valid_count',1) != row.get('received_count',1) or row.get('errors'):
                raise RuntimeError('Invalid readings or instrument errors; stopping sweep')
    except Exception as exc:
        report['failure']=repr(exc)
        raise
    finally:
        try:
            if modified:
                inst.write('ABOR')
                inst.query('*OPC?')
                for command,value in restore.items():
                    inst.write(command+' '+value)
                report['restore_errors']=errors(inst)
                report['restored_settings']={command:inst.query(command+'?').strip() for command in restore}
                print('RESTORED',json.dumps(report['restored_settings']),flush=True)
        finally:
            (OUT/(args.label+'.json')).write_text(json.dumps(report,indent=2), encoding='utf-8')
            inst.close()
            rm.close()


if __name__=='__main__':
    main()
