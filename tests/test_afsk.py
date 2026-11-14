import unittest
import shutil
import subprocess
import tempfile
from pathlib import Path
import numpy as np
from iqscope_afsk import decode_afsk1200
from test_ax25 import frame, hdlc, TEXT


def fixture(fs=8000,inverted=False,bad=False,offset=0,payload=None,baud=1200):
    bits = hdlc(frame(payload=TEXT.encode() if payload is None else payload,bad=bad))*4
    state = int(inverted)
    tones = []
    for bit in bits:
        if bit=='0':
            state ^= 1
        tones.append(2200 if state else 1200)
    indices = np.floor((np.arange(int(len(tones)*fs/baud))-2.3)*baud/fs).astype(int)
    frequency = np.array(tones)[np.clip(indices,0,len(tones)-1)]+offset
    rng = np.random.default_rng(102)
    audio = .7*np.cos(2*np.pi*np.cumsum(frequency)/fs)+.015*rng.normal(size=len(frequency))
    return audio,fs


class AfskTests(unittest.TestCase):
    def test_automatic_clock_fit_recovers_independent_rate_offsets(self):
        for baud,fs in ((1169,8000),(1194.8,8000),(1206.7,44100),(1230,8000)):
            audio,rate = fixture(baud=baud,fs=fs)
            result = decode_afsk1200(audio,rate)
            self.assertEqual(len(result['frames']),4,result)
            fitted = [f for f in result['frames'] if f['clock_recovery']=='transition_fit']
            self.assertTrue(fitted,result)
            for frame in fitted:
                self.assertEqual(frame['fields']['text'],TEXT)
                self.assertTrue(frame['fcs_valid'])
                self.assertAlmostEqual(frame['clock_baud'],baud,delta=.15)
                self.assertLessEqual(frame['timing_evidence']['residual_rms_symbols'],.1)

    def test_separate_burst_clocks_and_original_time_reference(self):
        first,fs = fixture(baud=1180)
        second,_ = fixture(baud=1220)
        first,second = first[:len(first)//4],second[:len(second)//4]
        prefix,gap = np.zeros(9600),np.zeros(3200)
        audio = np.r_[prefix,first,gap,second,np.zeros(1600)]
        result = decode_afsk1200(audio,fs)
        self.assertEqual(len(result['frames']),2,result)
        for frame,baud,start in zip(result['frames'],(1180,1220),(1.2,(len(prefix)+len(first)+len(gap))/fs)):
            self.assertEqual(frame['clock_recovery'],'transition_fit')
            self.assertAlmostEqual(frame['clock_baud'],baud,delta=.2)
            self.assertAlmostEqual(frame['time_seconds'],start+80/baud,delta=2/baud)
            self.assertGreater(frame['time_end_seconds'],frame['time_seconds'])

    def test_clock_fit_does_not_repair_crc_or_accept_unrelated_rates(self):
        for baud,bad in ((1194.8,True),(1100,False),(1290,False)):
            audio,fs = fixture(baud=baud,bad=bad)
            self.assertEqual(decode_afsk1200(audio,fs)['frames'],[])

    def test_clock_chain_budget_remains_bounded_with_many_bursts(self):
        audio,fs = fixture(baud=1194.8,payload=b'>clock budget')
        burst = audio[:len(audio)//4]
        audio = np.tile(np.r_[np.zeros(400),burst],21)
        result = decode_afsk1200(audio,fs)
        self.assertTrue(result['clock_fit_budget_exhausted'],result)
        self.assertLessEqual(len(result['timing_trials']),16)
        self.assertLessEqual(result['clock_fit_trials'],16)
        self.assertLessEqual(result['phase_trials'],32)
        self.assertLessEqual(result['flag_pairs_examined'],6000)

    def test_direct_audio_duration_budget_and_short_limit(self):
        audio = np.zeros(21*8000)
        result = decode_afsk1200(audio,8000,max_seconds=99)
        self.assertEqual(result['analyzed_seconds'],20)
        self.assertTrue(result['duration_limited'])
        self.assertEqual(result['frames'],[])
        self.assertEqual(result['timing_trials'],[])
        for limit in (0,.1):
            self.assertEqual(decode_afsk1200(audio,8000,max_seconds=limit)['status'],'not_applicable')

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
