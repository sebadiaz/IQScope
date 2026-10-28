import unittest
from iqscope_lora_header import decode_explicit_header, _hamming_nibble

# Frozen transmit-side vectors: 17 bytes, CR4/5, payload CRC flag set,
# checksum 0x1B; nibbles 1,1,3,1,B. Extra SF8 nibble is zero.
HEADER_SF7 = [85,49,1,13,109,29,89,73]
HEADER_SF8 = [85,49,1,13,221,61,73,233]


class LoRaHeaderTests(unittest.TestCase):
    def test_frozen_explicit_header_vectors(self):
        for sf,vector in ((7,HEADER_SF7),(8,HEADER_SF8)):
            result=decode_explicit_header(vector,sf)
            self.assertEqual(result['status'],'header_checksum_valid',result)
            self.assertEqual(result['header_nibbles'],[1,1,3,1,11])
            self.assertEqual(result['payload_length_bytes'],17)
            self.assertEqual(result['coding_rate'],'4/5')
            self.assertTrue(result['payload_crc_present'])
            self.assertEqual(result['corrected_codeword_bits'],0)
            self.assertNotIn('frames',result)

    def test_hamming_corrects_single_errors_and_rejects_double_errors(self):
        codebook=[0x00,0x8B,0x4E,0xC5,0x2D,0xA6,0x63,0xE8,0x17,0x9C,0x59,0xD2,0x3A,0xB1,0x74,0xFF]
        for nibble,word in enumerate(codebook):
            self.assertEqual(_hamming_nibble(word),(nibble,0))
            for first in range(8):
                self.assertEqual(_hamming_nibble(word^(1<<first)),(nibble,1))
                for second in range(first+1,8):
                    self.assertIsNone(_hamming_nibble(word^(1<<first)^(1<<second)))

    def test_short_invalid_and_random_blocks_do_not_claim_frames(self):
        self.assertEqual(decode_explicit_header(HEADER_SF7[:7],7)['status'],'insufficient_symbols')
        self.assertEqual(decode_explicit_header([128]*8,7)['status'],'invalid_symbol_input')
        self.assertEqual(decode_explicit_header(HEADER_SF7,6)['status'],'not_applicable')
        self.assertNotEqual(decode_explicit_header([1]*8,7)['status'],'header_checksum_valid')

    def test_checksum_mismatch_is_rejected_after_valid_hamming(self):
        result=decode_explicit_header([41,49,1,13,105,29,101,85],7)
        self.assertEqual(result['status'],'header_checksum_mismatch')

    def test_one_codeword_bit_is_reported_as_corrected(self):
        result=decode_explicit_header([85,49,1,13,109,29,89,117],7)
        self.assertEqual(result['status'],'header_checksum_valid',result)
        self.assertEqual(result['corrected_codeword_bits'],1)
