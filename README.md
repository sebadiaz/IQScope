# IQScope

Local radio explorer with a French web interface, offline IQ analysis and an
initial live RTL-SDR adapter. DSP settings are selected automatically for the
implemented decoder trials. This is version 0.5, an early implementation of the
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

- SigMF/raw IQ, stereo WAV IQ and SDRangel `.sdriq` import;
- spectrum and waterfall (sampled time windows for files);
- automatically detected spectral bands and expandable audio candidates;
- validated ADS-B packet bytes and a small set of parsed fields;
- automatic RTTY text candidates, parameters and framing evidence;
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

### SDRangel example recordings

[SDRangel's IQ examples](https://www.sdrangel.org/iq-files/) provide real captures
across 15 signal families/cases. Their WAV IQ files and `.sdriq` files can now be
opened directly: the sample rate is read from the header. WAV must contain two
channels, I followed by Q; a mono audio WAV is rejected. WAV `auxi` center-frequency
metadata is used when present, otherwise frequencies remain relative.

Supported WAV layouts: little-endian RIFF/RF64, PCM 8/16/24/32 and IEEE float
32/64. WAVE_FORMAT_EXTENSIBLE and RIFX are not supported. SDRangel `.sdriq`
requires the 32-byte CRC-checked header and 16-bit or 24-bit samples; its 24-bit
samples are stored in 32-bit signed containers, not packed in three bytes.

Extract ZIPs before using ordinary import. For recordings larger than the web
upload limit, use the CLI to create a complete, bounded SigMF excerpt:

```bash
iqscope convert recording.wav --seconds 3 --out excerpt
```

Upload the resulting `excerpt.sigmf-data` and `excerpt.sigmf-meta`. The converter
also accepts `.sdriq` and existing supported IQ inputs, and refuses to overwrite
an existing output pair.

The [source manifest](corpus/sdrangel.json) records the 15 examples and their
published parameters. This catalog does not mean all 15 protocols are decoded.
A network-dependent smoke test downloads bounded prefixes of the first IQ ZIP
member, rather than fetching hundreds of megabytes per recording:

```bash
python scripts/sdrangel_corpus.py --name adsb --name rtty --name radar
```

The script exports complete local SigMF excerpts and records URLs, member names,
excerpt hashes and measurements under `corpus-cache/`. Normal imports still
reject truncated WAV files; only this explicit excerpt pipeline allows a partial
source WAV. A partial ZIP does not provide whole-archive integrity validation.
No original IQ is committed or uploaded as a CI artifact; redistribution rights
have not been established. External availability and file changes can affect
this separate real-data CI job.

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
| RTTY / ITA2 | Text candidates, raw character codes, automatic common baud rates/tones/polarity | Single IQ source at 1–12 kS/s, 5-bit LSB-first with at least 1.5 stop bits; framing only, no checksum |
| Mode S / ADS-B | 112-bit DF17/DF18 frames, CRC-24, address/type code, selected barometric altitude | Clean captures at >= 2 MS/s; no general Mode S parity overlays, position reconstruction, collision recovery or bit-error correction; pulse timing uses an 8 MS/s energy grid |

The capability registry distinguishes analog interpretations from validated
packet integrity. A CRC does **not** authenticate a transmitter. For DF18, the
address is not automatically labeled as an ICAO identity.

Stationary spectral detection can miss short bursts and merge close emissions.
ADS-B uses a separate envelope packet search over the source, so a packet need
not appear as an isolated stationary band. Decoder effort is bounded by at most
12 audio-band trials, 2,000 ADS-B candidates and 100 recovered packets per window.
Deferred bands and exhausted packet-search budgets are exposed in the report.

LoRa, Morse, military protocols and the other remaining families in the specifications are
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
The first real SDRangel check recovered four CRC-valid packets; see the
[dated validation report](docs/VALIDATION_SDRANGEL.md) for scope and search-budget limits.
A separate SDRangel real-data CI job now checks real imports and requires at least
one CRC-valid ADS-B packet. This is a smoke test, not yet a frozen, fully annotated
regression corpus. RTTY now also requires a framing-consistent text candidate. Radar tests import and analysis only.

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

## Additional research corpus

The [imec/UGent sub-GHz corpus](docs/DATASET_IMEC_SUBGHZ.md) is now cataloged
for future technology-recognition evaluation (LoRa, Sigfox, SUN-FSK/SUN-OFDM,
IEEE 802.11ah and noise). Its identity and authors documentation are verified;
its shared files have not yet been inspected or imported. This is not another
validated decoder dataset. The authors report CC BY-NC-SA 4.0 licensing.

## Dataset catalog and Panoradio HF windows

The interface now includes **Explorer les jeux de données**, a catalog of 17
sources with explicit integration status. It opens source documentation; it does
not download all datasets or imply that their protocols are supported.

```bash
iqscope datasets
iqscope dataset-import panoradio_hf dataset_panoradio_hf.npy --record 0 --out hf-window
iqscope analyze hf-window.sigmf-meta --out hf-results
```

Panoradio uses independent 2,048-sample complex windows at 6 kS/s. The importer
reads the selected row through a memory map, exports one SigMF pair and a
`.provenance.json` file, and refuses to overwrite existing output. It never
concatenates rows or infers the class label from row order. Complex128 source
values are converted to complex64; the original dtype and output hash are kept.
Object arrays, pickle, real-valued feature arrays and incompatible shapes are
rejected. Choosing the dataset preset does not prove a local file's origin.

To test the public first window without downloading the 5+ GB array:

```bash
python scripts/panoradio_smoke.py
```

This bounded network check reads at most 64 KiB from the start, checks the NPY
header, exports one complete independent window and runs analysis. It does not
validate a class prediction, a decoded message, the tags CSV or the full source
file. The exported pair can be opened through the ordinary SigMF UI.

See [dataset catalog and integration scope](docs/DATASET_CATALOG.md). TorchSig,
NIST, GNSS and the other catalog entries still require their own adapters or
validation; they are not silently treated as supported decoder inputs.

## Analog FPV video dataset

[Zenodo 19870020](https://zenodo.org/records/19870020) is now cataloged separately
from drone fingerprinting datasets. It contains analog-video IQ sweeps and
experiment-level TX on/off annotations. The annotation reader preserves unknown
rate/frequency units and does not treat TX-off experiments as pure noise.

```bash
iqscope dataset-annotations fpv_analog iq_recording_meta.csv
python scripts/fpv_metadata_probe.py
```

The network probe reads the CSV and an internal ZIP metadata member using bounded
HTTP ranges; it does not extract IQ or reconstruct video. See the
[FPV dataset integration notes](docs/DATASET_FPV_ANALOG.md).

## RTTY text candidates

The receiver searches 45.45, 50, 75 and 100 baud, tone pairs near common shifts,
and both frequency polarities on a single low-bandwidth complex IQ source.
There is no manual filter, baud-rate or mark/space setting for these trials.
It checks asynchronous start/data/stop timing, recovers 5-bit codes and applies
international ITA2 letters/figures shifts. The initial shift state is assumed
letters until a shift code is observed.

Results appear as **texte candidat, sans CRC** in the UI and as a wideband trial
in the JSON report. The top text is exported as `rtty-candidate.txt`; alternatives
and their timing/framing evidence are kept in JSON. It is not counted as a
CRC-valid packet or authenticated content. Noise and malformed signals should
lead to abstention, but framing alone cannot eliminate all false interpretations.

This initial integration does not search RTTY channels throughout a wideband SDR
stream, handle every national alphabet, or guarantee recovery in fading/collisions.
The bounded analysis covers at most 12 seconds. Existing recorded RTTY at 2 kS/s
is part of the real-data CI test; known text fixtures independently exercise the
character codes, shifts, rates and inversion.
