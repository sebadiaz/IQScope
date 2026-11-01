import unittest
from unittest.mock import patch
import numpy as np
from iqscope_psk import decode_psk
from iqscope_psk_audio import search_audio_psk


def candidate(bad=False):
    from test_ax25 import frame,hdlc
    state=register=0
    bits=[]
    for bit in hdlc(frame(bad=bad)):
        state^=int(bit=='0')
        value=state^((register>>11)&1)^((register>>16)&1)
        bits.append(str(value));register=((register<<1)|value)&0x1ffff
    return {'modulation':'BPSK','bits':''.join(bits),
            'parameters':{'baud':1200,'first_symbol_center_seconds':.005,'carrier_offset_hz':1500}}


class PskContextTests(unittest.TestCase):
    def test_context_replacement_requires_real_crc(self):
        for corrupted in (False,True):
            primary={'status':'timing_consistent_candidate','candidates':[candidate(True)]}
            retry={'status':'timing_consistent_candidate','candidates':[candidate(corrupted)]}
            audio=np.r_[np.zeros(4000),np.ones(8000),np.zeros(4000)]
            with patch('iqscope_psk_audio.decode_psk',side_effect=[primary,retry]) as decoder:
                report=search_audio_psk(audio,8000)
            info=report['windows_examined'][0]
            self.assertEqual(info['context_retry']['accepted_by_ax25_crc'],not corrupted)
            chosen=report['candidates'][0]
            expected_start=info['source_sample_start'] if corrupted else info['context_retry']['source_sample_start']
            self.assertEqual(chosen['source_window']['source_sample_start'],expected_start)
            self.assertAlmostEqual(chosen['parameters']['first_symbol_center_seconds'],expected_start/8000+.005)
            self.assertAlmostEqual(decoder.call_args.kwargs['quality_start_seconds'],.1)
            self.assertLessEqual(decoder.call_args.kwargs['max_seconds'],3.1)

    def test_invalid_context_is_rejected(self):
        for value in (-1,float('nan'),float('inf')):
            with self.assertRaises(ValueError):
                decode_psk(np.ones(16000),16000,quality_start_seconds=value)

    def test_context_excludes_empty_prefix_from_quality(self):
        from test_psk_rrc import fixture
        from test_psk import equivalent
        x,fs,expected,_=fixture(2)
        x=np.r_[np.zeros(int(.1*fs)),x]
        report=decode_psk(x,fs,quality_start_seconds=.1)
        self.assertTrue(report['candidates'],report)
        c=report['candidates'][0]
        self.assertEqual(c['evidence']['quality_start_seconds'],.1)
        first=c['parameters']['first_symbol_center_seconds']
        index=max(0,int(np.ceil((.1-first)*c['parameters']['baud'])))+12
        self.assertTrue(equivalent(c['symbols'][index:-12],expected,2))
        self.assertLessEqual(c['evidence']['symbol_evm_rms'],.16)
