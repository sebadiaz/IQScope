"""Small, explicit decoder registry. Analog trials are never protocol validation."""
from dataclasses import dataclass, asdict
from fractions import Fraction
from pathlib import Path
import math

import numpy as np
from scipy import signal
from scipy.io import wavfile


@dataclass(frozen=True)
class Capability:
    id: str
    family: str
    scope: str
    validation: str


CAPABILITIES = (
    Capability('lora_preamble', 'LoRa-compatible CSS evidence', 'centered BW125/250/500kHz SF7–12 repeated chirps; no packet decoding', 'heuristic evidence only; no sync word, header, CRC or payload'),
    Capability('analog_fm', 'FM', 'mono audio candidate, 75 us de-emphasis', 'unvalidated'),
    Capability('analog_am', 'AM', 'envelope audio candidate, carrier-present AM only', 'unvalidated'),
    Capability('ofdm_cp', 'Cyclic-prefix / OFDM evidence', 'bounded periodic guard correlation; integer useful/guard lengths; no protocol classification or payload', 'heuristic structural evidence only; no CRC'),
    Capability('afsk1200_ax25', 'AFSK1200 / AX.25 UI', 'receiver audio at 1200 baud, 1200/2200-Hz tones; no RF FM frontend', 'CRC-16/X-25 and UI structure; no APRS semantics'),
    Capability('ax25_ui', 'AX.25 UI', 'HDLC/NRZI or NRZ on generic 2-FSK bits; UI addresses/PID/payload; no AFSK/G3RUH frontend', 'CRC-16/X-25 plus UI structure; not sender authenticity'),
    Capability('fsk4_generic', '4-FSK', 'equally spaced stationary tones; automatic baud and symbol ranks; bounded channel search', 'timing only; symbol-to-bit mapping arbitrary, no checksum'),
    Capability('fsk2_generic', '2-FSK', 'stationary channels; direct <=96 kS/s or bounded wideband search <=2.4 MS/s; blind baud and raw bits', 'timing only; protocol unknown, no checksum'),
    Capability('cw_morse', 'CW / Morse', 'A-Z and 0-9; automatic stationary carrier and 5-50 WPM timing; bounded channel search', 'timing only; no checksum'),
    Capability('rtty_ita2', 'RTTY / ITA2', '45.45/50/75/100 baud, blind tones and polarity; bounded stationary wideband channel search', 'framing only; no checksum'),
    Capability('adsb_1090es', 'Mode S / ADS-B', 'DF17/18, 112-bit, direct CRC; >= 2 MS/s', 'CRC-24'),
)


def capabilities():
    return [asdict(item) for item in CAPABILITIES]


def write_audio(audio, fs, out, name):
    if len(audio) < 100:
        return None
    audio = np.asarray(audio, dtype=np.float64)
    audio -= np.mean(audio)
    # Bound rational factors: sample rates can be non-integer after channelization.
    ratio = Fraction(48000 / fs).limit_denominator(4096)
    audio = signal.resample_poly(audio, ratio.numerator, ratio.denominator)
    peak = max(float(np.max(np.abs(audio))), 1e-12)
    wavfile.write(Path(out) / name, 48000, (audio / peak * 30000).astype(np.int16))
    return name


def analog_trials(y, rate, measurements, bandwidth, out, index):
    trials = []
    cv = measurements['envelope_variation']
    deviation = measurements['frequency_deviation_p90_hz']
    if cv < .45 and deviation > 300 and bandwidth > 5000:
        discriminator = np.angle(y[1:] * np.conj(y[:-1])) * rate / (2 * np.pi)
        audio = discriminator - np.mean(discriminator)
        audio = signal.sosfilt(signal.butter(5, min(15000, rate * .4), fs=rate, output='sos'), audio)
        alpha = math.exp(-1 / (rate * 75e-6))
        audio = signal.lfilter([1-alpha], [1, -alpha], audio)
        filename = write_audio(audio, rate, out, f'signal-{index:03d}-fm-candidate.wav')
        if filename:
            trials.append({'decoder': 'analog_fm', 'family': 'FM', 'status': 'unvalidated_candidate',
                           'audio': filename, 'evidence': [], 'parameters': {'deemphasis_us': 75}})
    # An envelope can also be OOK, fading or interference. Preserve this ambiguity.
    if .08 < cv < .85 and bandwidth > 1500:
        audio = np.abs(y).astype(np.float64)
        audio -= np.mean(audio)
        audio = signal.sosfilt(signal.butter(5, min(6000, rate * .4), fs=rate, output='sos'), audio)
        filename = write_audio(audio, rate, out, f'signal-{index:03d}-am-candidate.wav')
        if filename:
            trials.append({'decoder': 'analog_am', 'family': 'AM or envelope-modulated signal',
                           'status': 'unvalidated_candidate', 'audio': filename, 'evidence': []})
    return trials


def mode_s_remainder(frame):
    """Mode S CRC polynomial x^24 + ...; excludes address/parity overlays."""
    value = int.from_bytes(frame, 'big')
    for bit in range(len(frame) * 8 - 1, 23, -1):
        if value & (1 << bit):
            value ^= 0x1FFF409 << (bit - 24)
    return value & 0xFFFFFF


def decode_adsb(x, fs, max_candidates=2000, max_frames=100):
    """Envelope PPM receiver for clean DF17/18 captures. No general Mode S claim.

    Pulse energy is resampled to an 8 MS/s timing grid and integrated over
    half-symbols. There is no collision recovery or bit-error correction. CRC validates a recovered packet, not transmitter authenticity.
    """
    if fs < 2_000_000 or len(x) < fs * .00012:
        return {'decoder': 'adsb_1090es', 'status': 'not_applicable', 'frames': []}
    # Bound memory by processing overlapping chunks; preserve cross-chunk packets.
    frames, seen = [], set()
    candidates_examined = 0
    budget_exhausted = False
    chunk_size = 262144
    overlap = int(math.ceil(fs * .00015))
    timing_rate = 8_000_000
    ratio = Fraction(timing_rate / fs).limit_denominator(4096)
    for start in range(0, len(x), chunk_size):
        block = x[max(0, start-overlap):min(len(x), start+chunk_size+overlap)]
        offset = max(0, start-overlap)
        envelope_power = np.abs(block).astype(np.float64) ** 2
        power = signal.resample_poly(envelope_power, ratio.numerator, ratio.denominator)
        power = np.maximum(power, 0)
        if len(power) < 960:
            continue
        # Four 0.5 us preamble pulses, followed by 112 1 us PPM symbols.
        energy = np.convolve(power, np.ones(4)/4, mode='valid')
        high = np.array([0, 8, 28, 36])
        low = np.array([4,12,16,20,24,32,40,44,48,52,56,60])
        valid_length = len(energy)-956
        highs = sum(energy[k:k+valid_length] for k in high)/4
        lows = sum(energy[k:k+valid_length] for k in low)/12
        floor = max(float(np.median(energy)), 1e-12)
        positions = np.flatnonzero((highs > 3*np.maximum(lows, floor)) & (highs > 6*floor))
        for pos in positions:
            if candidates_examined >= max_candidates or len(frames) >= max_frames:
                budget_exhausted = True
                break
            candidates_examined += 1
            if np.min(energy[pos+high]) < highs[pos] * .35:
                continue
            starts = pos+64+8*np.arange(112)
            bits = energy[starts] > energy[starts+4]
            frame = np.packbits(bits).tobytes()
            df = frame[0] >> 3
            if df not in (17, 18) or mode_s_remainder(frame) != 0:
                continue
            sample = offset + int(round(pos * fs / timing_rate))
            # Same bytes may legitimately recur; deduplicate only overlap copies.
            key = (frame, int(round(sample / max(1, fs * .00001))))
            if key in seen:
                continue
            seen.add(key)
            fields = {'downlink_format': df, 'type_code': frame[4] >> 3,
                      'address_hex': frame[1:4].hex().upper()}
            if df == 17:
                fields['icao_hex'] = fields['address_hex']
            else:
                fields['control_field'] = frame[0] & 7
                fields['address_note'] = 'DF18 address semantics depend on control field'
            tc = fields['type_code']
            if 9 <= tc <= 18:
                altitude = (frame[5] << 4) | (frame[6] >> 4)
                if altitude & 0x10:
                    n = ((altitude & 0xFE0) >> 1) | (altitude & 0xF)
                    fields['barometric_altitude_ft'] = n * 25 - 1000
            frames.append({'hex': frame.hex().upper(), 'sample_start': sample,
                           'time_seconds': sample / fs, 'fields': fields,
                           'validation_scope': 'packet_integrity',
                           'evidence': [{'kind': 'mode_s_crc24', 'result': 'pass'}]})
        if budget_exhausted:
            break
    return {'decoder': 'adsb_1090es', 'family': 'Mode S / ADS-B',
            'status': 'validated_frames' if frames else 'no_valid_frame',
            'frames': frames, 'candidates_examined': candidates_examined,
            'budget_exhausted': budget_exhausted, 'timing_grid_hz': timing_rate}
