import tempfile
import unittest
from pathlib import Path
import numpy as np
from scipy import signal
from iqscope_lora import detect_lora_preamble


def preamble(sf=7, bandwidth=125000, inverted=False):
    # Integrate a linear instantaneous-frequency ramp at two samples/chip.
    length = 2**sf
    time = np.arange(2*length)/2
    symbol = np.exp(2j*np.pi*(time*time/(2*length)-time/2))
    waveform = np.tile(symbol, 12)
    if inverted:
        waveform = waveform.conj()
    rng = np.random.default_rng(71)
    waveform *= np.exp(2j*np.pi*0.27*np.arange(len(waveform))/(2*length))
    waveform += .03*(rng.normal(size=len(waveform))+1j*rng.normal(size=len(waveform)))
    return np.r_[np.zeros(47), waveform], bandwidth*2


def synchronized_preamble(inverted=False, sync_word=0x34, sf=8, bandwidth=125000, offset=47, cfo_bins=.19):
    # Independent instantaneous-frequency integration at two samples per chip.
    length = 2**sf
    t = np.arange(2*length)/2
    up = np.exp(2j*np.pi*(t*t/(2*length)-t/2))
    x = np.r_[np.zeros(offset),np.tile(up,8),np.roll(up,-16*(sync_word>>4)),np.roll(up,-16*(sync_word&15)),
              np.tile(up.conj(),2),up.conj()[:length//2],np.zeros(4*length)]
    if inverted:
        x = x.conj()
    x *= np.exp(2j*np.pi*cfo_bins*np.arange(len(x))/(2*length))
    return x,2*bandwidth


class LoRaPreambleTests(unittest.TestCase):
    def test_bw_sf_and_inverted_chirps_with_offset_noise(self):
        for sf,bw,inverted in ((7,125000,False),(9,250000,False),(12,125000,True),(8,500000,True)):
            x,fs = preamble(sf,bw,inverted)
            result = detect_lora_preamble(x,fs)
            matches = [c for c in result['candidates'] if c['parameters']['spreading_factor']==sf and c['parameters']['bandwidth_hz']==bw]
            self.assertTrue(matches, result)
            self.assertGreaterEqual(matches[0]['evidence']['repeated_chirps'],6)
            self.assertNotIn('frames',result)

    def test_noise_tone_and_short_chirps_abstain(self):
        rng = np.random.default_rng(72)
        noise = rng.normal(size=50000)+1j*rng.normal(size=50000)
        for x in (noise, signal.lfilter([1],[1,-.9],noise), np.exp(2j*np.pi*.1*np.arange(50000))):
            self.assertEqual(detect_lora_preamble(x,250000)['candidates'],[])
        x,fs = preamble()
        self.assertEqual(detect_lora_preamble(x[:1000],fs)['candidates'],[])

    def test_pipeline_exports_evidence_without_packets(self):
        from iqscope import analyze_samples
        x,fs = preamble()
        with tempfile.TemporaryDirectory() as directory:
            report = analyze_samples(x,fs,0,directory)
            trial = next(t for t in report['wideband_trials'] if t['decoder']=='lora_preamble')
            self.assertTrue(trial['candidates'])
            self.assertTrue((Path(directory)/report['lora_artifact']).exists())
            self.assertNotIn('frames',trial)

    def test_changing_css_symbols_are_not_a_preamble(self):
        rng = np.random.default_rng(73)
        n = np.arange(128)
        chirp = np.exp(1j*np.pi*(n*n/128-n))
        x = np.concatenate([np.roll(chirp, int(shift)) for shift in rng.integers(0,128,80)])
        self.assertEqual(detect_lora_preamble(x,125000)['candidates'], [])

    def test_unverified_encoding_is_preserved_in_chirp_artifact(self):
        import json
        from iqscope import analyze
        x,fs = preamble()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            x.astype('<c8').tofile(root/'input.sigmf-data')
            meta = {'global': {'core:datatype':'cf32_le', 'core:sample_rate':fs,
                    'iqscope:byte_order_status':'unverified_hypothesis'}}
            (root/'input.sigmf-meta').write_text(json.dumps(meta))
            report = analyze(root/'input.sigmf-meta', root/'results')
            artifact = json.loads((root/'results'/report['lora_artifact']).read_text())
            self.assertEqual(artifact['input_interpretation_status'],'unverified_byte_order_and_header_layout')
            self.assertNotIn('frames',artifact)

    def test_opposite_chirp_pair_after_preamble_and_sync_symbols(self):
        for inverted in (False,True):
            sf,bandwidth,length = 8,125000,256
            x,fs = synchronized_preamble(inverted)
            result = detect_lora_preamble(x,2*bandwidth)
            matches = [c for c in result['candidates'] if c['parameters']['spreading_factor']==sf and c['parameters']['bandwidth_hz']==bandwidth]
            self.assertTrue(matches,result)
            sync = matches[0]['synchronization']
            self.assertEqual(sync['status'],'opposite_chirp_pair_candidate',sync)
            self.assertLess(abs(sync['time_seconds']-(47/2+10*length)/bandwidth),length/bandwidth/4)

    def test_preamble_alone_and_single_opposite_chirp_do_not_confirm_pair(self):
        x,fs = preamble()
        result = detect_lora_preamble(x,fs)
        self.assertTrue(result['candidates'])
        self.assertTrue(all(c['synchronization']['status']=='no_consistent_opposite_pair' for c in result['candidates']))
        length=128
        n=np.arange(length)
        up=np.exp(1j*np.pi*(n*n/length-n))
        x=np.r_[np.tile(up,8),np.roll(up,8),np.roll(up,16),up.conj(),np.zeros(3*length)]
        result=detect_lora_preamble(x,125000)
        self.assertTrue(result['candidates'])
        self.assertTrue(all(c['synchronization']['status']=='no_consistent_opposite_pair' for c in result['candidates']))

    def test_sync_words_with_inversion_noise_and_different_spreading_factors(self):
        for word,sf,inverted in ((0x34,7,False),(0x12,8,True),(0x00,9,False),(0xAB,12,True)):
            x,fs = synchronized_preamble(inverted,word,sf)
            rng = np.random.default_rng(80)
            x += .01*(rng.normal(size=len(x))+1j*rng.normal(size=len(x)))
            result = detect_lora_preamble(x,fs)
            matches = [c for c in result['candidates'] if c['parameters']['spreading_factor']==sf and c['parameters']['bandwidth_hz']==125000]
            self.assertTrue(matches,result)
            sync = matches[0]['sync_word']
            self.assertEqual(sync['status'],'sync_word_candidate',sync)
            self.assertEqual(sync['value_hex'],f'{word:02X}')
            self.assertNotIn('frames',result)

    def test_nonconventional_sync_symbols_are_not_rounded_to_a_word(self):
        length=256
        t=np.arange(2*length)/2
        up=np.exp(2j*np.pi*(t*t/(2*length)-t/2))
        x=np.r_[np.zeros(47),np.tile(up,8),np.roll(up,-6),np.roll(up,-54),np.tile(up.conj(),2),up.conj()[:length//2],np.zeros(4*length)]
        result=detect_lora_preamble(x,250000)
        matches=[c for c in result['candidates'] if c['parameters']['spreading_factor']==8 and c['parameters']['bandwidth_hz']==125000]
        self.assertTrue(matches,result)
        self.assertEqual(matches[0]['synchronization']['status'],'opposite_chirp_pair_candidate')
        self.assertEqual(matches[0]['sync_word']['status'],'no_consistent_sync_word')

    def test_sync_word_with_varied_delays_and_carrier_offsets(self):
        for delay,cfo in ((0,0),(197,3.3),(773,-2.2)):
            x,fs=synchronized_preamble(False,0x34,8,125000,delay,cfo)
            result=detect_lora_preamble(x,fs)
            matches=[c for c in result['candidates'] if c['parameters']['spreading_factor']==8 and c['parameters']['bandwidth_hz']==125000]
            self.assertTrue(matches,result)
            self.assertEqual(matches[0]['sync_word'].get('value_hex'),'34',matches[0]['sync_word'])
