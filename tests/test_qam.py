import unittest
import tempfile
import json
from pathlib import Path
from fractions import Fraction
import numpy as np
from scipy import signal, fft
from iqscope_qam import decode_qam16, search_qam16

def fixture(baud=617,fs=16000,rolloff=.35,offset=273.4,seed=382,clock_ppm=0,symbol_count=1200,side=4):
    rng=np.random.default_rng(seed)
    symbols=rng.integers(0,side**2,symbol_count)
    points=((2*(symbols//side)-(side-1))+1j*(2*(symbols%side)-(side-1)))/np.sqrt(2*(side**2-1)/3)
    oversampling=32
    impulses=np.zeros((symbol_count+48)*oversampling,dtype=complex)
    impulses[24*oversampling:(24+symbol_count)*oversampling:oversampling]=points
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


def equivalent(candidate,expected):
    for conjugate in (False,True):
        i=expected//4;q=expected%4
        if conjugate:q=3-q
        for _ in range(4):
            if bytes(candidate) in bytes((4*i+q).astype(np.uint8)):return True
            i,q=3-q,i
    return False


class QamTests(unittest.TestCase):
    def test_blind_shaped_qam_symbols(self):
        for rolloff in (.2,.35,.5):
            with self.subTest(rolloff=rolloff):
                x,fs,expected,baud=fixture(rolloff=rolloff,clock_ppm=175)
                original=x.copy();trial=decode_qam16(x,fs)
                np.testing.assert_array_equal(x,original)
                self.assertTrue(trial['candidates'],trial)
                c=trial['candidates'][0]
                self.assertTrue(equivalent(c['symbols'],expected))
                self.assertAlmostEqual(c['parameters']['baud'],baud,delta=.1)
                self.assertAlmostEqual(c['parameters']['carrier_offset_hz'],273.4,delta=.1)
                self.assertGreater(c['symbol_count'],1000)
                self.assertEqual(c['bits'],''.join(format(v,'04b') for v in c['symbols']))
                self.assertEqual(c['evidence']['checksum'],'not_checked')

    def test_other_rates_phases_and_seeds(self):
        for baud,fs,seed in ((137,16000,701),(1200,16000,912),(1777,24000,101)):
            x,rate,expected,actual=fixture(baud=baud,fs=fs,seed=seed,offset=-412.75,clock_ppm=-250)
            result=decode_qam16(x,rate)
            self.assertTrue(result['candidates'],result)
            c=result['candidates'][0]
            self.assertTrue(equivalent(c['symbols'],expected))
            self.assertAlmostEqual(c['parameters']['baud'],actual,delta=.1)
            self.assertAlmostEqual(c['parameters']['carrier_offset_hz'],-412.75,delta=.1)

    def test_other_modulations_noise_and_carrier_abstain(self):
        from test_psk_rrc import fixture as psk
        from test_fsk import fixture as fsk
        rng=np.random.default_rng(861)
        cases=[psk(order=order)[0] for order in (2,4,8)]
        cases+=[fixture(side=8)[0],np.zeros(16000),np.ones(16000),
                rng.normal(size=16000)+1j*rng.normal(size=16000),fsk(fs=16000)[0]]
        for x in cases:
            self.assertFalse(decode_qam16(x,16000)['candidates'])

    def test_budget_and_invalid_samples(self):
        x,fs,_,_=fixture(baud=137,symbol_count=1200)
        r=decode_qam16(x,fs,max_bits=1030)
        self.assertTrue(r['duration_limited'])
        c=r['candidates'][0]
        self.assertEqual(c['bit_count'],1028)
        self.assertTrue(c['bit_budget_reached'])
        self.assertEqual(c['packed_padding_bits'],4)
        x[:100]=np.nan
        self.assertFalse(decode_qam16(x,fs)['candidates'])
        self.assertEqual(decode_qam16(np.ones(1000),float('nan'))['status'],'not_applicable')

    def test_automatic_wideband_channel(self):
        from iqscope import discover
        x,fs,expected,_=fixture(fs=192000,baud=1200)
        time=np.arange(len(x))/fs
        wide=x*np.exp(2j*np.pi*35000*time)
        bands,*_=discover(wide,fs)
        r=search_qam16(wide,fs,bands,7e6)
        self.assertTrue(r['candidates'],r)
        c=r['candidates'][0]
        self.assertTrue(equivalent(c['symbols'],expected))
        self.assertAlmostEqual(c['channel']['frequency_hz'],7e6+35000+273.4,delta=.2)

    def test_two_channels_with_interfering_tone(self):
        from iqscope import discover
        x,fs,a,_=fixture(fs=192000,baud=1200)
        y,_,b,_=fixture(fs=192000,baud=1200,seed=511)
        time=np.arange(len(x))/fs
        wide=x*np.exp(-2j*np.pi*35000*time)+.8*y*np.exp(2j*np.pi*40000*time)+2*np.exp(2j*np.pi*75000*time)
        bands,*_=discover(wide,fs)
        result=search_qam16(wide,fs,bands)
        self.assertEqual(len(result['candidates']),2,result)
        for c in result['candidates']:
            self.assertTrue(equivalent(c['symbols'],a if c['channel']['offset_hz']<0 else b))

    def test_report_and_exports_preserve_candidate_data(self):
        from iqscope import analyze_samples
        x,fs,expected,_=fixture()
        with tempfile.TemporaryDirectory() as directory:
            report=analyze_samples(x,fs,0,directory)
            qam=next(t for t in report['wideband_trials'] if t['decoder']=='qam16_generic')
            c=qam['candidates'][0]
            self.assertTrue(equivalent(c['symbols'],expected))
            self.assertEqual((Path(directory)/c['artifacts']['bits']).read_text(),c['bits'])
            self.assertEqual(json.loads((Path(directory)/c['artifacts']['symbols']).read_text()),c['symbols'])
            packed=np.frombuffer((Path(directory)/c['artifacts']['packed']).read_bytes(),dtype='u1')
            self.assertEqual(''.join(map(str,np.unpackbits(packed)[:c['bit_count']])),c['bits'])
            self.assertEqual(json.loads((Path(directory)/qam['artifact']).read_text())['candidates'][0]['constellation'],c['constellation'])

    def test_gain_rotation_and_iq_conjugation(self):
        x,fs,expected,_=fixture(seed=722)
        for values in (2j*x,.17*np.conj(x)):
            result=decode_qam16(values,fs)
            self.assertTrue(result['candidates'],result)
            self.assertTrue(equivalent(result['candidates'][0]['symbols'],expected))

    def test_four_samples_per_symbol(self):
        for rolloff,seed in ((.2,701),(.35,382),(.5,912)):
            with self.subTest(rolloff=rolloff):
                x,fs,expected,baud=fixture(fs=16000,baud=4000,rolloff=rolloff,seed=seed)
                original=x.copy()
                r=decode_qam16(x,fs)
                np.testing.assert_array_equal(x,original)
                self.assertTrue(r['candidates'],r)
                c=r['candidates'][0]
                self.assertTrue(equivalent(c['symbols'],expected))
                self.assertAlmostEqual(c['parameters']['baud'],baud,delta=.1)
                self.assertEqual(r['processing']['interpolation_factor'],2)

    def test_high_rate_preserves_physical_units_and_labels(self):
        x,fs,expected,_=fixture(fs=16000,baud=3800,offset=-273.4)
        low=decode_qam16(x,fs)
        scale=200e6/fs
        r=search_qam16(x,200e6,[],28e9)
        self.assertTrue(r['candidates'],r)
        c=r['candidates'][0];reference=low['candidates'][0]
        self.assertTrue(equivalent(c['symbols'],expected))
        self.assertEqual(c['symbols'],reference['symbols'])
        self.assertAlmostEqual(c['parameters']['baud'],3800*scale,delta=2000)
        self.assertAlmostEqual(c['parameters']['carrier_offset_hz'],-273.4*scale,delta=2000)
        self.assertAlmostEqual(c['parameters']['first_symbol_center_seconds']*scale,
                               reference['parameters']['first_symbol_center_seconds'],delta=1e-7)
        self.assertAlmostEqual(c['channel']['frequency_hz'],28e9-273.4*scale,delta=2000)
        self.assertEqual(c['channel']['sample_rate'],200e6)
        self.assertEqual(r['processing']['source_sample_count'],len(x))
        self.assertEqual(r['processing']['time_coordinate_sample_rate'],32000)
        self.assertAlmostEqual(r['analyzed_seconds'],len(x)/200e6)

    def test_high_rate_boundaries_and_false_positives(self):
        rng=np.random.default_rng(1083)
        for x in (fixture(fs=16000,baud=4000,side=8)[0],
                  rng.normal(size=6000)+1j*rng.normal(size=6000),np.ones(288010)):
            r=decode_qam16(x,200e6)
            self.assertFalse(r['candidates'],r)
            self.assertLessEqual(r['processing']['source_sample_count'],288000)
            self.assertAlmostEqual(r['analyzed_seconds'],min(len(x),288000)/200e6)
        x,_,expected,_=fixture(fs=200e6,baud=50e6,offset=1e6)
        r=decode_qam16(x,200e6,max_seconds=10e-6)
        self.assertTrue(r['duration_limited'])
        self.assertEqual(r['processing']['source_sample_count'],2000)
        self.assertTrue(r['candidates'],r)
        self.assertTrue(equivalent(r['candidates'][0]['symbols'],expected))
        self.assertEqual(decode_qam16(x,251e6)['status'],'not_applicable')
