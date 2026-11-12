"""Extended BCH distance checks and conservative whole-message correction."""
from itertools import combinations
import tempfile
import unittest

from iqscope_pocsag import decode_pocsag, repair_codeword, valid_codeword
from test_pocsag import IDLE, candidate, encoded_word, message_words, transmission, TEXT, reference_pocsag_iq


class PocsagBchTests(unittest.TestCase):
    def test_all_single_and_double_error_positions_on_reference_words(self):
        for original in (0, IDLE, encoded_word(0x1FFFFF), 0x4B5A1A25):
            self.assertTrue(valid_codeword(original))
            self.assertEqual(repair_codeword(original), (original, []))
            for count in (1, 2):
                for positions in combinations(range(32), count):
                    mask = sum(1 << bit for bit in positions)
                    self.assertEqual(repair_codeword(original ^ mask),
                                     (original, sorted(32-bit for bit in positions)))

    def test_every_three_bit_pattern_is_rejected_on_reference_words(self):
        for original in (0, IDLE, encoded_word(0x1FFFFF)):
            for positions in combinations(range(32), 3):
                mask = sum(1 << bit for bit in positions)
                self.assertIsNone(repair_codeword(original ^ mask))

    def test_strict_and_one_bit_limits(self):
        self.assertIsNone(repair_codeword(IDLE ^ 1, max_errors=0))
        self.assertEqual(repair_codeword(IDLE ^ 1, max_errors=1), (IDLE, [32]))
        self.assertIsNone(repair_codeword(IDLE ^ 3, max_errors=1))
        for limit in (-1, 3, 100):
            with self.assertRaises(ValueError):
                repair_codeword(IDLE, limit)
            with self.assertRaises(ValueError):
                decode_pocsag([], max_corrected_bits=limit)

    def test_address_data_terminator_repairs_keep_original_words(self):
        original = message_words(capcode=0)
        for index, role in ((0, 'address'), (1, 'message'), (len(original)-1, 'terminator')):
            for mask in (1, 0x80000001):
                words = original.copy(); words[index] ^= mask
                result = decode_pocsag([candidate(transmission(words))])
                self.assertEqual(len(result['messages']), 1)
                message = result['messages'][0]
                self.assertEqual(message['fields']['text'], TEXT)
                self.assertEqual(message['fields']['capcode'], 0)
                self.assertEqual(message['corrected_bits'], mask.bit_count())
                self.assertFalse(message['received_bch_parity_valid'])
                self.assertEqual(message['validation_stage'], 'after_BCH_correction')
                evidence = message['corrections'][0]
                self.assertEqual(evidence['role'], role)
                self.assertEqual(evidence['received_hex'], f'{words[index]:08X}')
                self.assertEqual(evidence['corrected_hex'], f'{original[index]:08X}')
                self.assertEqual(evidence['bit_positions_1_based'], [32] if mask==1 else [1, 32])
                if role=='terminator':
                    self.assertEqual(message['terminator_hex'], f'{words[index]:08X}')
                    self.assertEqual(message['decoded_terminator_hex'], f'{IDLE:08X}')
                else:
                    self.assertEqual(message['codewords_hex'][index], f'{words[index]:08X}')
                    self.assertEqual(message['decoded_codewords_hex'][index], f'{original[index]:08X}')
                self.assertTrue(all(valid_codeword(int(w, 16)) for w in message['decoded_codewords_hex']))

    def test_total_budget_includes_terminator_and_resets_for_next_message(self):
        original = message_words(capcode=0)
        for indices in ((0, 1), (1, len(original)-1)):
            words = original.copy()
            for index in indices: words[index] ^= 1
            result = decode_pocsag([candidate(transmission(words))])
            self.assertEqual(result['messages'][0]['corrected_bits'], 2)
            limited = decode_pocsag([candidate(transmission(words))], max_corrected_bits=1)
            self.assertFalse(limited['messages'])
            self.assertEqual(limited['correction_budget_rejected'], 1)
        for changes in (((0,1),(1,1),(len(original)-1,1)), ((0,3),(1,3))):
            words = original.copy()
            for index, mask in changes: words[index] ^= mask
            result = decode_pocsag([candidate(transmission(words)+transmission(original))])
            self.assertEqual(len(result['messages']), 1)
            self.assertEqual(result['messages'][0]['corrected_bits'], 0)
            self.assertTrue(result['messages'][0]['received_bch_parity_valid'])
            self.assertGreater(result['correction_budget_rejected'], 0)

    def test_sync_is_never_corrected_and_three_bad_bits_drop_the_message(self):
        bits = transmission()
        for index in (576, 1120):
            damaged = bits[:index]+('0' if bits[index]=='1' else '1')+bits[index+1:]
            self.assertFalse(decode_pocsag([candidate(damaged)])['messages'])
        words = message_words(capcode=0); words[1] ^= 7
        result = decode_pocsag([candidate(transmission(words))])
        self.assertFalse(result['messages'])
        self.assertGreater(result['invalid_codewords'], 0)

    def test_shared_address_terminator_has_provenance_for_both_messages(self):
        first = message_words(capcode=0)[:-1]
        words = first+message_words(capcode=8)
        words[len(first)] ^= 1
        messages = decode_pocsag([candidate(transmission(words))])['messages']
        self.assertEqual(len(messages), 2)
        self.assertEqual([m['fields']['capcode'] for m in messages], [0, 12])
        self.assertEqual([m['corrected_bits'] for m in messages], [1, 1])
        self.assertEqual([m['corrections'][0]['role'] for m in messages], ['terminator', 'address'])
        self.assertEqual(messages[0]['corrections'][0]['received_hex'], messages[1]['corrections'][0]['received_hex'])

    def test_automatic_iq_and_audio_paths_recover_two_data_bit_errors(self):
        from iqscope import analyze_samples
        from iqscope_pocsag_audio import decode_pocsag_audio
        from test_pocsag_audio import reference_audio
        words = message_words(); words[15] ^= (1 << 15) | (1 << 11)
        bits = transmission(words)
        audio_trial = decode_pocsag_audio(reference_audio(bits_override=bits), 8000)
        self.assertEqual(audio_trial['messages'][0]['fields']['text'], TEXT)
        self.assertEqual(audio_trial['messages'][0]['corrected_bits'], 2)
        with tempfile.TemporaryDirectory() as directory:
            report = analyze_samples(reference_pocsag_iq(bits_override=bits), 24000, 0, directory)
            message = next(t for t in report['wideband_trials'] if t['decoder']=='pocsag')['messages'][0]
            self.assertEqual(message['fields']['text'], TEXT)
            self.assertEqual(message['corrected_bits'], 2)


if __name__ == '__main__':
    unittest.main()
