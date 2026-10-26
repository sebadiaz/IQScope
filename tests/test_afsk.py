import unittest
import shutil
import subprocess
import tempfile
from pathlib import Path
import numpy as np
from iqscope_afsk import decode_afsk1200
from test_ax25 import frame, hdlc, TEXT


def fixture(fs=8000,inverted=False,bad=False,offset=0):
    bits = hdlc(frame(bad=bad))*4
    state = int(inverted)
    tones = []
    for bit in bits:
        if bit=='0':
            state ^= 1
        tones.append(2200 if state else 1200)
    indices = np.floor((np.arange(int(len(tones)*fs/1200))-2.3)*1200/fs).astype(int)
    frequency = np.array(tones)[np.clip(indices,0,len(tones)-1)]+offset
    rng = np.random.default_rng(102)
    audio = .7*np.cos(2*np.pi*np.cumsum(frequency)/fs)+.015*rng.normal(size=len(frequency))
    return audio,fs


class AfskTests(unittest.TestCase):
    def test_audio_to_ax25_crc_and_phase_deduplication(self):
        for fs in (8000,44100):
            for inverted in (False,True):
                audio,rate = fixture(fs=fs,inverted=inverted)
                result = decode_afsk1200(audio,rate)
                self.assertEqual(len(result['frames']),4,result)
                self.assertTrue(all(f['fields']['text']==TEXT for f in result['frames']))
                self.assertTrue(all(f['fcs_valid'] for f in result['frames']))
                self.assertTrue(all('frequency_hz' not in f['channel'] for f in result['frames']))

    def test_bad_crc_noise_and_unkeyed_tone_abstain(self):
        audio,fs = fixture(bad=True)
        rng = np.random.default_rng(103)
        for data in (audio,rng.normal(size=16000),np.cos(2*np.pi*1200*np.arange(16000)/8000)):
            self.assertEqual(decode_afsk1200(data,fs)['frames'],[])

    @unittest.skipUnless(shutil.which('ffmpeg'),'ffmpeg is an optional audio dependency')
    def test_mp3_import_exports_crc_frames_without_rf_center(self):
        from scipy.io import wavfile
        from iqscope_audio import analyze_audio
        audio,fs = fixture()
        with tempfile.TemporaryDirectory() as directory:
            wave = Path(directory)/'afsk.wav'
            mp3 = Path(directory)/'afsk.mp3'
            wavfile.write(wave,fs,audio.astype(np.float32))
            subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(wave),'-ar','24000','-b:a','64k',str(mp3)],check=True,timeout=20)
            report = analyze_audio(mp3,Path(directory)/'out')
            trial = next(t for t in report['wideband_trials'] if t['decoder']=='afsk1200_ax25')
            self.assertGreaterEqual(len(trial['frames']),3,trial)
            self.assertIsNone(report['center_frequency_hz'])
            self.assertTrue(all(f['fields']['text']==TEXT for f in trial['frames']))
            import json
            exported = json.loads((Path(directory)/'out'/report['frame_artifact']).read_text())
            self.assertEqual(exported['frames'],trial['frames'])

    def test_frame_and_flag_budgets(self):
        audio,fs = fixture()
        result = decode_afsk1200(audio,fs,max_frames=2)
        self.assertEqual(len(result['frames']),2)
        self.assertTrue(result['budget_exhausted'])
        result = decode_afsk1200(audio,fs,max_flag_pairs=2)
        self.assertLessEqual(result['flag_pairs_examined'],2)
        self.assertTrue(result['budget_exhausted'])
