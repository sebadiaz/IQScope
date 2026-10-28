import binascii
import unittest
from iqscope_lora_payload import decode_payload, whitening_bytes, payload_crc

# Frozen transmitter-side vectors: conventional reduced-rate first block,
# whitened low-nibble-first payload and unwhitened CRC bytes (32 83 for HELLO).
HELLO = {
7:[17,13,125,1,1,17,5,5,54,102,33,71,85,38,107,0,81,73],
8:[237,113,193,1,13,33,13,13,155,179,49,173,91,10,251,1,61,34],
9:[273,141,449,61,13,65,25,29,179,346,25,151,430,3,511,1,0,256],
10:[749,369,961,65,13,129,53,61,602,685,13,780,631,1,1,1,256,128],
}
NO_CRC=[113,49,125,13,61,17,53,1,54,102,33,71,85,6,126,0,96,49]
BINARY=[225,77,221,29,49,37,129,73,183,186,130,184,72,5,255,2,129,96]


class LoRaPayloadTests(unittest.TestCase):
    def test_frozen_payload_vectors_and_first_block_spillover(self):
        for sf,symbols in HELLO.items():
            result=decode_payload(symbols,sf)
            self.assertEqual(result['status'],'payload_crc_valid',result)
            self.assertEqual(result['payload_hex'],'48454c4c4f')
            self.assertEqual(result['text'],'HELLO')
            self.assertEqual(result['received_crc'],0x8332)
        result=decode_payload(BINARY,8)
        self.assertEqual(result['status'],'payload_crc_valid',result)
        self.assertEqual(result['payload_hex'],'0020ff41')
        self.assertNotIn('text',result)

    def test_crc_uses_independent_standard_crc_primitive(self):
        self.assertEqual(binascii.crc_hqx(b'123456789',0),0x31c3)
        self.assertEqual(payload_crc(b'HELLO'),0x8332)
        with self.assertRaises(ValueError):
            payload_crc(b'x')

    def test_whitening_sequence_prefix(self):
        self.assertEqual(whitening_bytes(16).hex(),'fffefcf8f0e1c2850b172f5ebc78f1e3')

    def test_truncation_and_no_crc_do_not_validate_payload(self):
        self.assertEqual(decode_payload(HELLO[7][:-1],7)['status'],'insufficient_symbols')
        result=decode_payload(NO_CRC,7)
        self.assertEqual(result['status'],'payload_without_crc')
        self.assertEqual(result['candidate_payload_hex'],'48454c4c4f')
        self.assertNotIn('payload_hex',result)

    def test_corrupted_payload_is_not_validated(self):
        for index in range(8,18):
            corrupted=HELLO[7].copy()
            corrupted[index]=(corrupted[index]+4)%128
            self.assertNotEqual(decode_payload(corrupted,7)['status'],'payload_crc_valid')

    def test_iq_chain_recovers_known_payload_with_crc(self):
        from test_lora import synchronized_preamble
        from iqscope_lora import detect_lora_preamble
        for sf,inverted in ((7,False),(8,True)):
            x,fs=synchronized_preamble(inverted,sf=sf,offset=0,cfo_bins=0,data_symbols=HELLO[sf])
            result=detect_lora_preamble(x,fs)
            self.assertTrue(result.get('frames'),result)
            self.assertEqual(result['frames'][0]['payload_hex'],'48454c4c4f')

    def test_wrong_crc_with_valid_payload_parity_is_rejected(self):
        symbols=[17,13,125,1,1,17,5,5,54,102,33,71,85,27,107,0,81,76]
        self.assertEqual(decode_payload(symbols,7)['status'],'payload_crc_mismatch')

    def test_pipeline_exports_exact_crc_valid_bytes(self):
        import tempfile
        from pathlib import Path
        from test_lora import synchronized_preamble
        from iqscope import analyze_samples
        x,fs=synchronized_preamble(sf=8,offset=0,cfo_bins=0,data_symbols=HELLO[8])
        with tempfile.TemporaryDirectory() as directory:
            report=analyze_samples(x,fs,0,directory)
            trial=next(t for t in report['wideband_trials'] if t['decoder']=='lora_preamble')
            self.assertEqual(len(trial['frames']),1)
            self.assertEqual((Path(directory)/trial['frames'][0]['artifact']).read_bytes(),b'HELLO')

    def test_unverified_input_warning_survives_valid_crc_export(self):
        import json,tempfile
        from pathlib import Path
        from test_lora import synchronized_preamble
        from iqscope import analyze
        x,fs=synchronized_preamble(sf=8,offset=0,cfo_bins=0,data_symbols=HELLO[8])
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            x.astype('<c8').tofile(root/'input.sigmf-data')
            (root/'input.sigmf-meta').write_text(json.dumps({'global':{'core:datatype':'cf32_le','core:sample_rate':fs,'iqscope:byte_order_status':'unverified_hypothesis'}}))
            report=analyze(root/'input.sigmf-meta',root/'results')
            artifact=json.loads((root/'results'/report['lora_artifact']).read_text())
            frame=artifact['frames'][0]
            self.assertEqual(frame['input_interpretation_status'],'unverified_byte_order_and_header_layout')
            self.assertEqual((root/'results'/frame['artifact']).read_bytes(),b'HELLO')
