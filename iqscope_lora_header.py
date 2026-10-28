"""Bounded LoRa explicit-header hypotheses; a header checksum is not a packet CRC."""
from numbers import Integral
from functools import reduce

_BASIS = (0x8B, 0x4E, 0x2D, 0x17)
_CODEBOOK = tuple(reduce(int.__xor__,
                  (basis for bit,basis in enumerate(_BASIS) if nibble & (1<<bit)),0)
                  for nibble in range(16))


def _hamming_nibble(word):
    distances = [(word^code).bit_count() for code in _CODEBOOK]
    distance = min(distances)
    if distance>1 or distances.count(distance)!=1:
        return None
    return distances.index(distance),distance


def decode_explicit_header(symbols,sf):
    base = {'scope':'Explicit-header hypothesis only; no payload CRC, bytes or emitter identity validated'}
    if not isinstance(sf,Integral) or isinstance(sf,bool) or not 7<=sf<=12:
        return dict(base,status='not_applicable')
    if len(symbols)<8:
        return dict(base,status='insufficient_symbols',required_symbols=8)
    length = 1<<sf
    block = symbols[:8]
    if any(not isinstance(value,Integral) or isinstance(value,bool) or not 0<=value<length for value in block):
        return dict(base,status='invalid_symbol_input')
    reduced = [((int(value)-1)%length)//4 for value in block]
    gray = [value^(value>>1) for value in reduced]
    width = sf-2
    words = [0]*width
    for row,value in enumerate(gray):
        for column in range(width):
            bit = (value>>(width-1-column))&1
            words[(row-column-1)%width] |= bit<<(7-row)
    decoded = [_hamming_nibble(word) for word in words[:5]]
    if any(value is None for value in decoded):
        return dict(base,status='uncorrectable_header_codeword')
    nibbles = [value[0] for value in decoded]
    corrected = sum(value[1] for value in decoded)
    payload_length = nibbles[0]*16+nibbles[1]
    coding_rate = nibbles[2]>>1
    if payload_length==0 or not 1<=coding_rate<=4 or nibbles[3]&14:
        return dict(base,status='invalid_header_fields')
    data = nibbles[0]<<8 | nibbles[1]<<4 | nibbles[2]
    expected = 0
    for mask in (0xF00,0x8E1,0x49A,0x257,0x12F):
        expected = expected*2+((data&mask).bit_count()&1)
    observed = (nibbles[3]&1)*16+nibbles[4]
    if expected!=observed:
        return dict(base,status='header_checksum_mismatch',corrected_codeword_bits=corrected)
    return dict(base,status='header_checksum_valid',payload_length_bytes=payload_length,
                coding_rate_index=coding_rate,coding_rate=f'4/{4+coding_rate}',
                payload_crc_present=bool(nibbles[2]&1),header_checksum=observed,
                corrected_codeword_bits=corrected,header_nibbles=nibbles,
                validation='5-bit header checksum only; payload is not decoded or validated')
