"""POCSAG standard words and independently encoded synthetic FSK references."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from iqscope_pocsag import decode_pocsag, valid_codeword

SYNC = 0x7CD215D8
IDLE = 0x7A89C197
CAPCODE = 1234567
TEXT = 'IQSCOPE <b>42</b>'


def encoded_word(information):
    # Streaming polynomial register, independent of the decoder's division.
    register = 0
    for bit in [int(c) for c in f'{information:021b}']+[0]*10:
        outgoing = register & 0x200
        register = ((register << 1) | bit) & 0x3FF
        if outgoing:
            register ^= 0x369
    block = (information << 10) | register
    return (block << 1) | (bin(block).count('1') % 2)


def message_words(text=TEXT, capcode=CAPCODE, function=3, address_slot=None):
    slot = 2*(capcode & 7) if address_slot is None else address_slot
    address = encoded_word(((capcode >> 3) << 2) | function)
    if function == 0:
        alphabet = '0123456789?U -]['
        payload = ''.join(f'{alphabet.index(c):04b}'[::-1] for c in text)
        while len(payload) % 20:
            payload += '0011'  # Space (code 12), LSB first.
    else:
        payload = ''.join(''.join(str((ord(c) >> b) & 1) for b in range(7)) for c in text+'\0')
        payload += '0' * (-len(payload) % 20)
    data = [encoded_word((1 << 20) | int(payload[i:i+20], 2)) for i in range(0, len(payload), 20)]
    return [IDLE]*slot+[address]+data+[IDLE]


def transmission(words=None, prefix='101010'*96):
    words = message_words() if words is None else list(words)
    words += [IDLE]*(-len(words) % 16)
    return prefix+''.join(f'{SYNC:032b}'+''.join(f'{w:032b}' for w in words[i:i+16])
                          for i in range(0, len(words), 16))


def candidate(bits, baud=1200, origin=.125):
    return dict(bits=bits, parameters=dict(baud=baud, first_symbol_center_seconds=origin),
                channel=dict(offset_hz=35000, frequency_hz=153035000, sample_rate=24000))


def reference_pocsag_iq(fs=24000, baud=1200, inverted=False, text=TEXT, function=3, bits_override=None):
    bits = (bits_override if bits_override is not None else transmission(message_words(text=text, function=function)))+'10'*64
    states = np.array(list(map(int, bits)))
    if inverted:
        states = 1-states
    indices = np.floor((np.arange(int(len(bits)*fs/baud))-2.3)*baud/fs).astype(int)
    tones = 175+(2*states[np.clip(indices, 0, len(states)-1)]-1)*4500
    iq = np.exp(2j*np.pi*np.cumsum(tones)/fs)
    rng = np.random.default_rng(584)
    iq += .006*(rng.normal(size=len(iq))+1j*rng.normal(size=len(iq)))
    return iq.astype(np.complex64)


class PocsagTests(unittest.TestCase):
    def test_standard_idle_sync_and_every_single_bit_error(self):
        self.assertTrue(valid_codeword(IDLE))
        self.assertTrue(valid_codeword(SYNC))
        self.assertEqual(encoded_word(IDLE >> 11), IDLE)
        for word in (IDLE, encoded_word(0), encoded_word(0x1FFFFF)):
            self.assertTrue(valid_codeword(word))
            for bit in range(32):
                self.assertFalse(valid_codeword(word ^ (1 << bit)))
            self.assertFalse(valid_codeword(word ^ 3))  # Even parity alone is insufficient.

    def test_alpha_cross_word_and_batch_boundaries_and_provenance(self):
        bits = transmission()
        original = candidate(bits); untouched = deepcopy(original)
        result = decode_pocsag([original])
        self.assertEqual(original, untouched)
        self.assertEqual(len(result['messages']), 1, result)
        m = result['messages'][0]
        self.assertEqual(m['fields']['text'], TEXT)
        self.assertEqual(m['fields']['capcode'], CAPCODE)
        self.assertEqual(m['address_frame'], 7)
        self.assertEqual(m['fields']['function'], 3)
        self.assertEqual(m['batch_sync_bit_starts'], [576, 1120])
        self.assertEqual(m['bit_start'], 576+32+14*32)
        self.assertAlmostEqual(m['time_seconds'], .125+m['bit_start']/1200)
        self.assertEqual(m['channel'], original['channel'])
        self.assertEqual(m['corrected_bits'], 0)
        self.assertTrue(m['bch_valid'] and m['even_parity_valid'])
        json.dumps(result, allow_nan=False)

    def test_numeric_symbols_spare_and_preserved_padding(self):
        for text in ('0123456789U -][', '12?'):
            m = decode_pocsag([candidate(transmission(message_words(text=text, function=0)))])['messages'][0]
            self.assertEqual(m['fields']['text'], text.replace('?', '\ufffd')+' '*(-len(text) % 5))
            self.assertEqual(m['fields']['reserved_character_present'], '?' in text)
            self.assertEqual(m['fields']['message_format'], 'numeric')

    def test_all_frame_numbers_and_odd_address_slots(self):
        for group in range(8):
            for second_slot in (0, 1):
                capcode = (3456 << 3) | group
                words = message_words(capcode=capcode, address_slot=group*2+second_slot)
                m = decode_pocsag([candidate(transmission(words))])['messages'][0]
                self.assertEqual(m['fields']['capcode'], capcode)
                self.assertEqual(m['address_frame'], group)

    def test_both_polarities_rates_and_nonstandard_rates(self):
        bits = transmission()
        for baud in (512, 1200, 2400):
            for inverted in (False, True):
                stream = bits.translate(str.maketrans('01', '10')) if inverted else bits
                result = decode_pocsag([candidate('001'+stream, baud=baud*1.001)])
                self.assertEqual(len(result['messages']), 1)
                self.assertEqual(result['messages'][0]['nominal_baud'], baud)
                self.assertEqual(result['messages'][0]['polarity'], 'inverted' if inverted else 'normal')
        for baud in (300, 600, 9600, float('nan')):
            self.assertFalse(decode_pocsag([candidate(bits, baud=baud)])['messages'])

    def test_corrupt_address_payload_and_terminator_discard_whole_message(self):
        words = message_words(capcode=0)
        for index in range(len(words)):
            for mask in (1, 1 << 17, 3):
                damaged = words.copy(); damaged[index] ^= mask
                result = decode_pocsag([candidate(transmission(damaged))], max_corrected_bits=0)
                self.assertFalse(result['messages'], (index, mask))
                self.assertGreater(result['invalid_codewords'], 0)

    def test_missing_continuation_sync_and_truncation_never_export_prefix(self):
        bits = transmission()
        damaged = bits[:1120]+f'{SYNC ^ 1:032b}'+bits[1152:]
        self.assertFalse(decode_pocsag([candidate(damaged)])['messages'])
        for cut in (1088, 1120, 1180):
            self.assertFalse(decode_pocsag([candidate(bits[:cut])])['messages'])
            self.assertFalse(decode_pocsag([candidate(bits[cut:])])['messages'])

    def test_unknown_function_keeps_bits_without_text_and_tone_only(self):
        for function in (1, 2):
            fields = decode_pocsag([candidate(transmission(message_words(function=function)))])['messages'][0]['fields']
            self.assertEqual(fields['message_format'], 'unspecified_function')
            self.assertNotIn('text', fields)
            self.assertGreater(fields['payload_bit_count'], 0)
        words = [encoded_word((77 << 2) | 3), IDLE]
        fields = decode_pocsag([candidate(transmission(words))])['messages'][0]['fields']
        self.assertEqual(fields['message_format'], 'tone_only')
        self.assertEqual(fields['capcode'], 77 << 3)

    def test_new_address_terminates_and_repetitions_and_candidates_stay_distinct(self):
        words = message_words(capcode=0)[:-1]+message_words(capcode=8)
        result = decode_pocsag([candidate(transmission(words))])
        self.assertEqual(len(result['messages']), 2)
        self.assertEqual(result['messages'][0]['termination'], 'next_address')
        # The second address occupies frame 4, so its three low bits are 100.
        self.assertEqual([m['fields']['capcode'] for m in result['messages']], [0, 12])
        result = decode_pocsag([candidate(transmission()), candidate(transmission())])
        self.assertEqual([m['candidate_index'] for m in result['messages']], [0, 1])
        repeated = decode_pocsag([candidate(transmission()+transmission())])
        self.assertEqual(len(repeated['messages']), 2)

    def test_budgets_and_random_bits(self):
        bits = transmission()+transmission()
        for option in ({'max_syncs': 1}, {'max_words': 15}, {'max_message_words': 2}, {'max_messages': 0}):
            self.assertFalse(decode_pocsag([candidate(bits)], **option)['messages'])
        limited = decode_pocsag([candidate(bits)], max_messages=1)
        self.assertEqual(len(limited['messages']), 1)
        self.assertTrue(limited['budget_exhausted'])
        self.assertTrue(decode_pocsag([candidate(bits)], max_bits=600)['input_budget_reached'])
        rng = np.random.default_rng(584)
        random = ''.join(map(str, rng.integers(0, 2, 100000).tolist()))
        self.assertFalse(decode_pocsag([candidate(random)])['messages'])
        self.assertFalse(decode_pocsag([candidate(f'{SYNC:032b}'+f'{IDLE:032b}'*16)])['messages'])

    def test_fsk_frontend_all_rates_and_polarities(self):
        from iqscope_fsk import decode_fsk
        for baud in (512, 1200, 2400):
            for inverted in (False, True):
                trial = decode_fsk(reference_pocsag_iq(baud=baud, inverted=inverted), 24000)
                result = decode_pocsag(trial['candidates'])
                self.assertEqual(len(result['messages']), 1, (baud, inverted, trial['status']))
                self.assertEqual(result['messages'][0]['fields']['text'], TEXT)

    def test_complete_pipeline_artifact(self):
        from iqscope import analyze_samples
        with tempfile.TemporaryDirectory() as directory:
            report = analyze_samples(reference_pocsag_iq(), 24000, 153000000, directory)
            trial = next(t for t in report['wideband_trials'] if t['decoder'] == 'pocsag')
            self.assertEqual(len(trial['messages']), 1)
            self.assertEqual(trial['messages'][0]['fields']['text'], TEXT)
            self.assertEqual(json.loads((Path(directory)/trial['artifact']).read_text()), trial)
            saved = json.loads((Path(directory)/'report.json').read_text())
            self.assertEqual(next(t for t in saved['wideband_trials'] if t['decoder']=='pocsag'), trial)

    def test_corruption_does_not_prevent_a_later_independent_message(self):
        words = message_words(); words[15] ^= 1 << 23
        result = decode_pocsag([candidate(transmission(words)+transmission())], max_corrected_bits=0)
        self.assertEqual(len(result['messages']), 1)
        self.assertEqual(result['messages'][0]['fields']['text'], TEXT)
        self.assertGreater(result['incomplete_messages'], 0)

    def test_wideband_channel_retains_rf_frequency_and_source_time(self):
        from iqscope import analyze_samples
        from scipy import signal
        fs = 192000
        iq = reference_pocsag_iq(fs=fs)
        # Independent transmit low-pass; unfiltered abrupt FSK sidelobes can
        # exceed the existing detector's 24 kHz channel eligibility limit.
        iq = signal.convolve(iq, signal.firwin(257, 7000, fs=fs), mode='same')
        time = np.arange(len(iq))/fs
        iq = iq*np.exp(2j*np.pi*35000*time)+2*np.exp(-2j*np.pi*43000*time)
        rng = np.random.default_rng(77)
        iq += .01*(rng.normal(size=len(iq))+1j*rng.normal(size=len(iq)))
        with tempfile.TemporaryDirectory() as directory:
            report = analyze_samples(iq, fs, 153000000, directory)
            trial = next(t for t in report['wideband_trials'] if t['decoder']=='pocsag')
            self.assertEqual(len(trial['messages']), 1, trial)
            message = trial['messages'][0]
            self.assertEqual(message['fields']['text'], TEXT)
            self.assertAlmostEqual(message['channel']['frequency_hz'], 153035175, delta=20)
            self.assertAlmostEqual(message['time_seconds'], 1056/1200, delta=.002)


if __name__ == '__main__':
    unittest.main()
