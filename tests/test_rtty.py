import unittest

import numpy as np

from iqscope_rtty import decode_rtty

# Independent literal ITA2 reference: LTRS RYRY CQ CQ DE TEST FIGS 12345 LTRS CR LF.
CODES = [31,10,21,10,21,4,14,23,4,14,23,4,9,1,4,16,1,5,16,4,27,23,19,1,10,16,31,8,2]
TEXT = 'RYRY CQ CQ DE TEST 12345\r\n'


def fixture(baud=50,shift=450,inverted=False,fs=4000):
    symbols = [(True,10)]
    for code in CODES:
        symbols.append((False,1))
        symbols.extend((bool(code & (1 << bit)),1) for bit in range(5))
        symbols.append((True,1.5))
    symbols.append((True,10))
    samples = []
    elapsed = 0
    for value,length in symbols:
        end = elapsed+length*fs/baud
        count = int(round(end))-int(round(elapsed))
        mark = not value if inverted else value
        samples.extend([130+(shift/2 if mark else -shift/2)]*count)
        elapsed = end
    phase = 2*np.pi*np.cumsum(samples)/fs
    rng = np.random.default_rng(77)
    iq = np.exp(1j*phase)+.025*(rng.normal(size=len(phase))+1j*rng.normal(size=len(phase)))
    return iq,fs


class RttyTests(unittest.TestCase):
    def test_text_rate_shift_and_figures_without_manual_settings(self):
        x,fs = fixture()
        result = decode_rtty(x,fs)
        self.assertTrue(result['candidates'],result)
        best = result['candidates'][0]
        self.assertEqual(best['text'],TEXT)
        self.assertEqual(best['parameters']['baud'],50)
        self.assertAlmostEqual(best['parameters']['shift_hz'],450,delta=10)
        self.assertEqual(best['evidence']['checksum'],'not_present')

    def test_inverted_polarity_and_other_baud_rate(self):
        x,fs = fixture(baud=45.45,shift=170,inverted=True)
        result = decode_rtty(x,fs)
        self.assertTrue(result['candidates'],result)
        self.assertEqual(result['candidates'][0]['text'],TEXT)
        self.assertEqual(result['candidates'][0]['parameters']['baud'],45.45)

    def test_other_nominal_baud_rates(self):
        for baud in (75,100):
            x,fs = fixture(baud=baud,shift=850)
            result = decode_rtty(x,fs)
            self.assertTrue(result['candidates'],result)
            self.assertEqual(result['candidates'][0]['text'],TEXT)
            self.assertEqual(result['candidates'][0]['parameters']['baud'],baud)

    def test_analysis_duration_limit_is_explicit(self):
        x,fs = fixture()
        result = decode_rtty(np.tile(x,3),fs,max_seconds=len(x)/fs)
        self.assertTrue(result['duration_limited'])

    def test_noise_and_single_carrier_abstain(self):
        rng = np.random.default_rng(6)
        for x in (rng.normal(size=16000)+1j*rng.normal(size=16000),np.exp(2j*np.pi*400*np.arange(16000)/4000)):
            self.assertEqual(decode_rtty(x,4000)['candidates'],[])

    def test_short_and_wideband_sources_not_claimed(self):
        x,fs = fixture()
        self.assertEqual(decode_rtty(x[:300],fs)['status'],'not_applicable')
        self.assertEqual(decode_rtty(x,2_400_000)['status'],'not_applicable')


if __name__ == '__main__':
    unittest.main()
