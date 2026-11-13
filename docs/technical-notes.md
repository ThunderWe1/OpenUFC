# OpenUFC 技术说明

本文件是 OpenUFC 的实现与仪器记录（英文原文），涵盖频率计的停止/排空时序、`.lmp` 记录格式与分段边界、采样率预设与实测吞吐，以及 DMM / OPM / WLM 的命令细节和验证结果。README 只保留面向用户的概览。

## Universal Frequency Counter Notes

The lower analysis plot has **ADEV** and **FN** tabs, with each tab's settings
below its plot. ADEV normalization and wavelength settings apply to the next
acquisition. FN uses a one-sided Welch power spectral density in Hz²/Hz from
the latest 65,536 recorded frequency samples at most, using the recording's
sample rate. Segment length, window (Hann, Hamming, or rectangular), and overlap
(0%, 50%, or 75%) can be changed during or after acquisition. Each segment's
mean is removed, DC is omitted, and windows never span acquisition gaps.
The plot waits for a complete segment rather than padding insufficient data.
Independent X and Y switches select logarithmic or linear axes; zero noise
values are visible on linear Y. Analysis choices are saved per instrument.

Universal Frequency Counter supports the 53220A and 53230A; the 53220A has been tested with the current app. It configures continuous frequency mode and normally drains reading memory once per second with `R? <sample_rate_hz>` instead of repeated `READ?` polling. Channels 1 and 2 use a fixed 10 MHz expected frequency; channel 3 uses 100 MHz. Frequency readings are converted to fractional values as:

```text
y = frequency_hz / optical_frequency_hz / sqrt(2)
```

Each acquisition streams into one `.lmp` file in the shared Library folder. The Library view previews waveform/ADEV data and exports plotted series to CSV on demand.
Refresh also finds recordings copied into that folder manually, including `.LMP`
files. The folder icon beside Refresh opens the configured folder in Explorer.
Files that cannot be read produce a visible warning instead of disappearing silently.

Stopping a counter recording finishes any in-flight VISA read, snapshots the
buffered reading count with `DATA:POIN?`, then sends `ABOR` and waits for `*OPC?`
on the acquisition thread. Binary `R?` transfers empty the buffer, but only the
pre-abort count is saved, including its final partial batch, before closing the
file and calculating final ADEV. This prevents an abnormal final reading that
the connected 53230A sometimes appends during abort. Readings appended after the
snapshot fall outside the recording's stop cutoff and are discarded; a delay
after `*OPC?` did not reliably prevent the bad final reading. It does not
issue `INIT`, `READ?`, or reconfigure the counter while draining. The normal
read timeout is 10 seconds; the drain has a 30-second budget with individual
VISA timeouts constrained by the remaining budget. Backend shutdown allows
recordings to finish draining before exiting.

If a transfer, stop confirmation, or drain fails, the file retains all readings
successfully saved and the final status reports that stop/buffer recovery could
not be fully confirmed. Recording metadata contains `stop_drain.complete`,
`stop_drain.saved_samples` (readings saved during the drain),
`stop_drain.discarded_after_stop` (readings beyond the pre-abort cutoff), and
`stop_drain.error`. A failed final in-flight binary read is treated as incomplete
recovery because `R?` is destructive and the reply stream may be out of sync.

The stop/drain sequence follows the Keysight 53220A/53230A Programmer's Reference:
[ABORt (p. 18)](https://www.easymanua.ls/keysight/53230a/manual/249540?p=18),
[R? (p. 26)](https://www.easymanua.ls/keysight/53230a/manual/249540?p=26), and
[DATA:POINts? (p. 161)](https://www.easymanua.ls/keysight/53230a/manual/249540?p=161).
These are copies of the manufacturer's reference hosted by EasyManua.ls.

Counter read deadlines now follow the segment's start time and retrieved sample
count, so each binary transfer's duration is not added to the next wait. Readout
catches up when behind; short replies have a 10 ms minimum spacing and empty
replies back off for 250 ms. Normal restarts retrieve every sample, including a
partial final batch, then send only `INIT`. The initial configuration is reused.
An empty buffer does not trigger a nominal-time restart while the counter still
reports active measurement.
Recovery after stalled/failed reads stops and drains recoverable readings before
reconfiguring. An unconfirmed recovery drain or failed restart ends the run with
an error rather than silently clearing unread data.

File writes, metadata flushes and data-event publication run on a separate writer
thread with a bounded 32-batch queue. Normal restarts can proceed while those
writes finish. If disk throughput cannot keep up, the queue applies backpressure;
it does not silently discard readings. Stop still drains the counter and waits
for queued writes to finish before final ADEV and the completion message.

Recordings store `ufc_segment_starts` (zero-based sample offsets), starting with
`[0]` when the file is created. Live and
Library waveforms break the line at these boundaries. Live, final and exported
ADEV only use blocks and adjacent block pairs within a segment. Potential lost
data following a failed destructive read also starts a new segment. Waveform
CSV exports add a zero-based `segment_index` column when boundaries are present.
The waveform time axis and CSV `time_s` remain nominal sample time; they do not
measure the physical restart gap. Readers validate the LMP version, sample
layout, measurement settings, and any recorded segment boundaries. Earlier LMP1
counter files without boundary metadata are supported without rewriting them.
Their plots and analysis use one continuous segment, with a warning that the
original boundaries are unknown. Missing measurement rates and invalid recorded
boundaries are still rejected.

The documented maximum
[sample count is 1,000,000 per trigger (p. 317)](https://www.easymanua.ls/keysight/53230a/manual/249540?p=317).
In [continuous gap-free frequency mode (p. 329)](https://www.easymanua.ls/keysight/53230a/manual/249540?p=329),
the counter accepts only one trigger per `INIT` and ignores `TRIG:COUN`;
increasing trigger count therefore cannot extend a gap-free run. `SAMP:COUN INF`
is not documented. At 1 kHz this limits each documented gap-free segment to
1,000 seconds (16 minutes 40 seconds). These optimizations reduce software delay;
they do not make `INIT` boundaries gap-free. Actual restart gaps and model/channel
behavior still require hardware validation.

For the existing rate presets, the rate-dependent instrument command is
`SENS:FREQ:GATE:TIME` with gate time `1 / sample_rate_hz`. The app automatically
changes the requested read batch size, scheduling and waveform/ADEV nominal time
scale with the selected rate:

| Nominal rate | Gate time | Normal read batch | Nominal million-sample segment |
| --- | --- | --- | --- |
| 1 Hz | 1 s | 1 | 1,000,000 s |
| 10 Hz | 100 ms | 10 | 100,000 s |
| 100 Hz | 10 ms | 100 | 10,000 s |
| 1,000 Hz | 1 ms | 1,000 | 1,000 s |
| 5,000 Hz | 200 µs | 5,000 | 200 s |
| 10,000 Hz | 100 µs | 10,000 | 100 s |
| 50,000 Hz | 20 µs | 50,000 | 20 s |

`SAMP:COUN` remains 1,000,000, `TRIG:SOUR IMM`, `TRIG:COUN 1`,
`SENS:FREQ:MODE CONT`, the time-based gate source and binary float64 transfer
format stay the same. Expected frequency depends on channel, not sample rate.
No additional manual parameter changes are needed for these presets. Presets are
nominal gate requests, not guarantees of delivered sample rate. The highest
supported preset is 50 kHz; unsupported acquisition rates are rejected.
Waveform, spectrum, and ADEV time
scales still use the selected nominal rate, so they are not calibrated time scales
when the instrument cannot sustain it. Other counter models need separate validation.

All app VISA connections (counter, DMM, and identification) disable driver-level
newline detection for USB INSTR and LAN TCPIP INSTR resources, which provide
message boundaries. Command newlines and PyVISA's trailing-newline handling remain
enabled. Raw TCP sockets, USB RAW, and serial retain their previous behavior.

USB validation on 2026-10-31 used the connected 53230A, channel 3, with real disk
recording, live ADEV and event serialization. Each preset was tested twice for
approximately 35–41 seconds, including million-reading restarts at the higher rates:

| Selected rate | Observed delivered readings/s | Result |
| --- | --- | --- |
| 5 kHz | 4,926–4,988 | Both runs clean |
| 10 kHz | 10,015–10,083 | Both runs clean |
| 50 kHz | 49,084–49,515 | Both runs clean, including restarts |

50 kHz is the highest tested preset recommended for this setup.
These are short USB tests, not long-term stability or verified sample
spacing; LAN hardware and GUI rendering were not part of the throughput measurements.
The live input frequency changed during testing. Detailed results and raw recordings
are in [the validation report](../artifacts/visa-rate-validation-20261031/report.html).
Raw `.lmp` recordings from those runs are not published in this repository.

## Digital Multimeter Notes

Digital Multimeter supports Keysight/Agilent 34410A, 34411A, 34460A,
34461A, 34465A, and 34470A meters. Support uses explicit model capability
profiles rather than assuming compatibility with arbitrary SCPI multimeters;
the legacy 34401A is not supported.

Available measurement functions are `VOLT:DC`, `VOLT:AC`, `CURR:DC`,
`CURR:AC`, and `RES`. Sessions stream elapsed time and values into the same
`.lmp` library format as the counter.

DMM acquisitions use the instrument's timed continuous sampling and drain
completed readings from its reading memory in roughly one-second batches. Stop
requests abort the sampler and drain all completed readings before finalizing
the recording.

DMM connection settings use one `resource` string: a full USB/LAN VISA address
or a host/IP, expanded to `TCPIP0::<host>::inst0::INSTR` by the backend.
Recordings store the resolved address and flat measurement settings.

Current modes show an in-app lead-placement warning before acquisition.
Manual ranges are checked against the connected model. The 10 A range is
available only on the 34461A, 34465A, and 34470A and selects their dedicated
10 A terminal.
Digital Multimeter and Optical Power Meter connection timeouts are fixed internally at the 5000 ms default.

## Optical Power Meter Notes

OpenUFC does not bundle or launch the Thorlabs installer. Install Thorlabs
Optical Power Monitor/TLPMX separately from the
[official OPM download page](https://www.thorlabs.com/software-pages/OPM), then
use the installed Driver Switcher to bind the meter to TLPMX before reconnecting
it. See the [OPM 7.0 manual](https://www.thorlabs.com/images/tabimages/TL_OPM_V7.0.pdf)
for vendor installation and driver-selection guidance.

After installation, OpenUFC checks `TLPMX_DLL_PATH`, the standard IVI and
Thorlabs Optical Power Monitor directories, and then the normal Windows DLL
search path. Copying `TLPMX_64.dll` alone is not sufficient because the Windows
USB driver and machine-level driver binding are installed separately.

Optical Power Meter sessions currently use channel 1. Channel is fixed
internally and is intentionally not shown as an editable control. Sessions store
elapsed time plus `power_w` values in watts. W, mW, and dBm are display choices
only; statistics and absolute ADEV remain based on watts. Non-positive samples
cannot be represented in dBm and display as unavailable.

## Wavelength Meter Notes

Wavelength Meter supports [Bristol 671](https://www.bristol-inst.com/bristol-instruments-products/wavelength-meters-scientific/671-series-cw-lasers/)
and [Bristol 771](https://www.bristol-inst.com/bristol-instruments-products/spectrum-analyzers/771-series-laser-spectrum-analyzer/)
instruments through Telnet-SCPI. USB mode uses the meter's RNDIS virtual
Ethernet endpoint fixed at `10.199.199.1:23`. Ethernet mode accepts a hostname
or IP address, `host:port`, or `telnet://host:port` and remembers that endpoint
when switching modes. Opening the instrument page does not contact the meter;
use the connection-check icon beside the endpoint to run a bounded probe.
OpenUFC selects the 771 scalar wavelength query after identifying a 771 model,
while retaining the 671 command path. It talks directly to the instrument
protocol using the [telnetlib3 blocking API](https://telnetlib3.readthedocs.io/en/master/api/sync.html),
so Bristol NuView and a native Bristol runtime are not required.

The available polling presets are 0.5, 1, 2.5, 4, and 10 Hz, although actual
throughput remains limited by the meter response time. Sessions store elapsed
time and raw `wavelength_nm` float64 values. Display, statistics, and absolute
ADEV all use nanometres; CSV exports label wavelength and ADEV columns
`wavelength_nm` and `adev_nm`. Wavelength Meter has no channel setting.
