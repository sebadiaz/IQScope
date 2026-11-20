# NOAA APT image recovery

IQScope automatically tries NOAA APT on complex IQ at 48 kS/s–2.4 MS/s. No
manual decimation, FM deviation or image line alignment is required. File,
file-scan window and existing live-IQ analyses use the same trial. A window
needs at least three consecutive complete lines (usually more than two seconds
of input); live updates with shorter buffers cannot produce an image.

The receiver mixes up to two stationary spectral/baseband channel hypotheses,
filters the FM channel, discriminates phase, retains 400–4500 Hz audio without
de-emphasis, and recovers the 2400-Hz AM subcarrier envelope. Centered filters
and rational resampling yield 8320 envelope samples/s. A normalized correlation
search looks for the two different 39-word A/B sync patterns, 1040 words apart.
Adjacent A syncs must be 0.495–0.505 seconds apart, A correlations at least 0.65
and B correlation at least 0.60 within four words of the predicted midpoint.
At least three adjacent full lines must meet all conditions. Only the longest
contiguous run per trial channel is exported, with no fabricated missing lines.

Each observed line is independently interpolated to 2080 words. The full line
layout per 1040-word half is 39 sync + 47 space + 909 image + 45 telemetry.
Channel A image columns are `[86,995)`, B `[1126,2035)`, zero-based half-open.
Pixels retain reception order; no geographic orientation is inferred.

The trial has a hard limit of twenty seconds, eight million input samples,
two channels and forty output lines per image. Spectral bands are prioritized;
a baseband fallback uses a remaining channel slot. Weak, overlapping or
incorrectly bounded detections may be missed. No Doppler tracking, telemetry interpretation,
channel identification, full-pass assembly or cross-window image stitching is
implemented. Results are partial strips, not an entire satellite pass.

## Outputs and UI

The UI shows channels A/B and downloads the full-line PNG, channel PNGs, numeric
CSV and row-major uint8 binary. Previews are stretched vertically and labelled
accordingly; the files preserve their original dimensions. The full-line PNG
retains space, sync and telemetry columns. CSV has one row per image line and
2080 integer columns. PNG, binary, CSV and `pixels_u8_hex` encode identical
display pixels. These are not transmitted digital bytes.

One contrast mapping uses the 1st/99th envelope percentiles across the selected
full lines; values are rounded/clipped to 0–255. `apt-images.json` records the
mapping, pixel order, per-line timing, A/B correlations, measured clock error,
channel tuning and processing budgets. File analyses add the original source
window origin. Intensities are **not calibrated radiances, temperatures or
exact original ADC words**. No geolocation or satellite identity is inferred.

APT is analog and has no packet CRC. Its image candidates do not increase the
CRC counter or enter the CRC-checked event catalogue. Periodic A/B sync is
structural evidence, not proof of picture contents or transmitter identity.

## Validation

`tests/test_apt.py` builds independent FM/AM transmitter fixtures from the
documented pulse positions. Checks cover recovered image structure, sample
rates, clock offsets, translation, I/Q inversion, work limits, rejected noise,
tones, unrelated FM, missing B sync, incorrect line period and too-short runs.
PNG chunks/CRCs are independently read in tests and their pixels compared to
the binary, CSV and cropped images. PNG container CRCs do not validate RF data.
The web API test uses the automatic full pipeline; Chromium checks actual
image loading, numeric downloads and the unchanged zero CRC count.

`python scripts/apt_reference.py` downloads a bounded, SHA-256 pinned 16 MiB
prefix of SDRangel's `apt.zip`, a historical recording labelled NOAA 18 by its
publisher. Ten seconds at 62.5 kS/s yield 19 consecutive dual-sync lines and two
909-column image strips. The complete original-IQ pipeline checks this result,
numeric tile profiles, timings and CSV/binary equality. The source is exported
losslessly to a complete ten-second SigMF recording for the browser import.
`--offline` reuses the pinned local prefix. Original recordings are not committed
or redistributed. The recording publisher supplies no independently decoded
reference image; this is a development regression, not an external pixel oracle
or authenticated satellite identification. The CI browser job runs the same
recording and checks that both PNG previews load.

Primary format references:

- [NOAA KLM User's Guide, section 4.2.3 and synchronization figure](https://www.ncei.noaa.gov/pub/data/cdo/documentation/podguides/N-15%20thru%20N-19/pdf/0.0%20NOAA%20KLM%20Users%20Guide.pdf).
- [NOAA receiving-station guide](https://noaasis.noaa.gov/NOAASIS/pubs/Users_Guide-Building_Receive_Stations_March_2009.pdf).
- [SDRangel historical NOAA 18 IQ example](https://www.sdrangel.org/iq-files/).
- [Independent transmitter pulse positions, apt-encoder](https://github.com/tom2238/apt-encoder/blob/28f2b9b2464957d5e70a01ac04c85390bf80329e/aptcode/aptcode.c).

The NOAA APT spacecraft retired in 2025. This receiver supports historical
recordings and generated signals; it does not claim current NOAA APT service.
