# IQScope — automatic IQ analysis prototype

Open a recording and run discovery and decoder trials without choosing filters,
decimation, tuning offsets, or modulation. This is an initial offline DSP core,
not yet a universal decoder or an SDR application.

## Run

Python 3.10+, NumPy and SciPy are required.

```bash
git clone https://github.com/sebadiaz/IQScope.git
cd IQScope
python -m pip install .
python iqscope.py demo --out demo
python iqscope.py analyze recording.sigmf-meta --out results
```

For raw little-endian complex float32 files, the sample rate must be supplied
because it cannot be inferred reliably from the bytes:

```bash
python iqscope.py analyze recording.cf32 --sample-rate 2400000 --out results
```

SigMF automatically supplies the sample rate, sample representation and center
frequency. Supported sample types: cf32_le, cf32_be, ci16_le, ci16_be and cu8.
Only single-channel, single-capture files without data offsets are supported.
Analysis defaults to the first 10 seconds; change with `--seconds`.
Input is bounded by duration, not memory size: high sample rates can still require
substantial RAM. The prototype loads the selected samples into memory.

## Results

- `report.json`: detected bands, center frequencies, bandwidths, spectral SNR
  estimates, modulation hypotheses, trial outputs and explicit validation status.
- `spectrum.csv`: frequency versus power spectral density.
- `signal-NNN-fm-candidate.wav`: automatic FM listening trials where the measured
  envelope and instantaneous frequency suggest angle modulation.

FM audio is a candidate interpretation. A successful WAV export does not prove
that the signal is FM broadcast or contains intelligible speech. No result is
currently marked as validated content. Signal strength estimates use a global
spectral noise floor and are approximate.

The deterministic demo contains a carrier at -60 kHz and an FM signal at +45 kHz,
with a known 1 kHz audio tone. These are generated signals, not an Internet capture.

## Verification

GitHub Actions runs the tests and demo on Python 3.10, 3.12 and 3.13 for every push and pull request.

```bash
python -m unittest discover -s tests -v
```

Tests exercise two-signal discovery, recovery of the known audio frequency,
noise rejection, integer SigMF input and missing metadata handling.
Real recordings have not yet been validated. An attempted public GitHub download
failed because the network connection was unavailable in the development runtime.

## Next milestones

1. Validate against public, licensed SigMF recordings with documented contents.
   Source candidates include https://github.com/sigmf and
   https://www.iqengine.org/ (availability and recording licenses require checking).
2. Add time-frequency detection for bursts, adaptive noise estimates and overlapping
   signal hypotheses. Current spectral grouping can merge closely spaced emitters;
   hopping, spread-spectrum and low-SNR signals may be missed.
3. Add Morse and documented FSK protocol decoders, with symbol timing, frame search,
   error correction and CRC evidence. Build a decoder registry and rank competing
   interpretations using validation evidence.
4. Add a local spectrum/waterfall interface and streaming SDR input, reusing the
   file analysis pipeline after introducing block processing.

Unsupported signals remain unknown. Encryption cannot be removed by modulation
recognition. Live scanning, binary protocol recovery, voice codecs and video
reconstruction are not implemented in this release.
