import tempfile
import unittest
from pathlib import Path
import numpy as np
from iqscope_psk import decode_psk, search_psk


def fixture(order=2,baud=317,fs=16000,offset=273.4,seed=902,phase=.71,symbol_count=700):
    rng=np.random.default_rng(seed)
    symbols=rng.integers(0,order,symbol_count)
    time=np.arange(int(symbol_count*fs/baud))/fs
    index=np.clip(np.floor((time-3.2/fs)*baud).astype(int),0,len(symbols)-1)
    x=np.exp(1j*(2*np.pi*symbols[index]/order+2*np.pi*offset*time+phase))
    x+=.015*(rng.normal(size=len(x))+1j*rng.normal(size=len(x)))
    return x,fs,symbols


def equivalent(candidate, expected, order):
    return any(candidate in ''.join(map(str,((sign*expected+rotation)%order).tolist()))
               for sign in (-1,1) for rotation in range(order))


class PskTests(unittest.TestCase):
    def test_blind_clock_carrier_and_symbols(self):
        for order in (2,4):
            for baud in (50,137,317,1200):
                with self.subTest(order=order,baud=baud):
                    x,fs,expected=fixture(order,baud=baud,offset=-317.25)
                    result=decode_psk(x,fs)
                    self.assertTrue(result['candidates'],result)
                    c=result['candidates'][0]
                    self.assertEqual(c['modulation'],'BPSK' if order==2 else 'QPSK')
                    self.assertTrue(equivalent(c['symbols'],expected,order))
                    self.assertGreater(c['symbol_count'],100)
                    self.assertAlmostEqual(c['parameters']['baud'],baud,delta=baud*.005)
                    self.assertAlmostEqual(c['parameters']['carrier_offset_hz'],-317.25,delta=.1)
                    self.assertEqual(len(c['bits']),len(c['symbols'])*(1 if order==2 else 2))
                    self.assertLessEqual(len(c['constellation']['i']),512)

    def test_noise_tone_fsk_and_am_abstain(self):
        from test_fsk import fixture as fsk_fixture
        rng=np.random.default_rng(44)
        time=np.arange(16000)/16000
        for x in (np.ones(16000),np.zeros(16000),np.exp(2j*np.pi*900*time),
                  rng.normal(size=16000)+1j*rng.normal(size=16000),
                  (1+.3*np.cos(2*np.pi*200*time))*np.exp(2j*np.pi*900*time),fsk_fixture(fs=16000)[0]):
            self.assertEqual(decode_psk(x,16000)['candidates'],[])

    def test_duration_bit_budget_and_invalid_input(self):
        x,fs,_=fixture(4,baud=50,symbol_count=900)
        result=decode_psk(x,fs,max_bits=200)
        self.assertTrue(result['duration_limited'])
        c=result['candidates'][0]
        self.assertLessEqual(c['bit_count'],200)
        self.assertTrue(c['bit_budget_reached'])
        fast,fast_rate,expected=fixture(4,fs=96000,baud=9600,symbol_count=26000)
        high=decode_psk(fast,fast_rate)['candidates'][0]
        self.assertEqual(high['bit_count'],50000)
        self.assertTrue(high['bit_budget_reached'])
        self.assertTrue(equivalent(high['symbols'],expected,4))
        for rate in (float('nan'),0,1_000_000):
            self.assertEqual(decode_psk(x,rate)['status'],'not_applicable')
        x[:10]=np.nan
        self.assertFalse(decode_psk(x,fs)['candidates'])

    def test_two_automatic_channels(self):
        from iqscope import discover
        x,fs,a=fixture(2,fs=192000,baud=1200)
        y,_,b=fixture(4,fs=192000,baud=1200,seed=124)
        time=np.arange(len(x))/fs
        wide=x*np.exp(-2j*np.pi*35000*time)+.8*y*np.exp(2j*np.pi*40000*time)
        bands,*_=discover(wide,fs)
        result=search_psk(wide,fs,bands,7_000_000)
        self.assertEqual(len(result['candidates']),2,result)
        for candidate in result['candidates']:
            order=2 if candidate['modulation']=='BPSK' else 4
            self.assertTrue(equivalent(candidate['symbols'],a if order==2 else b,order))
            self.assertAlmostEqual(candidate['channel']['offset_hz'],-34726.6 if order==2 else 40273.4,delta=.2)
            self.assertGreater(candidate['channel']['frequency_hz'],6_900_000)

    def test_report_exports_preserve_bits_and_constellation(self):
        from iqscope import analyze_samples
        x,fs,expected=fixture(4)
        with tempfile.TemporaryDirectory() as directory:
            report=analyze_samples(x,fs,0,directory)
            trial=next(t for t in report['wideband_trials'] if t['decoder']=='psk_generic')
            candidate=trial['candidates'][0]
            self.assertTrue(equivalent(candidate['symbols'],expected,4))
            self.assertEqual((Path(directory)/candidate['artifacts']['bits']).read_text(),candidate['bits'])
            packed=np.frombuffer((Path(directory)/candidate['artifacts']['packed']).read_bytes(),dtype='u1')
            self.assertEqual(''.join(map(str,np.unpackbits(packed)[:candidate['bit_count']])),candidate['bits'])
            import json
            saved=json.loads((Path(directory)/trial['artifact']).read_text())
            self.assertEqual(saved['candidates'][0]['constellation'],candidate['constellation'])
            self.assertEqual(candidate['evidence']['checksum'],'not_checked')
