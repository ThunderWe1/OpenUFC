import html
import json
from pathlib import Path

out = Path(__file__).resolve().parent
files = ['buffered-sweep', 'streaming-sweep', 'binary-usb-buffered', 'binary-usb-streaming',
         'minimum-gate-probe', 'near-limit-streaming', 'display-off-streaming', 'million-reading-validation']
rows = []
for name in files:
    data = json.loads((out / (name + '.json')).read_text())
    assert not data.get('failure') and not data.get('restore_errors'), name
    assert data['restored_settings'] == data['original_settings'], name
    for row in data['tests']:
        assert row['received_count'] == row['requested_count'] == row['valid_count']
        assert row['buffer_count_after_read'] == 0 and row['questionable_event'] == 0 and not row['errors']
        rows.append({'test_group': name, 'termchar_enabled': data.get('termchar_enabled', True), **row})
(out / 'combined-results.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
table = []
for r in rows:
    elapsed = r.get('acquisition_wall_s', r['total_wall_s'])
    cells = [r['test_group'], f"{r['accepted_gate_s'] * 1e6:g}", 'Streaming' if r['streaming'] else 'Buffered',
             'On' if r['display'] else 'Off', f"{r['received_count']:,}", f'{elapsed:.4f}', f"{r['wall_readings_per_s']:,.1f}"]
    table.append('<tr>' + ''.join('<td>' + html.escape(c) + '</td>' for c in cells) + '</tr>')
report = '''<!doctype html><html lang="en"><meta charset="utf-8"><title>53230A USB benchmark - 2026-10-31</title>
<style>body{font:16px/1.5 system-ui;max-width:1200px;margin:40px auto;padding:0 24px;color:#17212b}h1{font-size:28px}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:8px 10px;border-bottom:1px solid #dce1e8;text-align:left}th{background:#edf3fa}.note{padding:16px;background:#f0f6ff;border-left:4px solid #3869a8}</style>
<h1>53230A USB frequency-rate benchmark</h1>
<p>31 October 2026 (Asia/Shanghai). Counter MY59220164, firmware 03.01, option 106; channel 3, continuous frequency mode. Signal readings were approximately 219-237 MHz during testing.</p>
<p class="note"><strong>Practical tested setting: 20 us gate (50 kHz nominal).</strong> Two one-million-reading streamed runs completed in 20.388 s and 20.190 s (49,049 and 49,529 readings/s). All requested readings were recovered; no invalid numeric readings, buffer-overflow events or instrument errors were reported.</p>
<h2>What limits the rate</h2><ul>
<li>The app-style VISA configuration enables newline termination during binary reads. In this USB session, disabling VI_ATTR_TERMCHAR_EN raised bulk retrieval from approximately 51-60 thousand to 559-656 thousand readings/s, with unchanged 20,480-byte VISA chunks. PyVISA still accounts for the trailing newline; USBTMC provides message boundaries.</li>
<li>With that transport adjustment, the 10 us setting delivered one million readings in 14.745 s with the display on (67,819/s), or 14.190 s with it off (70,474/s). It did not sustain 100,000 delivered readings/s.</li>
<li>The instrument accepted and read back a 1 us gate in CONT mode, but 200,000 buffered readings took 2.700 s (74,062/s), followed by USB retrieval. Accepting a gate setting does not establish its physical sampling interval or a 1 MS/s frequency stream.</li>
<li>Nonstandard 16, 15 and 14 us requests showed inconsistent correspondence between reciprocal gate and measured wall-clock throughput. They are not recommended as calibrated sample rates.</li></ul>
<h2>Scope and interpretation</h2>
<p>These are instrument-plus-USB diagnostic tests, not full OpenUFC GUI/disk/ADEV benchmarks. Buffered acquisition time runs from INIT to the return of *OPC?; streamed time runs from INIT to receipt of the last sample. These include startup, instrument processing and, for streaming, USB readout. No external gate timing or per-reading timestamps were measured, so these results do not prove uniform physical sampling at the tabulated wall-clock rate. Input readings varied during the tests.</p>
<p>The current OpenUFC application is unchanged and still caps nominal rates at 1 kHz. Higher-rate operation needs the USB binary-transfer adjustment and rate presets integrated and validated in the application. At 50 kHz the one-million-reading segment lasts nominally 20 seconds, followed by a restart gap.</p>
<p>The <a href="https://www.keysight.com/content/dam/keysight/en/doc/ungate/data-sheets/5990-6283.pdf">Keysight datasheet</a> specifies continuous-mode gates in 10 us steps with a 10 us minimum (page 8), and approximately 75,000 frequency readings/s under its stated speed-test conditions (page 13). Firmware accepting a smaller setting is not a validation of performance outside those documented conditions.</p>
<h2>All runs</h2><p>Buffered rows exclude subsequent transfer from the elapsed-time column; streamed rows include transfer. Raw samples (.npy), individual read timings, configuration snapshots and JSON results are saved beside this report. Baseline groups use newline termination; groups beginning binary-usb and all subsequent groups disable it for the USB session.</p>
<table><thead><tr><th>Test</th><th>Gate (us)</th><th>Readout</th><th>Display</th><th>Samples</th><th>Elapsed (s)</th><th>Readings/elapsed second</th></tr></thead><tbody>'''
report += ''.join(table) + '''</tbody></table>
<h2>Restoration</h2><p>Every test restored all instrument settings it modified. Final queries confirmed channel 3, CONT mode, a 1 ms gate, 1,000,000 samples, display on, idle state, zero pending readings and an empty error queue. The original learn string is saved as original-settings.scpi. No app settings or source code were changed.</p></html>'''
(out / 'report.html').write_text(report, encoding='utf-8')
print('Validated runs:', len(rows))
print('Total readings:', sum(r['received_count'] for r in rows))
print('Report:', out / 'report.html')
