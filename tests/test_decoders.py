"""Independent packet reference, analog signal recovery and receiver negatives."""
import tempfile
import unittest
from pathlib import Path

import numpy as np
from scipy import signal
from scipy.io import wavfile

from iqscope import analyze_samples
from iqscope_decoders import decode_adsb, mode_s_remainder

# Widely published Mode S airborne-position example (mode-s.org).
REFERENCE = bytes.fromhex('8D40621D58C382D690C8AC2863A7')


def reference_iq(frame=REFERENCE, count=20000, start=1000):
    """Test PPM waveform, deliberately independent from receiver implementation."""
    x = np.full(count, .001, dtype=np.complex64)
    for position in (0, 2, 7, 9):
        x[start+position] = 1
    bits = ''.join(f'{byte:08b}' for byte in frame)
    for i, bit in enumerate(bits):
        x[start+16+2*i+(bit == '0')] = 1
    return x


class DecoderTests(unittest.TestCase):
    def test_reference_crc_and_fields(self):
        self.assertEqual(mode_s_remainder(REFERENCE), 0)
        result = decode_adsb(reference_iq(), 2_000_000)
        self.assertEqual(len(result['frames']), 1)
        frame = result['frames'][0]
        self.assertEqual(frame['hex'], REFERENCE.hex().upper())
        self.assertEqual(frame['sample_start'], 1000)
        self.assertEqual(frame['fields']['icao_hex'], '40621D')
        self.assertEqual(frame['fields']['barometric_altitude_ft'], 38000)

    def test_resampling_frequency_offset_and_noise(self):
        x = signal.resample_poly(reference_iq(), 6, 5)
        rng = np.random.default_rng(7)
        x *= np.exp(2j*np.pi*125000*np.arange(len(x))/2_400_000)
        x += .004*(rng.normal(size=len(x))+1j*rng.normal(size=len(x)))
        frame = decode_adsb(x, 2_400_000)['frames'][0]
        self.assertEqual(frame['hex'], REFERENCE.hex().upper())
        self.assertAlmostEqual(frame['time_seconds'], .0005, places=5)

    def test_corrupted_payload_rejected(self):
        frame = bytearray(REFERENCE)
        frame[8] ^= 4
        self.assertNotEqual(mode_s_remainder(frame), 0)
        self.assertEqual(decode_adsb(reference_iq(frame), 2_000_000)['frames'], [])

    def test_noise_and_analog_do_not_validate(self):
        rng = np.random.default_rng(42)
        x = rng.normal(size=100000)+1j*rng.normal(size=100000)
        self.assertEqual(decode_adsb(x, 2_000_000)['frames'], [])
        t = np.arange(20000)/2_000_000
        fm = np.exp(1j*5*np.sin(2*np.pi*1000*t))
        self.assertEqual(decode_adsb(fm, 2_000_000)['frames'], [])

    def test_truncated_packet_and_low_rate(self):
        self.assertEqual(decode_adsb(reference_iq()[:1100], 2_000_000)['frames'], [])
        self.assertEqual(decode_adsb(reference_iq(), 1_024_000)['status'], 'not_applicable')

    def test_chunk_boundary_is_not_lost_or_duplicated(self):
        x = reference_iq(count=530000, start=262100)
        frames = decode_adsb(x, 2_000_000)['frames']
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0]['sample_start'], 262100)

    def test_repeated_frames_preserved(self):
        x = reference_iq(count=530000, start=1000)
        packet = reference_iq()[1000:1240]
        x[300000:300240] = packet
        self.assertEqual(len(decode_adsb(x, 2_000_000)['frames']), 2)

    def test_candidate_budget(self):
        result = decode_adsb(reference_iq(), 2_000_000, max_candidates=0)
        self.assertTrue(result['budget_exhausted'])
        self.assertEqual(result['frames'], [])

    def test_am_audio_recovers_reference_tone(self):
        fs = 128000
        t = np.arange(fs)/fs
        rng = np.random.default_rng(9)
        x = (1+.5*np.cos(2*np.pi*700*t))*np.exp(2j*np.pi*18000*t)
        x += .01*(rng.normal(size=len(t))+1j*rng.normal(size=len(t)))
        with tempfile.TemporaryDirectory() as directory:
            report = analyze_samples(x, fs, 100_000_000, directory)
            am = [trial for band in report['signals'] for trial in band['decoder_trials'] if trial['decoder']=='analog_am']
            self.assertTrue(am)
            rate, audio = wavfile.read(Path(directory)/am[0]['audio'])
            f,p = signal.welch(audio[12000:],rate,nperseg=8192)
            self.assertAlmostEqual(f[np.argmax(p)],700,delta=10)
            self.assertEqual(am[0]['status'],'unvalidated_candidate')


if __name__ == '__main__':
    unittest.main()
