import tempfile
import unittest
from pathlib import Path
import numpy as np
from iqscope_fsk4 import decode_fsk4, search_fsk4


def fixture(baud=300,fs=16000,spacing=900,seed=79):
    rng = np.random.default_rng(seed)
    symbols = rng.integers(0,4,600)
    indices = np.floor((np.arange(int(600*fs/baud))-3.2)*baud/fs).astype(int)
    frequency = 210+(symbols[np.clip(indices,0,599)]-1.5)*spacing
    x = np.exp(2j*np.pi*np.cumsum(frequency)/fs)
    x += .012*(rng.normal(size=len(x))+1j*rng.normal(size=len(x)))
    return x,fs,''.join(map(str,symbols.tolist()))


class Fsk4Tests(unittest.TestCase):
    def test_blind_levels_clock_and_symbols(self):
        for baud in (50,137,300,1200):
            x,fs,expected = fixture(baud=baud)
            result = decode_fsk4(x,fs)
            self.assertTrue(result['candidates'],result)
            candidate = result['candidates'][0]
            self.assertIn(candidate['symbols'],expected)
            self.assertGreater(candidate['symbol_count'],100)
            self.assertAlmostEqual(candidate['parameters']['baud'],baud,delta=baud*.005)
            self.assertAlmostEqual(candidate['parameters']['spacing_hz'],900,delta=10)
            self.assertEqual(candidate['bits'],''.join(format(int(s),'02b') for s in candidate['symbols']))

    def test_binary_noise_and_carrier_abstain(self):
        from test_fsk import fixture as binary
        rng = np.random.default_rng(80)
        for x,fs in ((binary()[0],12000),(np.ones(16000,dtype=complex),16000),
                     (rng.normal(size=16000)+1j*rng.normal(size=16000),16000)):
            self.assertEqual(decode_fsk4(x,fs)['candidates'],[])

    def test_two_wideband_channels_with_interferer(self):
        from iqscope import discover
        x,fs,a = fixture(fs=192000)
        y,_,b = fixture(fs=192000,seed=87)
        time = np.arange(len(x))/fs
        wide = x*np.exp(-2j*np.pi*35000*time)+.8*y*np.exp(2j*np.pi*40000*time)
        wide += 2*np.exp(2j*np.pi*75000*time)
        bands,*_ = discover(wide,fs)
        result = search_fsk4(wide,fs,bands,7_000_000)
        self.assertEqual(len(result['candidates']),2,result)
        for candidate in result['candidates']:
            frequency = candidate['channel']['frequency_hz']
            self.assertIn(candidate['symbols'],a if frequency<7_000_000 else b)
            self.assertGreater(candidate['symbol_count'],500)
        for expected in (6_965_210,7_040_210):
            self.assertTrue(any(abs(c['channel']['frequency_hz']-expected)<20 for c in result['candidates']))

    def test_report_and_exports_preserve_symbols_and_convention(self):
        from iqscope import analyze_samples
        x,fs,expected = fixture()
        with tempfile.TemporaryDirectory() as directory:
            report = analyze_samples(x,fs,0,directory)
            trial = next(t for t in report['wideband_trials'] if t['decoder']=='fsk4_generic')
            candidate = trial['candidates'][0]
            symbols = (Path(directory)/candidate['artifacts']['symbols']).read_text()
            self.assertIn(symbols,expected)
            bits = (Path(directory)/candidate['artifacts']['bits']).read_text()
            self.assertEqual(bits,''.join(format(int(s),'02b') for s in symbols))
            packed = (Path(directory)/candidate['artifacts']['packed']).read_bytes()
            unpacked = ''.join(map(str,np.unpackbits(np.frombuffer(packed,dtype=np.uint8)).tolist()))
            self.assertEqual(unpacked[:candidate['bit_count']],bits)
            self.assertEqual(unpacked[candidate['bit_count']:],'0'*candidate['packed_padding_bits'])

    def test_unequal_spacing_and_eight_levels_abstain(self):
        rng = np.random.default_rng(90)
        for levels in ([-1200,-300,100,1600],np.arange(8)*400-1400):
            frequency = np.repeat(rng.choice(levels,500),40)
            x = np.exp(2j*np.pi*np.cumsum(frequency)/16000)
            self.assertEqual(decode_fsk4(x,16000)['candidates'],[])

    def test_limits(self):
        x,fs,_ = fixture()
        result = decode_fsk4(x,fs,max_seconds=1,max_bits=101)
        self.assertTrue(result['duration_limited'])
        self.assertTrue(result['candidates'][0]['bit_budget_reached'])
        self.assertEqual(result['candidates'][0]['bit_count'],100)
