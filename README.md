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
| CW / Morse | Automatic carrier, speed and A–Z / 0–9 text candidates | Stationary on-off keying, 5–50 WPM, standard spacing; timing only, no checksum |
| RTTY / ITA2 | Text candidates, raw character codes, automatic common baud rates/tones/polarity | Direct IQ at 1–12 kS/s or bounded stationary-channel search up to 2.4 MS/s, 5-bit LSB-first with at least 1.5 stop bits; framing only, no checksum |
| Mode S / ADS-B | 112-bit DF17/DF18 frames, CRC-24, address/type code, selected barometric altitude | Clean captures at >= 2 MS/s; no general Mode S parity overlays, position reconstruction, collision recovery or bit-error correction; pulse timing uses an 8 MS/s energy grid |

The capability registry distinguishes analog interpretations from validated
packet integrity. A CRC does **not** authenticate a transmitter. For DF18, the
address is not automatically labeled as an ICAO identity.

Stationary spectral detection can miss short bursts and merge close emissions.
ADS-B uses a separate envelope packet search over the source, so a packet need
not appear as an isolated stationary band. Decoder effort is bounded by at most
12 audio-band trials, 2,000 ADS-B candidates and 100 recovered packets per window.
Deferred bands and exhausted packet-search budgets are exposed in the report.

LoRa, military protocols and the other remaining families in the specifications are
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
and both frequency polarities. Low-bandwidth IQ is decoded directly; wider IQ
(up to 2.4 MS/s) is searched for stationary tone pairs, mixed and filtered
automatically to narrowband channels.
There is no manual filter, baud-rate or mark/space setting for these trials.
It checks asynchronous start/data/stop timing, recovers 5-bit codes and applies
international ITA2 letters/figures shifts. The initial shift state is assumed
letters until a shift code is observed.

Results appear as **texte candidat, sans CRC** in the UI and as a wideband trial
in the JSON report. The top text is exported as `rtty-candidate.txt`; alternatives
and their timing/framing evidence are kept in JSON. It is not counted as a
CRC-valid packet or authenticated content. Noise and malformed signals should
lead to abstention, but framing alone cannot eliminate all false interpretations.

The wideband search examines at most 96 strong spectral peaks and eight separated
channel centers. The report records examined channels and deferred centers; this
is not an exhaustive search. Overlapping channels, bursts, hopping, national
alphabets and fading/collisions remain limitations.
The bounded analysis covers at most 12 seconds. Existing recorded RTTY at 2 kS/s
is part of the real-data CI test; known text fixtures independently exercise the
character codes, shifts, rates and inversion. A two-channel synthetic fixture
includes a stronger unrelated carrier. The real SDRangel excerpt is also
resampled and frequency-translated in CI to exercise the wideband chain; this
is a transformed recording, not an independent wideband RF capture.


## CW / Morse text candidates

IQScope searches up to six stationary carrier peaks, filters each channel and
fits dot/dash and spacing durations automatically (5–50 words/minute). Supported
characters are A–Z and 0–9 with standard 1/3/7-unit spacing. Both narrowband IQ
and bounded wideband input up to 2.4 MS/s are supported. The report records the
frequency, estimated speed, raw Morse groups and timing error; the UI displays
candidate text and `cw-candidate.txt` exports the top result.

This is timing evidence, not a checksum or authenticated content. Noise and
continuous carriers are tested for abstention. Short or truncated messages,
manual timing, Farnsworth spacing, fading, overlapping signals, hopping and
punctuation/prosigns may fail. At most the first 20 seconds are searched; source
imports or live snapshots can be shorter. Search budgets are included in JSON.
Validation currently uses independently specified synthetic Morse references
at several speeds and a wideband interferer fixture. The UDXF FDC receiver-audio
excerpt also yields unverified CW candidates; see the audio validation notes.


## Generic 2-FSK candidate bits

A first generic binary-FSK receiver estimates two frequency levels and symbol
rate without a supplied baud rate. It supports a **single stationary complex IQ
channel at 1–96 kS/s**, 20 baud to sample_rate/8 (capped at 9600). IQScope
also searches wider IQ up to 2.4 MS/s using the shared stationary spectral
detector. At most eight detected bands of width <=24 kHz are mixed, filtered and
resampled automatically. Per-channel sample rate limits the baud range. Weak,
merged, overlapping or hopping signals can be missed; the search is not exhaustive.

The report contains candidate bits, tone frequencies, clock residual and the
first recovered symbol's timestamp. `fsk-bits.txt` exports ASCII 0/1;
`fsk-packed.bin` packs the same bits MSB-first, with zero padding in the final
byte. The report records the exact bit count and padding. Byte alignment is
arbitrary and **high tone = 1 is only a convention**; inverse polarity is equally
possible. No framing, CRC, protocol or payload interpretation is inferred.

Analysis is limited to 12 seconds and 100000 output bits. Clock fitting uses at
most the first 512 inter-transition intervals, followed by a whole-window timing
check. Integer rate aliases remain possible for repetitive data. GFSK, MSK,
GMSK, M-FSK, bursts, collisions and clock drift are outside this first scope.
Synthetic references check bit-exact recovery at 50/137/300/1200 baud, fractional
sample alignment, both polarities and abstention on noise/carrier/4-FSK. A two-channel wideband reference includes a stronger unmodulated interferer,
checks bit-exact recovery, absolute frequencies and separate exports. A real
recorded generic-FSK corpus has not yet been validated.


When several generic-FSK candidates are recovered, each has its own `channel`
and `artifacts` entries. The first export keeps `fsk-bits.txt` / `fsk-packed.bin`;
subsequent candidates use `fsk-2-bits.txt`, `fsk-2-packed.bin`, etc. Tone frequencies
are offsets from the original IQ center, and symbol timestamps include channel
filter trimming. The UI displays frequency and separate downloads for each
candidate, plus examined/deferred/excluded channel counts for band searches.


## Generic 4-FSK candidate symbols

The first 4-FSK receiver fits four equally spaced stationary frequency levels
and a common symbol clock automatically. It accepts a single IQ channel at
1–96 kS/s or uses the bounded wideband spectral-band search up to 2.4 MS/s.
Rate limits remain 20 baud to channel_rate/8 (capped at 9600). All four tones
must be sufficiently represented; shaped FSK, clock drift, bursts, collisions
and unknown spacing patterns are outside this first scope.

Symbols **0,1,2,3 are only ranks in ascending frequency order**. The true protocol
mapping may be Gray-coded, reversed or another permutation. `fsk4-symbols.txt`
is the primary export. `fsk4-bits.txt` and `fsk4-packed.bin` use an explicitly
arbitrary natural-binary convention 00/01/10/11, MSB-first with zero padding;
JSON records the symbol/bit counts and padding. This does not establish framing,
CRC, protocol identity or payload meaning. Initial/final partial symbols are
omitted, and repetitive data can leave symbol-rate aliases unresolved.

Search budgets are eight spectral bands, twelve seconds and 100000 convention
bits (50000 symbols). Fitting uses at most 512 inter-transition intervals with
a subsequent whole-window timing check. Each wideband candidate retains its
frequency, timing origin and separate exports. Validation uses independent
synthetic symbol sequences at 50/137/300/1200 baud, two simultaneous wideband
channels and a stronger carrier. Real recorded 4-FSK has not yet been validated.


## AX.25 UI frames from recovered 2-FSK bits

A bounded HDLC receiver now tries NRZI (independent of tone polarity), direct
NRZ and inverted NRZ on each generic 2-FSK candidate. It locates flags, removes
bit stuffing, checks the CRC-16/X-25 FCS (little-endian on air), and validates
AX.25 UI address/control fields. Only accepted frames enter the CRC packet
counter. The UI and JSON expose source/destination callsigns and SSIDs, path,
PID, payload hex, line coding, channel and timestamp. PID 0xf0 also gets a safe
UTF-8 text interpretation; it does not imply valid APRS content.

Scope: UI frames only, two to ten address fields, up to 256 information octets.
Search budgets are 128 accepted frames and 2000 flag pairs across all candidate
streams. FCS failures are rejected without bit correction. A valid FCS and
address structure do not authenticate a sender. Truncated frames, upstream
clock/rate errors and inter-window gaps can cause missed packets.

**This does not yet implement a RF FM discriminator for AFSK1200, G3RUH
scrambling/descrambling, connected-mode AX.25, KISS output or APRS field parsing.**
The initial end-to-end tests use synthetic continuous direct-2-FSK recordings,
NRZI with both polarities, independent FCS generation, stuffed payloads,
corrupted FCS, truncation, random bits and bounded search. No over-air AX.25
recording has yet been validated. Existing real-IQ CI remains a regression check
for the previously supported recordings.

The AX.25 synthetic IQ checks exercise direct 1200-baud NRZI and a translated
300-baud wideband channel. The shared detector can merge sidelobes into bands
wider than the 24-kHz generic-FSK eligibility limit, including for some low-baud
signals; those bands are reported as excluded. This remains a coverage limit,
not evidence that AX.25 is absent.


## UDXF receiver-audio references

[UDXF Collection 4](https://www.udxf.nl/uc4.html) is cataloged separately as
**receiver audio**, not RF IQ. Selected MP3 links and unverified source labels
are in `corpus/udxf_uc4.json`; see [the inspection notes](docs/DATASET_UDXF_UC4.md).
The optional probe needs `ffmpeg` on PATH:

```bash
python scripts/udxf_audio_probe.py
```

It downloads bounded prefixes and decodes at most 20 seconds per entry, then
tries the existing CW receiver on analytic audio. It stores provenance and any
unverified text candidates, never claims the analytic audio is original IQ, and
supports the same bounded decoder as the explicit receiver-audio mode in the UI. CI uploads reports
only. No new military protocol decoder is implied by this catalog addition.

First real-audio probe: three MP3 excerpts decoded successfully. The FDC excerpt
produced CW candidates containing `DE FDC FDC FDC AR` around 24 WPM; initial
characters differ between hypotheses and remain uncertain. VTK and Link-11
excerpts produced no consistent CW candidate. See the linked inspection notes
for the verified CI run and hashes. This is candidate recovery without a checksum
or independent transcript, not validated military protocol decoding.


## MP3 / WAV receiver audio in the UI

Install `ffmpeg` on PATH, run `iqscope serve`, and select **Audio de récepteur**
in the File panel. Choose MP3 or WAV and 1–20 seconds. The server mixes to mono,
resamples to 8 kHz, and runs **CW timing, RTTY/ITA2 framing, and AFSK1200 AX.25 UI trials**. Results include audio
playback, an audio-frequency spectrum/waterfall, candidate Morse/RTTY text and JSON.
There is no RF center frequency, RF-band discovery, speech recognition or new
military-protocol support in this mode. IQ mode still rejects MP3 and mono WAV.

API: submit an upload with `input_kind: "audio"` and no SigMF sidecar. Reports
use `source_kind: "receiver_audio"`, `frequency_reference: "audio_hz"`, null
`center_frequency_hz` and `audio_frequency_hz` fields for candidate channels. The first requested
seconds are bounded; the total source duration is not measured. Missing ffmpeg
returns an actionable error. Browser CI covers MP3 upload, CW text, audio
playback artifact and audio/RF labeling; the real UDXF probe exercises the same
importer separately from original-RF-IQ validation.


RTTY audio trials automatically search common shifts, 45.45/50/75/100 baud and
both polarities. They inspect at most the first 12 seconds even when 20 seconds
of audio are imported; the report/UI expose this shorter decoder budget. ITA2
letters/figures and raw codes remain available, and `rtty-candidate.txt` exports
the top text without converting CR/LF. Frequencies refer to the audio, not RF;
tone polarity can be reversed by receiver sideband settings. There is no CRC,
independently verified transcript or automatic protocol identity guarantee.

Tests cover receiver-audio WAV in both polarities, letters/figures, MP3 browser
upload, text download and the per-decoder duration limit. CI also attempts a
frequency-translated, real-valued audio version of the SDRangel RTTY IQ excerpt;
that is a transformed recording, not a separate off-air audio acquisition.


## VKSDR IQ WAV recordings

[VKSDR](https://vksdr.com/iq/) provides five IQ WAV references selected in
`corpus/vksdr.json`. The bounded probe downloads at most 2 MiB per recording,
reads at most one second, exports a complete SigMF excerpt and checks its exact
round-trip before analysis. It retains header RF metadata separately from
filename hints; filenames alone are not promoted to verified center frequencies.

```bash
python scripts/vksdr_corpus.py
python scripts/vksdr_corpus.py --name uhf_fo
```

See [the VKSDR notes](docs/DATASET_VKSDR.md). This checks import and existing
analysis; it adds no NOAA PDS, LRIT image extraction or military payload decoder.
CI uploads reports only. Source recordings remain outside Git and CI artifacts.


VKSDR is also available from **Explorer les jeux de données** in the UI. Each
of the five recording cards offers a bounded import-and-analyze button. Opening
the catalog uses packaged metadata only; clicking a recording downloads at most
2 MiB on the server and analyzes at most one second. The result offers complete
SigMF data/metadata and provenance downloads. It never substitutes filename RF
hints for unknown header metadata or claims that the advertised protocol decoded.
Only fixed recording IDs and the HTTPS VKSDR bucket are accepted, including
redirects. Download errors appear as failed jobs. This uses the same importer
as the real-corpus CI probe; no full WAV download or remote arbitrary URL input
is provided.


## AFSK1200 audio to AX.25 UI

Receiver-audio mode now also tests 1200-baud AFSK with nominal 1200/2200-Hz tones.
A noncoherent two-tone receiver tries 32 fixed sampling phases, then reuses HDLC,
NRZI/NRZ, bit-unstuffing, CRC-16/X-25 and AX.25 UI structure checks. Only accepted
frames enter the CRC counter. Phase copies of the same frame at the same time
are deduplicated; repeated transmissions at distinct times are retained.

The UI displays callsigns/SSIDs, path, PID and payload, with frequencies labeled
as audio. `ax25-frames.json` exports accepted frames. PID 0xf0 text is decoded
as safe UTF-8, without interpreting APRS positions, telemetry or other fields.
A valid CRC does not authenticate an emitter. No RF FM discriminator, G3RUH,
connected-mode AX.25, speech transcription or general AFSK classifier is added.

Limits: first 20 seconds, 32 phases, 6000 total flag-pair attempts and 128 unique
frames. There is no frequency or clock tracking. Tests use synthetic NRZI audio
with both tone polarities, fractional timing, 8/44.1-kHz input, corrupted FCS,
noise, unkeyed tone and phase deduplication. WAV and a 24-kHz/64-kbit/s MP3 fixture
exercise import, UI and export. Aggressively compressed MP3 can destroy valid
packets; WAV is preferable for protocol validation. No real over-air AFSK1200
capture has yet been validated.


The browser releases its temporary upload after a completed or failed analysis;
job results and exported artifacts remain available. API clients can use
`DELETE /api/uploads/{id}` when no analysis is active. The eight-upload quota
remains in force for retained source uploads; sequential browser analyses no
longer accumulate those sources. SDRangel corpus downloads explicitly request
the ZIP beginning and identity encoding, and retry a failed prefix parse once.
Each attempt keeps the original byte/parser limits and pinned excerpt hashes.


CI reuses the already imported and pinned SDRangel RTTY excerpt for its derived
audio check (`python scripts/rtty_audio_smoke.py --reuse-source-root corpus-cache`)
instead of downloading the same ZIP again in the independent UDXF job.


## imec real LTE / Wi-Fi / DVB-T corpus

The share `qrJCWgzQaGPfHPr` is identified by its authors' repository as a distinct
real over-air technology-recognition corpus, separate from the existing sub-GHz
share. Its documented default rate is 1 MS/s unless filenames state otherwise.
The public MATLAB example reads interleaved signed int16, I then Q, but leaves
endianness implicit. A bounded prefix has since been inspected; conversion candidates are available
but no physical-layout validation or content decoder is claimed. See [the source and metadata-probe notes](docs/DATASET_IMEC_LTE_WIFI_DVBT.md).
The catalog keeps the declared CC BY-NC-SA 4.0 license and potential RadioPile
overlap explicit. The public-share probe now accepts a validated share token and
supports the modern public DAV endpoint/header as well as the legacy route.


The local candidate converter is now available:

```bash
iqscope dataset-import imec_lte_wifi_dvbt recording.bin --out excerpt
```

It reads at most 256 KiB and exports both `ci16_le` and `ci16_be` SigMF
interpretations with identical source bytes. Neither endian is selected as
correct. Rate conventions and unknown original header layout remain explicit;
filename RF hints are not promoted to verified capture frequencies. The normal
analyzer and UI preserve this uncertainty from the generated metadata. The CI
prefix probe explores at most three public directories in one known location,
downloads one bounded prefix and checks byte-exact conversion for both variants.
This does not establish an independently verified physical format or decode LTE,
Wi-Fi or DVB-T payloads.


First real-prefix observation: 256 KiB from
`wf10Msps_g30_rabot_f5240MHz_r1.bin`, 65,536 candidate complex samples at the
filename-indicated 10 MS/s (6.5536 ms). Both byte-order interpretations round-trip
exactly; physical layout and byte order remain unresolved. The catalog reports
candidate conversion, not verified RF format or Wi-Fi recognition. See the
imec notes for the checked run, source URL, size and hash.


## Cyclic-prefix repetition evidence

IQ analysis now tests a bounded model of periodic guard repetition compatible
with OFDM. It averages complex lag products by candidate symbol phase, compares
the guard interval with its background, checks both halves of the observation,
and excludes spectrally concentrated tones. It estimates useful/guard lengths
and nominal durations; **it does not identify Wi-Fi, LTE or DVB-T, recover FFT
bins or bits, verify CRCs, or interpret payloads**. Other block waveforms with
repeated guards can give the same evidence.

Search limits: at most 262144 complex samples in total, distributed across up to three non-overlapping windows of at most 131072
samples, useful lengths 16–2048 in powers of two, guards 1/4, 1/8, 1/16 or 1/32
(minimum two samples), and at least 32 symbols per trial. Short bursts, overlapping
channels, clock drift, noninteger resampling, other guards and channel offsets
can be missed. The detector searches the input directly without channelization.
Timing in seconds depends on the supplied sample rate; filename-derived rates
and unverified byte-order hypotheses remain unverified.

Results appear in the UI as structural candidates and in `ofdm-candidates.json`.
They do not increment the CRC packet counter. Synthetic tests exercise several
length/guard pairs, arbitrary acquisition offset, CFO, noise and multipath, plus
abstention on noise, colored noise, a carrier and binary FSK. The imec prefix
probe records the candidates separately for each endian without selecting one.


## Iraq RF handcrafted feature tables

[Mendeley v2zmysy94r v1](https://data.mendeley.com/datasets/v2zmysy94r/1) is cataloged
as **derived feature tables**, not raw IQ. Its published metadata describes
24.8 million feature-window rows, 84 columns and 297 source recordings; the
large compressed feature tables are not downloaded by the probe. The dataset
license is CC BY 4.0. See [the source notes](docs/DATASET_IRAQ_RF_FEATURES.md)
for the small supporting files and related raw-IQ lineage. No waveform importer,
radio decoder or prediction model is added for these CSV features.

### LoRa-compatible preamble evidence

Automatic centered-channel CSS preamble search is available for BW125/250/500 kHz
and SF7–12, with both chirp directions. Candidate parameters and repeated-chirp
evidence appear in the UI and JSON. A conventional sync-word hypothesis may be reported after opposite chirps.
A matching final quarter chirp enables at most 64 raw CSS symbol candidates,
with explicit stop reasons; these values are not bytes.
A candidate explicit header reports its announced length, coding rate and CRC
flag after a five-bit check. Explicit CR4/5 SF7–10 payloads can be decoded,
dewhitened and checked against the LoRa PHY CRC16. CRC-valid bytes appear in the
UI and binary export; other outputs remain candidates. Validation currently uses
synthetic transmitter vectors, not known over-the-air packets. No LoRaWAN parsing,
decryption or sender authentication is performed.
See [scope, budgets and validation](docs/LORA_PREAMBLE.md).
