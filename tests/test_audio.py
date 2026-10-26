import io
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from scipy.io import wavfile
from iqscope_audio import analyze_audio, decode_audio


@unittest.skipUnless(shutil.which('ffmpeg'),'ffmpeg is an optional audio dependency')
class AudioTests(unittest.TestCase):
    def test_cw_report_keeps_audio_separate_from_rf(self):
        from test_cw import fixture,TEXT
        x,fs = fixture()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'cw.wav'
            wavfile.write(path,fs,x.real.astype(np.float32))
            report = analyze_audio(path,Path(directory)/'out')
            self.assertEqual(report['source_kind'],'receiver_audio')
            self.assertIsNone(report['center_frequency_hz'])
            self.assertEqual(report['frequency_reference'],'audio_hz')
            self.assertEqual([t['decoder'] for t in report['wideband_trials']],['cw_morse','rtty_ita2'])
            best = report['wideband_trials'][0]['candidates'][0]
            self.assertEqual(best['text'],TEXT)
            self.assertIn('audio_frequency_hz',best['channel'])
            self.assertNotIn('frequency_hz',best['channel'])
            self.assertGreaterEqual(min(report['spectrum']['frequency_hz']),0)
            self.assertEqual((Path(directory)/'out/cw-candidate.txt').read_text(),TEXT)
            self.assertTrue((Path(directory)/'out/audio-preview.wav').is_file())

    def test_rtty_audio_rate_polarity_and_export(self):
        from test_rtty import fixture,TEXT
        for inverted in (False,True):
            x,fs = fixture(inverted=inverted)
            audio = np.real(x*np.exp(2j*np.pi*1000*np.arange(len(x))/fs))
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory)/'rtty.wav'
                wavfile.write(path,fs,audio.astype(np.float32))
                report = analyze_audio(path,Path(directory)/'out')
                trial = next(t for t in report['wideband_trials'] if t['decoder']=='rtty_ita2')
                self.assertTrue(trial['candidates'],trial)
                best = trial['candidates'][0]
                self.assertEqual(best['text'],TEXT)
                self.assertEqual(best['parameters']['baud'],50)
                self.assertIn('audio_frequency_hz',best['channel'])
                self.assertNotIn('frequency_hz',best['channel'])
                self.assertEqual((Path(directory)/'out/rtty-candidate.txt').read_bytes(),TEXT.encode())

    def test_rtty_twelve_second_budget_is_reported(self):
        from test_rtty import fixture
        x,fs = fixture()
        audio = np.real(x*np.exp(2j*np.pi*1000*np.arange(len(x))/fs))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'long-rtty.wav'
            wavfile.write(path,fs,np.tile(audio,5).astype(np.float32))
            report = analyze_audio(path,Path(directory)/'out',seconds=20)
            trial = next(t for t in report['wideband_trials'] if t['decoder']=='rtty_ita2')
            self.assertTrue(trial['duration_limited'])
            self.assertEqual(trial['analyzed_seconds'],12)
            self.assertEqual(report['analyzed_seconds'],20)

    def test_duration_and_corrupt_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'tone.wav'
            wavfile.write(path,16000,np.ones(48000,dtype=np.float32))
            report = analyze_audio(path,Path(directory)/'out',seconds=2)
            self.assertEqual(report['analyzed_seconds'],2)
            self.assertTrue(all(not t['candidates'] for t in report['wideband_trials']))
            with self.assertRaises(ValueError):
                decode_audio(path,21)
            bad = Path(directory)/'bad.mp3'
            bad.write_bytes(b'not audio'*200)
            with self.assertRaises(ValueError):
                decode_audio(bad)


class AudioDependencyTests(unittest.TestCase):
    def test_missing_ffmpeg_has_actionable_error(self):
        with patch('iqscope_audio.shutil.which',return_value=None):
            with self.assertRaisesRegex(ValueError,'ffmpeg'):
                decode_audio('test.mp3')
