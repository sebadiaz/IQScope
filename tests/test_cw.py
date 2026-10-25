import unittest
import tempfile
from pathlib import Path
import numpy as np
from iqscope_cw import search_cw

# Literal independent fixture: CQ TEST 123, standard 1/3/7-unit spacing.
PATTERNS = ['-.-.','--.-',' ','-','.','...','-',' ','.----','..---','...--']
TEXT = 'CQ TEST 123'


def fixture(wpm=20,fs=4000,offset=650):
    dot = 1.2/wpm
    runs = [(0,7)]
    for i,pattern in enumerate(PATTERNS):
        if pattern==' ':
            continue
        for j,symbol in enumerate(pattern):
            runs.append((1,1 if symbol=='.' else 3))
            if j<len(pattern)-1:
                runs.append((0,1))
        runs.append((0,7 if i+1<len(PATTERNS) and PATTERNS[i+1]==' ' else 3))
    runs.append((0,7))
    envelope = np.concatenate([np.full(round(length*dot*fs),value) for value,length in runs])
    rng = np.random.default_rng(18)
    time = np.arange(len(envelope))/fs
    return envelope*np.exp(2j*np.pi*offset*time)+.025*(rng.normal(size=len(time))+1j*rng.normal(size=len(time))),fs


class CwTests(unittest.TestCase):
    def test_automatic_tone_speed_and_numbers(self):
        for speed in (12,20,35):
            x,fs = fixture(wpm=speed)
            result = search_cw(x,fs)
            self.assertTrue(result['candidates'],result)
            best = result['candidates'][0]
            self.assertEqual(best['text'],TEXT)
            self.assertAlmostEqual(best['parameters']['words_per_minute'],speed,delta=1)
            self.assertEqual(best['evidence']['checksum'],'not_present')

    def test_wideband_with_strong_unkeyed_carrier(self):
        x,fs = fixture(fs=48000,offset=-9000)
        x += 3*np.exp(2j*np.pi*13000*np.arange(len(x))/fs)
        result = search_cw(x,fs,7_000_000)
        matches = [c for c in result['candidates'] if c['text']==TEXT]
        self.assertTrue(matches,result)
        self.assertAlmostEqual(matches[0]['channel']['frequency_hz'],6_991_000,delta=10)

    def test_noise_carrier_and_short_capture_abstain(self):
        rng = np.random.default_rng(4)
        for x in (rng.normal(size=16000)+1j*rng.normal(size=16000),np.ones(16000,dtype=complex)):
            self.assertEqual(search_cw(x,4000)['candidates'],[])
        self.assertEqual(search_cw(np.ones(100),4000)['status'],'not_applicable')

    def test_analysis_report_and_text_export(self):
        from iqscope import analyze_samples
        x,fs = fixture()
        with tempfile.TemporaryDirectory() as directory:
            report = analyze_samples(x,fs,7_000_000,directory)
            trial = next(t for t in report['wideband_trials'] if t['decoder']=='cw_morse')
            self.assertEqual(trial['candidates'][0]['text'],TEXT)
            self.assertEqual((Path(directory)/'cw-candidate.txt').read_text(),TEXT)

    def test_rtty_is_not_morse(self):
        from test_rtty import fixture as rtty_fixture
        x,fs = rtty_fixture()
        self.assertEqual(search_cw(x,fs)['candidates'],[])

    def test_budget_and_duration_are_explicit(self):
        x,fs = fixture()
        result = search_cw(x,fs,max_channels=0,max_seconds=2)
        self.assertTrue(result['duration_limited'])
        self.assertEqual(result['candidates'],[])
        self.assertGreater(result['deferred_peak_count'],0)
