# IQScope

Local radio explorer with a French web interface, offline IQ analysis and an
initial live RTL-SDR adapter. DSP settings are selected automatically for the
implemented decoder trials. This is version 0.2, an early implementation of the
[broader technical plan](docs/SPECIFICATIONS_TECHNIQUES.md).

## Start the interface

Python 3.10+ is required. Linux is the initial target platform.

```bash
git clone https://github.com/sebadiaz/IQScope.git
cd IQScope
python -m venv .venv
source .venv/bin/activate
python -m pip install .
iqscope serve
```

Open **http://127.0.0.1:8765** in a browser. Use `iqscope serve --port 9000` to
choose another local port. The server deliberately listens on loopback only.

The interface includes:

- IQ data import, plus an optional matching SigMF metadata file;
- spectrum and waterfall (sampled time windows for files);
- automatically detected spectral bands and expandable audio candidates;
- validated ADS-B packet bytes and a small set of parsed fields;
- live spectrum updates from a local `rtl_tcp` server;
- JSON report download and a built-in synthetic FM/carrier demonstration.

There is no dependency on a hosted website or cloud service.

## Recorded IQ files

In the **Fichier IQ** tab, select `.sigmf-data` and its `.sigmf-meta`. SigMF
supplies the sample rate, format and center frequency. For raw `.cf32`, enter
the sample rate; the assumed representation is little-endian complex float32.
Raw files without RF metadata use relative frequencies.

Supported SigMF types: `cf32_le`, `cf32_be`, `ci16_le`, `ci16_be`, `cu8`.
Only single-channel, single-capture, zero-offset metadata is currently supported.

The web import limit is **128 MiB per file**, eight uploads and 256 MiB total per
server session. An analysis reads at most **8 million complex samples** from the
start, and may therefore cover less than the requested duration. Data is loaded
into memory within that bound; this is not yet a full streaming file pipeline.

The last 32 analysis jobs are retained, then older completed jobs are removed.
Uploaded sources and derived files are temporary and removed on normal server
shutdown. Download results before closing the server; there is no durable catalog.

## Live RTL-SDR

Install the RTL-SDR utilities and drivers appropriate for your operating system,
connect your receiver and start a receive-only TCP source on the same machine:

```bash
rtl_tcp -a 127.0.0.1 -p 1234
```

In **SDR en direct**, choose the RF center frequency, source sample rate and TCP
port, then connect. Tuning and sample rate are acquisition settings; modulation,
filters and decimation do not need to be configured. The adapter requests
automatic tuner gain. Hardware frequency coverage depends on the receiver.

Live rates offered: 256 kS/s, 1.024, 2.048 and 2.4 MS/s. For ADS-B, select
**1090 MHz** with at least **2 MS/s**, using a suitable receiver and antenna.

The spectrum is polled approximately four times per second while decoding runs
on independent snapshots of the latest approximately one second, approximately
every four seconds when enabled. CPU speed can reduce the cadence. This is a
live analysis preview, **not guaranteed lossless continuous packet decoding**.
There can be gaps between analyzed windows. The UI waterfall also represents
sampled windows, not every received sample.

`rtl_tcp` does not supply hardware sample timestamps, overflow counters or tuning
readback. Received sample counts cannot prove that no upstream data was lost.
Frequency and rate in this first adapter are requested settings. There is no
frequency scanning, recording button, SoapySDR adapter or other SDR support yet.

The rtl_tcp wire contract is tested with simulated data. A physical receiver has
not been tested in this development environment.

## Implemented decoder scope

| Decoder | Result | Limits |
|---|---|---|
| FM | Mono WAV candidate, 75 microsecond de-emphasis | Heuristic selection; no broadcast identification, stereo, RDS or speech validation |
| AM | Envelope-demodulated WAV candidate | Carrier-present AM only; OOK/fading can also produce candidates |
| Mode S / ADS-B | 112-bit DF17/DF18 frames, CRC-24, address/type code, selected barometric altitude | Clean captures at >= 2 MS/s; no general Mode S parity overlays, position reconstruction, collision recovery or fractional phase search |

The capability registry distinguishes analog interpretations from validated
packet integrity. A CRC does **not** authenticate a transmitter. For DF18, the
address is not automatically labeled as an ICAO identity.

Stationary spectral detection can miss short bursts and merge close emissions.
ADS-B uses a separate envelope packet search over the source, so a packet need
not appear as an isolated stationary band. Decoder effort is bounded by at most
12 audio-band trials, 2,000 ADS-B candidates and 100 recovered packets per window.
Deferred bands and exhausted packet-search budgets are exposed in the report.

LoRa, Morse, military protocols and the other families in the specifications are
**planned, not implemented**. The current registry is a small explicit list;
a general third-party plugin loader and search engine remain future work.

## Command-line analysis

```bash
iqscope demo --out demo
iqscope analyze recording.sigmf-meta --out results
iqscope analyze recording.cf32 --sample-rate 2400000 --seconds 10 --out results
iqscope decoders
```

Outputs: `report.json` (schema 0.2), `spectrum.csv` and candidate WAV files.
The report includes spectrum, sampled waterfall, band measurements, decoder
trials, recovered packet bytes, checks and limitations. Existing schema 0.1
consumers must account for the new wideband trials and fields.

The demo IQ is generated locally; it is not an Internet recording. ADS-B tests
use a widely published example frame `8D40621D58C382D690C8AC2863A7`, independently
encoded as a test waveform. It decodes to address `40621D` and altitude 38,000 ft.
That validates the implemented test conditions, not arbitrary off-air reception.
Real-recording regression coverage remains to be added.

## Tests and CI

```bash
python -m pip install '.[test]'
python -m unittest discover -s tests -v
```

Tests cover analog tone recovery, packet reference and CRC rejection, resampling,
noise, chunk boundaries, repeated packets, search budgets, SigMF/raw import,
HTTP jobs and artifacts, and simulated rtl_tcp input. HTTP tests run through an
in-process ASGI transport without opening network sockets.

GitHub Actions installs the package, runs the tests and CLI demo on Python 3.10,
3.12 and 3.13. A separate browser job launches Chromium, exercises the demo and
file upload, checks the mobile layout and saves desktop/mobile screenshots and failure evidence.
Browser tests require `pip install playwright` and `playwright install chromium`.

The local development sandbox blocks HTTP socket binding and Chromium startup;
local API verification therefore uses ASGI. Browser and physical SDR verification
must be distinguished from the in-process tests in release reports.

## Further work

- Block-based input and multi-resolution burst detection.
- Broader decoders and bounded competing hypotheses.
- Real public IQ corpus with provenance, licensing and expected outputs.
- Loss-aware streaming decoder state, scanning and more SDR adapters.
- Persistent results, cancellation and richer signal selection.

See [technical specifications](docs/SPECIFICATIONS_TECHNIQUES.md) and
[community-reversed and unusual protocols](docs/PROTOCOLES_NON_DOCUMENTES.md).
