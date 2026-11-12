"""Receiver discriminator levels are distinct from RF IQ and AFSK audio tones."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import numpy as np
from scipy import signal
from scipy.io import wavfile

from iqscope_pocsag_audio import decode_pocsag_audio
from test_pocsag import transmission, message_words, TEXT


def reference_audio(fs=8000, baud=1200, inverted=False, ppm=0, numeric=False, bits_override=None):
    text = '00123 45-67' if numeric else TEXT
    bits = (bits_override if bits_override is not None else transmission(message_words(text=text, function=0 if numeric else 3)))+'10'*64
    actual = baud*(1+ppm/1e6)
    indices = np.floor((np.arange(int(len(bits)*fs/actual))-2.3)*actual/fs).astype(int)
    levels = 2*np.array(list(map(int, bits)))[np.clip(indices, 0, len(bits)-1)]-1.
    if inverted:
        levels = -levels
    filtered = signal.sosfilt(signal.butter(3, min(fs*.4, baud*2), fs=fs, output='sos'), levels)
    rng = np.random.default_rng(5842)
    return .17+.65*filtered+.003*rng.normal(size=len(filtered))


class PocsagAudioTests(unittest.TestCase):
    def test_three_rates_both_polarities_and_clock_offset(self):
        for baud in (512, 1200, 2400):
            for inverted in (False, True):
                for ppm in (-700, 700):
                    trial = decode_pocsag_audio(reference_audio(baud=baud, inverted=inverted, ppm=ppm), 8000)
                    self.assertEqual(len(trial['messages']), 1, (baud, inverted, ppm, trial))
                    message = trial['messages'][0]
                    self.assertEqual(message['fields']['text'], TEXT)
                    self.assertEqual(message['nominal_baud'], baud)
                    self.assertAlmostEqual(message['baud'], baud*(1+ppm/1e6), delta=baud*.002)
                    self.assertEqual(message['frontend'], 'receiver_audio_discriminator')
                    self.assertIsNone(message['channel'])
                    self.assertNotIn('frequency_hz', message)

    def test_high_sample_rate_and_numeric_content(self):
        for fs in (24000, 48000, 96000):
            trial = decode_pocsag_audio(reference_audio(fs=fs, numeric=True), fs)
            self.assertEqual(len(trial['messages']), 1)
            fields = trial['messages'][0]['fields']
            self.assertTrue(fields['text'].startswith('00123 45-67'))
            self.assertEqual(fields['message_format'], 'numeric')

    def test_silence_tones_noise_and_afsk_are_not_pocsag(self):
        rng = np.random.default_rng(584)
        time = np.arange(16000)/8000
        from test_afsk import fixture
        cases = [np.zeros(16000), np.ones(16000), np.sin(2*np.pi*600*time), rng.normal(size=16000)]
        # An IQ/AFSK conversion is deliberately not used by this frontend.
        for samples in cases:
            self.assertFalse(decode_pocsag_audio(samples, 8000)['messages'])
        afsk, fs = fixture()
        self.assertFalse(decode_pocsag_audio(afsk, fs)['messages'])

    def test_no_state_across_windows_and_no_manual_message_completion(self):
        samples = reference_audio()
        boundary = int(len(samples)*.66)
        self.assertFalse(decode_pocsag_audio(samples[:boundary], 8000)['messages'])
        self.assertFalse(decode_pocsag_audio(samples[boundary:], 8000)['messages'])
        self.assertEqual(len(decode_pocsag_audio(samples, 8000)['messages']), 1)

    def test_processing_budgets_and_invalid_audio(self):
        samples = reference_audio()
        limited = decode_pocsag_audio(samples, 8000, max_seconds=.05)
        self.assertTrue(limited['duration_limited'])
        self.assertEqual(limited['analyzed_seconds'], .05)
        self.assertFalse(limited['messages'])
        edge_limited = decode_pocsag_audio(samples, 8000, max_edges=20)
        self.assertTrue(edge_limited['edge_budget_reached'])
        self.assertFalse(edge_limited['messages'])
        for audio, fs in ((samples, 4000), (np.full(16000, np.nan), 8000), (np.zeros((16000, 2)), 8000)):
            self.assertFalse(decode_pocsag_audio(audio, fs)['messages'])

    def test_corrupt_received_word_is_rejected_without_correction(self):
        bits = transmission()
        index = 1088+15  # One information bit in the first message codeword.
        damaged = bits[:index]+('0' if bits[index]=='1' else '1')+bits[index+1:]
        trial = decode_pocsag_audio(reference_audio(bits_override=damaged), 8000)
        self.assertFalse(trial['messages'])
        self.assertGreater(trial['invalid_codewords'], 0)

    @unittest.skipUnless(shutil.which('ffmpeg'), 'ffmpeg is an optional audio dependency')
    def test_wav_audio_pipeline_json_and_provenance(self):
        from iqscope_audio import analyze_audio
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root/'pager.wav'
            wavfile.write(path, 48000, reference_audio(fs=48000).astype(np.float32))
            report = analyze_audio(path, root/'out', 20)
            trial = next(t for t in report['wideband_trials'] if t['decoder']=='pocsag')
            self.assertEqual(trial['messages'][0]['fields']['text'], TEXT)
            self.assertEqual(report['source_kind'], 'receiver_audio')
            self.assertIsNone(report['center_frequency_hz'])
            self.assertIsNone(trial['messages'][0]['channel'])
            self.assertEqual(json.loads((root/'out'/trial['artifact']).read_text()), trial)
            json.dumps(report, allow_nan=False)


class PocsagSourceTests(unittest.TestCase):
    def test_offline_source_hash_mismatch_is_rejected(self):
        from scripts.pocsag_radio_reference import verified_source
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'lab').mkdir()
            (root/'lab/pager_addr0.wav').write_bytes(b'not the pinned recording')
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                verified_source(root, 0, offline=True)

if __name__ == '__main__':
    unittest.main()
