"""Independent frequency-domain pulse shaping for PSK recovery tests."""
import unittest
from fractions import Fraction
import numpy as np
from scipy import signal, fft
from iqscope_psk import decode_psk
from test_psk import equivalent


def fixture(order=4,baud=617,fs=16000,rolloff=.35,offset=273.4,seed=382,clock_ppm=0,symbol_count=800):
    rng=np.random.default_rng(seed)
    symbols=rng.integers(0,order,symbol_count)
    oversampling=32
    impulses=np.zeros((symbol_count+48)*oversampling,dtype=complex)
    impulses[24*oversampling:(24+symbol_count)*oversampling:oversampling]=np.exp(2j*np.pi*symbols/order)
    size=fft.next_fast_len(len(impulses)+32*oversampling)
    frequency=abs(np.fft.fftfreq(size,1/oversampling))
    response=np.zeros(size)
    response[frequency<=(1-rolloff)/2]=1
    edge=(frequency>(1-rolloff)/2)&(frequency<(1+rolloff)/2)
    response[edge]=.5*(1+np.cos(np.pi/rolloff*(frequency[edge]-(1-rolloff)/2)))
    shaped=np.fft.ifft(np.fft.fft(impulses,size)*np.sqrt(response))*oversampling
    shaped=shaped[24*oversampling:(24+symbol_count)*oversampling]
    actual_baud=baud*(1+clock_ppm*1e-6)
    ratio=Fraction(fs/(actual_baud*oversampling)).limit_denominator(20000)
    x=signal.resample_poly(shaped,ratio.numerator,ratio.denominator)
    index=np.arange(len(x))-3.37
    x=np.interp(index,np.arange(len(x)),x.real)+1j*np.interp(index,np.arange(len(x)),x.imag)
    time=np.arange(len(x))/fs
    x*=np.exp(1j*(2*np.pi*offset*time+.83))
    x+=.018*(rng.normal(size=len(x))+1j*rng.normal(size=len(x)))
    return x,fs,symbols,actual_baud


class RrcPskTests(unittest.TestCase):
    def test_filtered_symbols_blind_rate_frequency_and_clock(self):
        for order in (2,4):
            for rolloff in (.2,.35,.5):
                with self.subTest(order=order,rolloff=rolloff):
                    x,fs,expected,baud=fixture(order,rolloff=rolloff,clock_ppm=175)
                    report=decode_psk(x,fs)
                    self.assertTrue(report['candidates'],report)
                    c=report['candidates'][0]
                    self.assertTrue(equivalent(c['symbols'],expected,order))
                    self.assertEqual(c['parameters']['pulse_shape'],'rrc_trial')
                    self.assertAlmostEqual(c['parameters']['baud'],baud,delta=baud*.0005)
                    self.assertAlmostEqual(c['parameters']['carrier_offset_hz'],273.4,delta=.15)
                    self.assertGreater(c['symbol_count'],500)
                    self.assertLess(c['evidence']['symbol_evm_rms'],.16)

    def test_other_rates_and_negative_carrier(self):
        for order,baud in ((2,137),(4,1200)):
            x,fs,expected,actual=fixture(order,baud=baud,clock_ppm=-250,offset=-412.75)
            c=decode_psk(x,fs)['candidates'][0]
            self.assertTrue(equivalent(c['symbols'],expected,order))
            self.assertAlmostEqual(c['parameters']['baud'],actual,delta=.02)
            self.assertAlmostEqual(c['parameters']['carrier_offset_hz'],-412.75,delta=.1)

    def test_two_filtered_channels(self):
        from iqscope import discover
        from iqscope_psk import search_psk
        x,fs,a,_=fixture(2,fs=192000)
        y,_,b,_=fixture(4,fs=192000,baud=1200,seed=711)
        n=min(len(x),len(y))
        time=np.arange(n)/fs
        wide=x[:n]*np.exp(-2j*np.pi*35000*time)+.8*y[:n]*np.exp(2j*np.pi*40000*time)
        bands,*_=discover(wide,fs)
        report=search_psk(wide,fs,bands)
        self.assertEqual(len(report['candidates']),2,report)
        for c in report['candidates']:
            order=2 if c['modulation']=='BPSK' else 4
            self.assertTrue(equivalent(c['symbols'],a if order==2 else b,order))
            self.assertEqual(c['parameters']['pulse_shape'],'rrc_trial')

    def test_other_constellations_and_noise_abstain(self):
        # Same independent shaping with eight phases should not become QPSK.
        x,fs,_,_=fixture(8)
        self.assertFalse(decode_psk(x,fs)['candidates'])
        rng=np.random.default_rng(891)
        n=16000
        qam=(rng.choice([-3,-1,1,3],1000)+1j*rng.choice([-3,-1,1,3],1000)).repeat(16)
        for values in (qam,rng.normal(size=n)+1j*rng.normal(size=n),np.zeros(n)):
            self.assertFalse(decode_psk(values,fs)['candidates'])

    def test_bit_budget_and_report_exports(self):
        import tempfile,json
        from pathlib import Path
        from iqscope import analyze_samples
        x,fs,expected,_=fixture(4)
        c=decode_psk(x,fs,max_bits=200)['candidates'][0]
        self.assertEqual(c['bit_count'],200)
        self.assertTrue(c['bit_budget_reached'])
        self.assertTrue(equivalent(c['symbols'],expected,4))
        with tempfile.TemporaryDirectory() as directory:
            report=analyze_samples(x,fs,0,directory)
            trial=next(t for t in report['wideband_trials'] if t['decoder']=='psk_generic')
            c=trial['candidates'][0]
            saved=json.loads((Path(directory)/trial['artifact']).read_text())['candidates'][0]
            self.assertEqual(saved['parameters']['pulse_shape'],'rrc_trial')
            self.assertEqual(saved['bits'],(Path(directory)/c['artifacts']['bits']).read_text())
            self.assertTrue(equivalent(saved['symbols'],expected,4))
            self.assertEqual(saved['evidence']['checksum'],'not_checked')
