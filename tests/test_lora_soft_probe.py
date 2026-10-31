import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from test_lora_payload import HELLO
from test_lora_quarter import WRONG_CRC

scripts=Path(__file__).parents[1]/'scripts'
with patch.object(sys,'path',[str(scripts)]+sys.path):
    from lora_soft_probe import infer_block,infer_payload


class SoftErasureResearchTests(unittest.TestCase):
    def test_real_research_block_recovers_without_expected_bytes_as_input(self):
        vector=json.loads(Path(__file__).with_name('lora_soft_research_vector.json').read_text())
        symbols=vector['symbols'];sf=vector['sf'];start=vector['block_start']
        result=infer_block(symbols[start:start+5],sf,vector['block_scores'])
        self.assertEqual(result['status'],'single_erasure_candidate')
        self.assertGreaterEqual(result['spectral_margin'],8)
        scores=np.ones((len(symbols),1<<sf));scores[start:start+5]=vector['block_scores']
        analysis=infer_payload(symbols,sf,scores)
        self.assertEqual(analysis['payload']['status'],'payload_crc_valid')
        self.assertEqual(analysis['payload']['payload_hex'],'30303030303030')
        self.assertEqual(analysis['payload_decode_calls'],1)

    def test_each_single_column_erasure_is_recoverable_by_parity_and_spectra(self):
        block=HELLO[7][8:13]
        for row in range(5):
            damaged=list(block);damaged[row]=(damaged[row]+17)%128
            scores=np.ones((5,128))
            for i,value in enumerate(block):scores[i,value]=20
            scores[row,block[row]]=10;scores[row,damaged[row]]=11
            result=infer_block(damaged,7,scores)
            self.assertEqual(result['symbols'],block)
            self.assertEqual(result['status'],'single_erasure_candidate')

    def test_ambiguity_is_not_resolved_with_crc(self):
        vector=json.loads(Path(__file__).with_name('lora_soft_research_vector.json').read_text())
        result=infer_payload(vector['symbols'],7,np.ones((23,128)))
        self.assertEqual(result['status'],'research_payload_unvalidated')
        self.assertEqual(result['selected_symbols'],vector['symbols'])

    def test_crc_outcome_cannot_change_spectral_selection(self):
        vector=json.loads(Path(__file__).with_name('lora_soft_research_vector.json').read_text())
        scores=np.ones((23,128));scores[13:18]=vector['block_scores']
        good=infer_payload(vector['symbols'],7,scores)
        with patch('iqscope_lora_payload.decode_payload',return_value={'status':'payload_crc_mismatch'}) as decode:
            bad=infer_payload(vector['symbols'],7,scores)
            decode.assert_called_once()
        self.assertEqual(good['selected_symbols'],bad['selected_symbols'])
        self.assertEqual(good['blocks'],bad['blocks'])
        self.assertEqual(bad['status'],'research_payload_unvalidated')

    def test_wrong_crc_with_consistent_parity_stays_wrong(self):
        result=infer_payload(WRONG_CRC,7,np.ones((len(WRONG_CRC),128)))
        self.assertEqual(result['payload']['status'],'payload_crc_mismatch')
        self.assertTrue(all(b['status']=='parity_already_consistent' for b in result['blocks']))

    def test_budgets_and_invalid_spectra_are_rejected(self):
        for scores in (np.zeros((4,128)),np.full((5,128),np.nan),-np.ones((5,128))):
            with self.assertRaises(ValueError):infer_block(HELLO[7][8:13],7,scores)
        with self.assertRaises(ValueError):infer_payload([0]*65,7,np.zeros((65,128)))

    def test_forensic_patches_are_restored_after_failure(self):
        import hashlib,tempfile
        import iqscope_lora as lora
        with patch.object(sys,'path',[str(scripts)]+sys.path):
            import loraiq_forensic_probe as probe
        before=(lora._opposite_chirp_pair,lora._sync_word_candidate,lora._data_symbol_candidates)
        with tempfile.TemporaryDirectory() as directory:
            meta=Path(directory)/'source.sigmf-meta';data=bytes(8192)
            meta.with_suffix('.sigmf-data').write_bytes(data)
            meta.write_text(json.dumps({'global':{'core:sha512':hashlib.sha512(data).hexdigest()}}))
            with patch.object(probe,'read_iq',return_value=(np.zeros(1024,complex),250000,0)),patch.object(lora,'detect_lora_preamble',side_effect=RuntimeError('diagnostic failure')):
                with self.assertRaises(RuntimeError):probe.run(meta)
        self.assertEqual(before,(lora._opposite_chirp_pair,lora._sync_word_candidate,lora._data_symbol_candidates))
