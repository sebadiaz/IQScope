# Automatic SITOR-B / CCIR 476 / NAVTEX candidates

IQScope automatically searches complex IQ for stationary 170-Hz FSK tone
pairs at nominal 100 baud. It tests both tone polarities, twenty sampling
phases, seven 7-bit word alignments and both direct/repeated-copy parities.
The bounded search accepts 1 kS/s–2.4 MS/s, at most four channel hypotheses,
forty seconds and eight million input samples. Weak, overlapping, hopping and
adjacent signals can be missed. No FM/audio-input frontend is implemented.

No user decimation or tone/character alignment is needed. File and existing
live-IQ analyses use the same receiver. SITOR-B is slow: a short window may
contain phasing only, a header only, or text without its beginning/end. Use
a longer file window, up to forty seconds for this decoder, to retain a short
complete message. The automatic file scan retains each window separately;
there is no cross-window text assembly. The usual ten-second first window of
the pinned reference does not yet contain its message body.

## What the checks mean

ITU-R M.476 collective mode uses the CCIR 476 constant-ratio alphabet: four
ones among seven elements. Each traffic character has a direct copy and a
repeat five transmitted symbol positions later. At 100 baud, seven elements
take 70 ms. Copy starts are **350 ms** apart; four intervening characters
occupy **280 ms**. Those two intervals must not be confused.

Acquisition requires at least twelve matching traffic pairs, 70% valid
constant-ratio words, 85% agreement among pairs whose two words are valid,
80% of active pairs matching or containing one valid copy, and four distinct
letter codes. Phasing/idle pairs do not satisfy the traffic/diversity tests.
The score uses repetition structure and sample contrast; NAVTEX wording is
not used to fit or repair the demodulation.

- Two valid, identical copies select that code.
- A valid copy can replace an invalid copy, using the protocol repetition.
- Two valid but different copies remain an erasure; neither is preferred.
- Two invalid copies remain an erasure. No bits are flipped or guessed.

The initial letter/figure shift state is unknown. Erasures and observed
phasing invalidate it. Only an observed LTRS/FIGS code restores the state;
space, CR and LF remain readable in either case. Unsupported figure variants
remain explicit tags, and BEL is displayed as `[BEL]` rather than sounded.

These are constant-ratio/repetition checks, **not a checksum or authentication**.
They cannot detect every possible channel error, including matching erroneous
copies. `text_interpretation_complete` means no known gap/unsupported character
inside the framed text, not proof of the transmitted contents.

## NAVTEX framing and exports

NAVTEX requires `ZCZC B1B2B3B4` followed by line separation. B1/B2 are raw
station/subject letters; B3/B4 retain their two decimal digits, including `00`.
A header must start the candidate, follow CR/LF, or follow at least six
observed direct-REP/repeated-ALPHA phasing pairs. This allows a real message
after phasing without turning an arbitrary body substring into a header.
`NNNN` on its own line closes the frame. A new header or window end without
it produces an explicitly incomplete message. Gaps and unknown shifts remain
replacement characters; no missing header, terminator or message is invented.

The UI presents framing and text completeness separately, plus copy agreement,
single-valid-copy and conflict counts. UTF-8 text exports preserve CR/LF and
known gaps. The symbol binary stores **one received 7-bit code value per
octet, high bit zero**, not the original packed RF bitstream. JSON preserves
every received code/contrast, both copies and their indices, the selected
code or null, decisions, shift state, source-relative times, tuning hypotheses
and budgets. File analyses add the original source-window origin.

Spectral sidelobes can yield multiple hypotheses for the same transmission.
Identical candidate texts are labelled by `same_text_as_candidate_index` and
remain visible; counts are not emitter counts. SITOR/NAVTEX never increases
the CRC counter or enters the CRC-rechecked event catalogue. No ARQ/SITOR-A,
selective-call procedure, full M.625 application suite or station identity
verification is implemented.

## Validation

The independent transmitter fixture in `tests/test_sitor.py` specifies emitted
B/Y patterns from ITU-R M.476 Table 1, interleaves copies with an independent
delay buffer and generates continuous-phase FSK. Tests cover the complete
alphabet, repetition spacing, sample rates, translation, inversion, clock
offsets, both one-copy erasure recoveries, valid-copy conflict rejection,
unknown shift state, incomplete framing, wrong repetition/baud, noise and
work/export budgets. Automatic API and Chromium tests cover text, symbol
bytes, explicit completeness and the unchanged zero CRC counter.

`python scripts/navtex_reference.py` downloads the bounded SDRangel recording
whose filename labels it `navtex_2023-02-21T16_40_30_201.wav`. Its WAV header is
**1953 samples/s**, correcting the previous IQScope catalog value of 1935;
the original I/Q sample values are retained. No RF center is supplied by this
WAV. Forty seconds yield a framed `ZCZC EA39` message with `NNNN`, including
the received text about Nash Point Light. The script pins source SHA-256,
message text, copy choices, exports, source timing and a lossless forty-second
SigMF conversion. `--offline` reuses the pinned local source. CI imports that
conversion through the same browser flow. Original IQ is not redistributed.

This is a development regression against original IQ, not an independently
published message/error oracle. The archive does not establish present-day
navigation conditions, an authenticated station or a verified capture date.
No SDR hardware has been tested.

Primary references:

- [ITU-R M.476-5, Tables 1/2 and collective B mode](https://www.itu.int/dms_pubrec/itu-r/rec/m/R-REC-M.476-5-199510-I!!PDF-E.pdf).
- [IMO Revised NAVTEX Manual, including ITU-R M.540 framing, published by MPA Singapore](https://www.mpa.gov.sg/api/media/1876f2fa-6896-4721-8761-224251900c62/-sc_no_15_of_2011.pdf).
- [SDRangel IQ sources](https://www.sdrangel.org/iq-files/).
