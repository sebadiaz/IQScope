"""Strict POCSAG batch/message extraction from recovered binary FSK bits.

ITU-R M.584-2 Annex 1. Bounded extended-BCH correction, no heuristic character
set or state between analyses. Parity checks do not authenticate a transmitter.
"""
import json
import math
from functools import lru_cache
from itertools import combinations
from pathlib import Path

SYNC = 0x7CD215D8
IDLE = 0x7A89C197
_INVERT = str.maketrans('01', '10')
_NUMERIC = '0123456789\ufffdU -]['


def _syndrome(word):
    """Ten BCH remainder bits plus the overall parity bit."""
    remainder = word >> 1
    for bit in range(30, 9, -1):
        if remainder & (1 << bit):
            remainder ^= 0x769 << (bit-10)
    return (remainder << 1) | (word.bit_count() & 1)


def valid_codeword(word):
    """Check BCH(31,21), generator x^10+x^9+x^8+x^6+x^5+x^3+1, and parity."""
    return _syndrome(word) == 0


@lru_cache(maxsize=1)
def _correction_masks():
    table = {0: 0}
    for weight in (1, 2):
        for positions in combinations(range(32), weight):
            mask = sum(1 << bit for bit in positions)
            syndrome = _syndrome(mask)
            # Unique syndromes are required. Never choose between alternatives.
            if syndrome in table:
                raise AssertionError('Ambiguous extended-BCH correction table')
            table[syndrome] = mask
    return table


def repair_codeword(word, max_errors=2):
    """Return (checked word, changed MSB-first positions 1..32), or None.

    This bounded-distance decision is not proof of the transmitted word when
    more errors occurred than the decoding radius. The received word is kept.
    """
    if max_errors not in (0, 1, 2):
        raise ValueError('POCSAG correction limit must be 0, 1 or 2 bits')
    syndrome = _syndrome(word)
    if syndrome == 0:
        return word, []
    if max_errors == 0:
        return None
    mask = _correction_masks().get(syndrome)
    if mask is None or mask.bit_count() > max_errors:
        return None
    corrected = word ^ mask
    if not valid_codeword(corrected):
        return None
    return corrected, sorted(32-bit for bit in range(32) if mask & (1 << bit))


def _message_fields(pending):
    words = pending['words']
    payload = ''.join(f'{(word >> 11) & 0xFFFFF:020b}' for word in words[1:])
    fields = {'capcode': pending['capcode'], 'function': pending['function'],
              'payload_bits': payload, 'payload_bit_count': len(payload)}
    if not payload:
        fields['message_format'] = 'tone_only'
    elif fields['function'] == 0:
        codes = [int(payload[i:i+4][::-1], 2) for i in range(0, len(payload), 4)]
        fields.update(message_format='numeric', character_codes=codes,
                      text=''.join(_NUMERIC[code] for code in codes),
                      reserved_character_present=10 in codes,
                      padding_note='Trailing spaces may be message padding; preserved.')
    elif fields['function'] == 3:
        codes = [int(payload[i:i+7][::-1], 2) for i in range(0, len(payload)-6, 7)]
        text = []
        for code in codes:
            if code in (0, 3, 4):
                break
            text.append(chr(code) if 32 <= code < 127 or code in (9, 10, 13) else '\ufffd')
        fields.update(message_format='ia5', character_codes=codes,
                      text=''.join(text), trailing_bits=payload[len(codes)*7:],
                      character_set='IA5 / basic ASCII; national remappings not inferred')
    else:
        fields['message_format'] = 'unspecified_function'
    return fields


def decode_pocsag(candidates, max_messages=64, max_syncs=128, max_words=8192,
                  max_message_words=128, max_bits=100000, max_candidates=8,
                  max_corrected_bits=2):
    """Require exact sync and valid address, payload and terminating codewords.

    Messages can span batches with exact sync at the expected 544-bit spacing.
    Missing terminators or uncorrectable words discard an open message; no
    partial payload is promoted. At most two corrected bits across address,
    payload and terminator, not two per word. Zero selects strict received bits.
    """
    messages = []
    if max_corrected_bits not in (0, 1, 2):
        raise ValueError('POCSAG correction limit must be 0, 1 or 2 bits')
    counts = dict(syncs_examined=0, codewords_examined=0, invalid_codewords=0,
                  incomplete_messages=0, orphan_message_codewords=0,
                  message_word_limit_rejected=0, lost_batch_syncs=0,
                  received_invalid_codewords=0, correction_budget_rejected=0)
    exhausted = max_messages <= 0 or max_syncs <= 0 or max_words <= 0
    input_limited = len(candidates) > max_candidates
    sync_bits = f'{SYNC:032b}'
    for candidate_index, candidate in enumerate(candidates[:max_candidates]):
        parameters = candidate.get('parameters', {})
        baud = parameters.get('baud', 0)
        origin = parameters.get('first_symbol_center_seconds', 0)
        if not (isinstance(baud, (int, float)) and math.isfinite(baud) and baud > 0
                and isinstance(origin, (int, float)) and math.isfinite(origin)):
            continue
        nominal = min((512, 1200, 2400), key=lambda rate: abs(rate-baud))
        if abs(baud/nominal-1) > .03:
            continue
        source = candidate.get('bits', '')
        input_limited |= len(source) > max_bits
        source = source[:max_bits]
        if not source or any(bit not in '01' for bit in source):
            continue
        for inverted in (False, True):
            bits = source.translate(_INVERT) if inverted else source
            search_from = 0
            while not exhausted:
                sync_start = bits.find(sync_bits, search_from)
                if sync_start < 0:
                    break
                pending = None
                cursor = sync_start
                while True:
                    if counts['syncs_examined'] >= max_syncs:
                        exhausted = True
                        break
                    counts['syncs_examined'] += 1
                    batch_start = cursor
                    if pending is not None:
                        pending['batch_sync_bit_starts'].append(batch_start)
                    cursor += 32
                    for slot in range(16):
                        if cursor+32 > len(bits):
                            break
                        if counts['codewords_examined'] >= max_words:
                            exhausted = True
                            break
                        word_start = cursor
                        received = int(bits[cursor:cursor+32], 2)
                        cursor += 32
                        counts['codewords_examined'] += 1
                        if not valid_codeword(received):
                            counts['received_invalid_codewords'] += 1
                        repaired = repair_codeword(received, max_corrected_bits)
                        if repaired is None:
                            counts['invalid_codewords'] += 1
                            counts['incomplete_messages'] += int(pending is not None)
                            pending = None
                            continue
                        word, changed = repaired
                        correction = dict(bit_start=word_start, received_hex=f'{received:08X}',
                                          corrected_hex=f'{word:08X}', bit_positions_1_based=changed)
                        if word == IDLE or word >> 31 == 0:
                            if pending is not None and pending['corrected_bits']+len(changed) > max_corrected_bits:
                                counts['correction_budget_rejected'] += 1
                                counts['incomplete_messages'] += 1
                                pending = None
                            if pending is not None:
                                corrected_bits = pending['corrected_bits']+len(changed)
                                corrections = pending['corrections']+([dict(correction, role='terminator')] if changed else [])
                                messages.append({
                                    'decoder': 'pocsag', 'fields': _message_fields(pending),
                                    'codewords_hex': [f'{w:08X}' for w in pending['received_words']],
                                    'terminator_hex': f'{received:08X}',
                                    'decoded_codewords_hex': [f'{w:08X}' for w in pending['words']],
                                    'decoded_terminator_hex': f'{word:08X}',
                                    'termination': 'idle' if word == IDLE else 'next_address',
                                    'candidate_index': candidate_index,
                                    'bit_start': pending['bit_start'],
                                    'time_seconds': origin+pending['bit_start']/baud,
                                    'time_reference': 'first address bit center relative to capture',
                                    'address_frame': pending['address_frame'],
                                    'batch_sync_bit_starts': pending['batch_sync_bit_starts'],
                                    'baud': baud, 'nominal_baud': nominal,
                                    'polarity': 'inverted' if inverted else 'normal',
                                    'channel': candidate.get('channel'),
                                    'validation_scope': 'exact batch sync; BCH(31,21) and even parity after bounded correction on address, payload and terminator; no CRC or authentication',
                                    'validation_stage': 'after_BCH_correction' if corrected_bits else 'received_words',
                                    'received_bch_parity_valid': corrected_bits == 0,
                                    'bch_valid': True, 'even_parity_valid': True,
                                    'corrected_bits': corrected_bits, 'corrections': corrections,
                                })
                                pending = None
                                if len(messages) >= max_messages:
                                    exhausted = True
                                    break
                            if word != IDLE:
                                pending = dict(words=[word], received_words=[received],
                                               corrected_bits=len(changed),
                                               corrections=[dict(correction, role='address')] if changed else [],
                                               capcode=(((word >> 13) & 0x3FFFF) << 3) | (slot//2),
                                               function=(word >> 11) & 3,
                                               bit_start=word_start, address_frame=slot//2,
                                               batch_sync_bit_starts=[batch_start])
                        elif pending is not None:
                            if pending['corrected_bits']+len(changed) > max_corrected_bits:
                                counts['correction_budget_rejected'] += 1
                                counts['incomplete_messages'] += 1
                                pending = None
                            elif len(pending['words']) >= max_message_words:
                                counts['message_word_limit_rejected'] += 1
                                counts['incomplete_messages'] += 1
                                pending = None
                            else:
                                pending['words'].append(word)
                                pending['received_words'].append(received)
                                pending['corrected_bits'] += len(changed)
                                if changed:
                                    pending['corrections'].append(dict(correction, role='message'))
                        else:
                            counts['orphan_message_codewords'] += 1
                    else:
                        # Only a complete batch permits continuation of an open message.
                        if bits[cursor:cursor+32] == sync_bits:
                            continue
                        if pending is not None:
                            counts['lost_batch_syncs'] += 1
                    counts['incomplete_messages'] += int(pending is not None)
                    break
                # Do not scan inside an already consumed batch or duplicate its messages.
                search_from = max(sync_start+32, cursor)
            if exhausted:
                break
        if exhausted:
            break
    return dict(decoder='pocsag', family='POCSAG',
                status='checked_messages' if messages else 'no_checked_messages',
                messages=messages, **counts, budget_exhausted=exhausted,
                input_budget_reached=input_limited,
                budgets=dict(messages=max_messages, syncs=max_syncs, codewords=max_words,
                             words_per_message=max_message_words, bits_per_candidate=max_bits,
                             candidates=max_candidates, corrected_bits_per_message=max_corrected_bits),
                limitations=['512/1200/2400 baud (+/-3%) NRZ on existing stationary 2-FSK candidates only.',
                             'Exact sync; unique syndrome correction bounded to at most two bits over the complete message including its terminator.',
                             'With errors beyond this radius a different valid word can be selected; FEC is not a CRC or authentication.',
                             'No state across analyses; incomplete, uncorrectable or over-budget messages are discarded.',
                             'Standard function 0 numeric and 3 IA5 only; functions 1/2 retain raw bits.',
                             'Synthetic IQ validation only; no recorded POCSAG RF corpus validated.'])


def write_pocsag_artifact(trial, out):
    if trial['messages']:
        trial['artifact'] = 'pocsag-messages.json'
        (Path(out)/trial['artifact']).write_text(json.dumps(trial, indent=2), encoding='utf-8')
