# Automatic RDS from broadcast FM IQ

The main IQ pipeline automatically tries RDS at 192 kS/s–4 MS/s. No manual
decimation, pilot phase, biphase alignment or checkword settings are required.
Two stationary spectral channels at most are selected by signal strength;
a remaining slot can try baseband. The time/sample budget is ten seconds or
eight million input samples, whichever comes first. At 4 MS/s this is two
seconds. Other detected stations remain outside the RDS channel budget.

Each trial mixes and filters the FM RF channel, discriminates frequency without
de-emphasis, mixes the multiplex at 57 kHz and retains the RDS baseband. Blind
squared-BPSK carrier estimation covers ±50 Hz of residual subcarrier error,
without requiring a stereo pilot. The 19 kS/s baseband is matched against the
nominal 1187.5-bit/s biphase pulse, sampled at 32 phases and differentially
decoded. This is a fixed nominal clock search, not an adaptive carrier/clock
PLL. Strong interference, clock drift and weak or overlapped stations can fail.

## Integrity and output

A group comprises four received 26-bit blocks: 16 information bits and 10
check bits each. All four must pass the shortened cyclic code with generator
`0x5B9` and the A/B/C-or-C-prime/D offset words. The C/C-prime choice follows
the version bit in block B. Acquisition requires at least two adjacent complete
valid groups in the same sampled stream; isolated groups are discarded.
There is no bit repair, burst-error correction or incomplete-block promotion.
CRC does not authenticate a PI, station or text.

At most 128 groups are retained per trial. Each group exports its exact **13
received bytes**, packing the 104 bits MSB first, including the four offset
checkwords. A separate eight-byte export concatenates the four big-endian
16-bit information words, without their checks. `rds-groups.json` preserves
both representations, fields, channel/timing hypotheses, budgets, per-group
source times and file-window origin. A CRC catalogue event rechecks these
received bits rather than trusting the JSON interpretation.

The UI CRC counter counts groups, one observation per four-block group. The
RDS section shows declared PI, numeric PTY and TP, plus names and RadioText.
Group bytes remain downloadable under the expandable group list. The file
scan catalogue can filter RDS events and export their exact 104 received bits.
Its time/channel matching is heuristic: two nominal bit periods and 5 kHz,
anchored to the first observation. It is not a unique physical packet count.

## Partial text assembly

Only the common header, group 0A/0B Programme Service (PS) and group 2A/2B
RadioText applications are interpreted. Other group bodies remain raw words.
PS uses four two-character segments. RadioText uses 16 four-character segments
in version A or 16 two-character segments in B. Completion requires every
position before a received CR terminator, or the complete fixed-width field.
Missing positions are explicit nulls in JSON and middle dots in the UI. No
missing characters are guessed or copied from another window/station.

Assembly is scoped by declared PI and trial channel. A conflicting segment
resets the affected field; RadioText A/B or version changes also reset its
state. This conservative rule can yield partial text on dynamic PS or abusive
broadcasters. Text is a basic Latin subset of the RDS character repertoire;
unsupported and control codes stay explicit `\xNN` escapes with raw bytes.
Country/region-specific PTY names, alternate-frequency retuning, clock-time,
traffic applications, ODA, EON and RDS2 streams are not interpreted. No station
state or complete radio programme is reconstructed across windows.

## Evidence

`tests/test_rds.py` uses independently specified FM/biphase/differential
transmitter fixtures and bit-list polynomial encoding. It checks the numerical
examples in NRSC-4-A Annex B and published Redsea YLE X3M information words:
PI `6204`, PS `YLE X3M ` and PTY 9. Additional checks cover frequency/clock
offsets, sample rates, translation, conjugation, reception without pilot,
rejection of damaged/isolated groups and unrelated signals, partial/conflicting
text, version B, work limits, received exports and catalogue CRC rechecks.
The automatic API and Chromium tests cover import, text, bytes and catalogue.

`python scripts/rds_reference.py` fetches a SHA-256 pinned 32 MiB prefix of
SDRangel's `bfm.zip`. The first eight million samples at 4 MS/s contain several
FM stations. The two automatically selected channels yield 20 checked groups
each: declared PI `C478`, PS `  LBC   `, and PI `C201`, PS `Radio 1 `.
RadioText is incomplete for both. The check exercises the entire original-IQ
pipeline and verifies received group bytes, fields, PS, JSON provenance and a
lossless complete two-second SigMF conversion for browser import. `--offline`
reuses the local prefix. Original IQ files are not committed or redistributed.

The group lists are development regression data. The publisher provides no
independently annotated group total, group/text oracle or authenticated station
identity. Published field vectors check parsing independently; they are not an
independent demodulation of this RF capture. No SDR hardware has been tested.

References:

- [NRSC-4 specification](https://www.nrscstandards.org/standards-and-guidelines/documents/archive/nrsc-4-2004.pdf).
- [NRSC-4-A Annexes A/B/C: offsets, coding and synchronization](https://www.nrscstandards.org/standards-and-guidelines/documents/archive/nrsc-4-a-annexes-2005.pdf).
- [Published Redsea field vectors, pinned revision](https://github.com/windytan/redsea/blob/b16943e17f6b954c87a70a35307691fc1bf5b735/test/components-hex.cc).
- [SDRangel IQ recordings](https://www.sdrangel.org/iq-files/).
