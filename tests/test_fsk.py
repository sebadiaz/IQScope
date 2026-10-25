import tempfile
import unittest
from pathlib import Path
import numpy as np
from iqscope_fsk import decode_fsk


def fixture(baud=300,fs=12000,shift=1500,inverted=False):
    rng = np.random.default_rng(2026)
    bits = rng.integers(0,2,700)
    # Fractional clock and noninteger sample offset independent of receiver.
    index = np.floor((np.arange(int(700*fs/baud))-2.7)*baud/fs).astype(int)
    keyed = bits[np.clip(index,0,len(bits)-1)]
    frequencies = 310+(2*(1-keyed if inverted else keyed)-1)*shift/2
    iq = np.exp(2j*np.pi*np.cumsum(frequencies)/fs)
    iq += .015*(rng.normal(size=len(iq))+1j*rng.normal(size=len(iq)))
    return iq,fs,''.join(map(str,(1-bits if inverted else bits).tolist()))


class FskTests(unittest.TestCase):
    def test_blind_rate_and_bits_fractional_timing(self):
        for baud in (50,137,300,1200):
            x,fs,expected = fixture(baud=baud)
            result = decode_fsk(x,fs)
            self.assertTrue(result['candidates'],result)
            candidate = result['candidates'][0]
            self.assertIn(candidate['bits'],expected)
            self.assertGreater(candidate['bit_count'],100)
            self.assertAlmostEqual(candidate['parameters']['baud'],baud,delta=baud*.005)
            self.assertAlmostEqual(candidate['parameters']['shift_hz'],1500,delta=20)

    def test_polarity_is_explicit(self):
        x,fs,expected = fixture(inverted=True)
        result = decode_fsk(x,fs)
        self.assertIn(result['candidates'][0]['bits'],expected)
        self.assertIn('inverse equally possible',result['candidates'][0]['parameters']['polarity'])

    def test_noise_carrier_and_four_levels_abstain(self):
        rng = np.random.default_rng(7)
        frequency = np.repeat(rng.choice([-900,-300,300,900],400),40)
        for x in (rng.normal(size=16000)+1j*rng.normal(size=16000),
                  np.exp(2j*np.pi*500*np.arange(16000)/12000),
                  np.exp(2j*np.pi*np.cumsum(frequency)/12000)):
            self.assertEqual(decode_fsk(x,12000)['candidates'],[])

    def test_report_and_packed_export_preserve_bit_count(self):
        from iqscope import analyze_samples
        x,fs,expected = fixture()
        with tempfile.TemporaryDirectory() as directory:
            report = analyze_samples(x,fs,0,directory)
            candidate = next(t for t in report['wideband_trials'] if t['decoder']=='fsk2_generic')['candidates'][0]
            bits = (Path(directory)/'fsk-bits.txt').read_text()
            self.assertIn(bits,expected)
            packed = np.frombuffer((Path(directory)/'fsk-packed.bin').read_bytes(),dtype=np.uint8)
            recovered = ''.join(map(str,np.unpackbits(packed).tolist()))
            self.assertEqual(recovered[:candidate['bit_count']],bits)
            self.assertEqual(recovered[candidate['bit_count']:],'0'*candidate['packed_padding_bits'])

    def test_limits(self):
        x,fs,_ = fixture()
        result = decode_fsk(x,fs,max_seconds=1,max_bits=80)
        self.assertTrue(result['duration_limited'])
        self.assertTrue(result['candidates'][0]['bit_budget_reached'])
        self.assertEqual(result['candidates'][0]['bit_count'],80)
        self.assertEqual(decode_fsk(x,2_400_000)['status'],'not_applicable')
