import json
import tempfile
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from iqscope_lora import detect_lora_preamble
from iqscope_lora_experimental import detect_guarded_lora
from iqscope import analyze_samples
from test_lora import synchronized_preamble
from test_lora_payload import HELLO,RATE_VECTORS


class ExperimentalIntegrationTests(unittest.TestCase):
    def test_pipeline_exports_experimental_bytes_and_labels_mode(self):
        x,fs=synchronized_preamble(sf=7,offset=0,cfo_bins=0,data_symbols=HELLO[7])
        with tempfile.TemporaryDirectory() as directory:
            r=analyze_samples(x,fs,0,directory,experimental_lora=True)
            self.assertTrue(r['analysis_options']['experimental_lora'])
            trial=next(t for t in r['wideband_trials'] if t['decoder']=='lora_preamble')
            self.assertEqual(trial['mode'],'experimental_guarded')
            self.assertEqual((Path(directory)/trial['frames'][0]['artifact']).read_bytes(),b'HELLO')
            self.assertTrue(trial['frames'][0]['experimental_mode'])
            artifact=json.loads((Path(directory)/r['lora_artifact']).read_text())
            self.assertEqual(artifact['mode'],'experimental_guarded')
            self.assertTrue(all('noise_normalized_spectra' not in c['data_symbols'] for c in artifact['candidates']))

    def test_existing_cr48_payload_and_fec_are_preserved(self):
        x,fs=synchronized_preamble(offset=0,cfo_bins=0,data_symbols=RATE_VECTORS['8-4-1-bit-errors'])
        r=detect_guarded_lora(x,fs)
        self.assertEqual(r['frames'][0]['payload_hex'],b'HELLO'.hex())
        self.assertEqual(r['frames'][0]['coding_rate'],'4/8')
        self.assertEqual(r['frames'][0]['corrected_payload_codeword_bits'],1)

    def test_parallel_policies_do_not_mutate_default_functions_or_output(self):
        import iqscope_lora as lora
        x,fs=synchronized_preamble(sf=7,offset=0,cfo_bins=.19,data_symbols=HELLO[7])
        before=detect_lora_preamble(x,fs)
        functions=(lora._opposite_chirp_pair,lora._sync_word_candidate,lora._data_symbol_candidates)
        with ThreadPoolExecutor(max_workers=2) as pool:
            a=pool.submit(detect_lora_preamble,x,fs)
            b=pool.submit(detect_guarded_lora,x,fs)
            self.assertEqual(a.result(),before)
            self.assertEqual(b.result()['frames'][0]['payload_hex'],b'HELLO'.hex())
        self.assertEqual(functions,(lora._opposite_chirp_pair,lora._sync_word_candidate,lora._data_symbol_candidates))
        self.assertEqual(detect_lora_preamble(x,fs),before)
