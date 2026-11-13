"""Summarize the saved hardware validation without contacting the counter."""
from collections import defaultdict
from html import escape
import json
from pathlib import Path

out = Path(__file__).resolve().parent
report = json.loads((out / 'results.json').read_text(encoding='utf-8'))
groups = defaultdict(list)
for test in report['tests']:
    groups[test['nominal_rate_hz']].append(test)
rows = []
for rate, tests in sorted(groups.items()):
    speeds = [t['effective_readings_per_s'] for t in tests]
    gates = sorted({s['gate_s'] for t in tests for s in t['setup']})
    read_calls = [r for t in tests for r in json.loads(
        (out / f'{rate}Hz-run{t["repetition"]}-reads.json').read_text(encoding='utf-8'))]
    max_read_s = max(r['end'] - r['start'] for r in read_calls)
    rows.append(f'<tr><td>{rate:,}</td><td>{", ".join(f"{g * 1e6:g}" for g in gates)}</td>'
                f'<td>{min(speeds):,.0f}–{max(speeds):,.0f}</td>'
                f'<td>{sum(t["saved_samples"] for t in tests):,}</td>'
                f'<td>{sum(t["restart_count"] for t in tests)}</td><td>{max_read_s:.3f} s</td>'
                f'<td>{"Pass" if all(t["integrity_pass"] for t in tests) else "FAIL"}</td></tr>')
total = sum(t['saved_samples'] for t in report['tests'])
wall = sum(t['acquisition_wall_s'] for t in report['tests'])
html = f'''<!doctype html><html lang="en"><meta charset="utf-8">
<title>OpenUFC USB rate validation — 31 October 2026</title>
<style>body{{max-width:1050px;margin:48px auto;padding:0 24px;font:16px/1.6 system-ui;color:#18232c}}
table{{border-collapse:collapse;width:100%}}th,td{{padding:10px;border-bottom:1px solid #ccd4da;text-align:right}}
th:first-child,td:first-child{{text-align:left}}h1{{line-height:1.2}}code{{overflow-wrap:anywhere}}</style>
<h1>OpenUFC USB rate validation</h1><p>31 October 2026 · {escape(report['identity'])}</p>
<p>{len(report['tests'])} acquisitions, {wall:.1f} seconds total, {total:,} readings saved.</p>
<table><thead><tr><th>Requested readings/s</th><th>Gate readback (µs)</th>
<th>Delivered readings/s</th><th>Total readings</th><th>Restarts</th><th>Longest read call</th><th>Integrity</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
<h2>What was tested</h2><p>Two approximately 35-second runs at each requested rate, using the
connected 53230A on channel 3. Tests used the real OpenUFC acquisition worker,
normal million-reading segments and one-second nominal read batches, background disk
recording, live and final Allan-deviation calculation, and frontend event JSON serialization.
The instrument display remained in its existing state. Driver newline detection was
confirmed disabled by reading the VISA attribute.</p>
<p>Delivered rate is all received readings divided by the interval from the first INIT
return to the stop/drain request. It includes restart downtime; small command/timing
uncertainty remains. Gate readback is the requested instrument setting, not a measurement
of physical sample spacing. The source signal was live and not independently stabilized.</p>
<h2>Integrity checks</h2><p>Received arrays and saved file payloads were compared by SHA-256.
Every saved reading was checked for finite, positive, non-sentinel values. Stop/drain
completion, zero remaining readings, instrument error queues and questionable-event
status were checked. Full restart segments are marked in each .lmp file.</p>
<h2>Limits</h2><p>Passing data integrity does not establish a stable delivery cadence.
The 100 kHz and 500 kHz settings showed read stalls of up to 11 and 22 seconds, respectively. The second
500 kHz run also had a read timeout: some acquired readings may have been lost even
though all successfully received arrays were saved correctly. These are short-duration USB tests, not a long-term stability or measurement
accuracy certification. GUI rendering and LAN hardware were not included in these timing
runs. Separate Electron smoke tests exercise all rate choices and a 500,000-reading display
batch. Waveform, PSD and ADEV time scales still use the nominal selected rate; the 100 kHz
and 500 kHz presets must not be treated as verified timing. The
<a href="https://www.keysight.com/us/en/assets/7018-02642/data-sheets/5990-6283.pdf">Keysight datasheet</a>
specifies a 10 µs minimum continuous gate and up to 75,000 frequency readings/s.</p>
<p>Original instrument configuration restored and queried values matched:
<strong>{escape(str(report.get('restored_matches_original')))}</strong>.
Restoration errors: {escape(str(report.get('restore_errors')))}.</p>
<p><a href="results.json">Detailed results</a> · <a href="recordings/">Raw .lmp recordings</a> ·
<a href="validate_hardware.py">Validation script</a></p></html>'''
(out / 'report.html').write_text(html, encoding='utf-8')
print(f'{len(report["tests"])} tests, {total:,} readings; report.html written')
