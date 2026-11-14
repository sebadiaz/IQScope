"""Independent published ISS packet bits; these tests do not demodulate a recording."""
import unittest

from iqscope_ax25 import decode_ax25
from scripts.aprs_radio_reference import EXPECTED_HEX, EXPECTED_TEXT, SOURCE_BYTES, verify_source

# Pinned Berkeley course mirror notebook, printed output of findPackets.
PUBLISHED_NRZ = '0111111001100001010001010000001000000010000000100000001000000110001001010110010100000110010010010110010101100101100001111100000000000111101111100010000010010010101001001011001010110010100000010010110100000001001001001001110110001011101010011001001110011101101000011000101110100101101111011001110110100001100011011000000100110010100000111010000110110001101010011000000100110010100010111010000110001011101001011011110110011101101101111100010000101111110'


def decode(bits):
    return decode_ax25([dict(bits=bits, parameters=dict(baud=1200, first_symbol_center_seconds=0))])


class AprsRadioReferenceTests(unittest.TestCase):
    def test_independent_published_packet_bytes_and_text(self):
        result = decode(PUBLISHED_NRZ)
        self.assertEqual(len(result['frames']), 1)
        frame = result['frames'][0]
        self.assertEqual(frame['hex'], EXPECTED_HEX)
        self.assertTrue(frame['fcs_valid'])
        self.assertEqual(frame['fields']['text'], EXPECTED_TEXT)
        self.assertEqual(frame['fields']['source']['callsign'], 'RS0ISS')
        self.assertEqual(frame['fields']['destination']['callsign'], 'CQ')
        self.assertNotIn('aprs', frame['fields'])  # Status text is not a numeric position.

    def test_damaged_recorded_packet_bits_are_rejected(self):
        index = 200
        damaged = PUBLISHED_NRZ[:index]+str(1-int(PUBLISHED_NRZ[index]))+PUBLISHED_NRZ[index+1:]
        self.assertEqual(decode(damaged)['frames'], [])

    def test_download_integrity_rejects_wrong_size_and_wrong_blob(self):
        for data in (b'not a WAV', bytes(SOURCE_BYTES)):
            with self.assertRaisesRegex(ValueError, 'size/Git blob'):
                verify_source(data)
