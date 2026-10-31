import sys
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from test_lora_payload import HELLO

scripts=Path(__file__).parents[1]/'scripts'
with patch.object(sys,'path',[str(scripts)]+sys.path):
    from lora_soft_probe import infer_payload
    from lora_iq_policy_audit import waveform,inspect
    from loraiq_forensic_probe import analyse_samples


class GuardedResearchTests(unittest.TestCase):
    def test_clean_packet_does_not_become_an_ambiguous_weak_hypothesis(self):
        x,fs=waveform('valid_strong',138700)
        for samples in (x,x.conj()):
            result=inspect(samples,fs)
            self.assertTrue(any(p['payload_hex']=='48454c4c4f' for p in result['accepted_research_payloads']))
        report=analyse_samples(x,fs,guarded=True)
        self.assertNotIn('frames',report)
        self.assertEqual(report['status'],'research_observations_only')
        self.assertTrue(any(c['sync_word'].get('research_policy_branch')=='existing_physical_sync' for c in report['candidates']))

    def test_bad_header_bad_crc_and_truncation_stay_unvalidated(self):
        for kind in ('bad_header','bad_crc','truncated_payload'):
            x,fs=waveform(kind,138700)
            self.assertEqual(inspect(x,fs)['accepted_research_payloads'],[])

    def test_low_spectral_evidence_is_rejected_before_crc_decode(self):
        with patch('iqscope_lora_payload.decode_payload',return_value={'status':'payload_crc_valid'}) as decode:
            result=infer_payload(HELLO[7],7,np.ones((18,128)),minimum_mean_score=8)
            decode.assert_not_called()
        self.assertEqual(result['status'],'research_evidence_rejected')
        self.assertEqual(result['payload_decode_calls'],0)

    def test_missing_quarter_is_not_claimed_as_detected(self):
        x,fs=waveform('missing_quarter',138700)
        result=inspect(x,fs)
        self.assertTrue(result['accepted_research_payloads'])
        self.assertTrue(all(not p['quarter_chirp_validated'] for p in result['accepted_research_payloads']))
