"""Bounded explicit LoRa CR4/5–4/8 payload decoding; no LoRaWAN parsing or decryption."""
from binascii import crc_hqx
from iqscope_lora_header import decode_explicit_header, _hamming_nibble, _CODEBOOK


_PAYLOAD_CODES = {
    1:tuple((int(f'{nibble:04b}'[::-1],2)<<1)|(nibble.bit_count()&1) for nibble in range(16)),
    2:tuple(word>>2 for word in _CODEBOOK),
    3:tuple(word>>1 for word in _CODEBOOK),
    4:_CODEBOOK,
}


def _decode_payload_word(word,coding_rate):
    distances=[(word^code).bit_count() for code in _PAYLOAD_CODES[coding_rate]]
    distance=min(distances)
    if distance>1 or distances.count(distance)!=1:
        return None
    return distances.index(distance),distance


def _deinterleave(symbols,width,sf,reduced):
    words=[0]*width
    for row,symbol in enumerate(symbols):
        value=(symbol-1)%(1<<sf)
        if reduced:
            value//=4
        value^=value>>1
        for column in range(width):
            words[(row-column-1)%width] |= ((value>>(width-column-1))&1)<<(len(symbols)-row-1)
    return words


def whitening_bytes(count):
    state=255
    result=[]
    for _ in range(count):
        result.append(state)
        feedback=((state>>7)^(state>>5)^(state>>4)^(state>>3))&1
        state=((state<<1)|feedback)&255
    return bytes(result)


def payload_crc(payload):
    if len(payload)<2:
        raise ValueError('This CRC convention requires at least two payload bytes')
    return crc_hqx(payload[:-2],0) ^ (payload[-2]<<8) ^ payload[-1]


def decode_payload(symbols,sf):
    base={'scope':'LoRa PHY bytes only; no LoRaWAN identity, authentication or decryption'}
    header=decode_explicit_header(symbols,sf)
    if header['status']!='header_checksum_valid':
        return dict(base,status='no_valid_explicit_header')
    if sf>10:
        return dict(base,status='unsupported_coding_rate_or_low_data_rate_mode')
    coding_rate=header['coding_rate_index']
    block_symbols=4+coding_rate
    length=header['payload_length_bytes']
    has_crc=header['payload_crc_present']
    if has_crc and length<2:
        return dict(base,status='unsupported_short_crc_payload')
    required_nibbles=2*(length+(2 if has_crc else 0))
    spill=sf-7
    blocks=max(0,(required_nibbles-spill+sf-1)//sf)
    required_symbols=8+block_symbols*blocks
    if len(symbols)<required_symbols:
        return dict(base,status='insufficient_symbols',required_symbols=required_symbols,available_symbols=len(symbols))
    if len(symbols)>64 or any(type(value) is not int or not 0<=value<(1<<sf) for value in symbols):
        return dict(base,status='invalid_or_oversized_symbol_input')
    nibbles=[]
    corrected=0
    corrected_payload=0
    for word in _deinterleave(symbols[:8],sf-2,sf,True)[5:5+required_nibbles]:
        decoded=_hamming_nibble(word)
        if decoded is None:
            return dict(base,status='uncorrectable_first_block_spillover')
        nibbles.append(decoded[0])
        corrected+=decoded[1]
    for start in range(8,required_symbols,block_symbols):
        for word in _deinterleave(symbols[start:start+block_symbols],sf,sf,False):
            if len(nibbles)>=required_nibbles:
                break
            decoded=_decode_payload_word(word,coding_rate)
            if decoded is None:
                return dict(base,status='payload_parity_mismatch' if coding_rate==1 else 'payload_codeword_uncorrectable')
            nibbles.append(decoded[0])
            corrected_payload+=decoded[1]
    raw=bytes(nibbles[index]|(nibbles[index+1]<<4) for index in range(0,required_nibbles,2))
    payload=bytes(a^b for a,b in zip(raw[:length],whitening_bytes(length)))
    if not has_crc:
        return dict(base,status='payload_without_crc',candidate_payload_hex=payload.hex(),payload_length_bytes=length)
    received=int.from_bytes(raw[length:length+2],'little')
    expected=payload_crc(payload)
    if received!=expected:
        return dict(base,status='payload_crc_mismatch',received_crc=received,calculated_crc=expected)
    result=dict(base,status='payload_crc_valid',payload_hex=payload.hex(),payload_length_bytes=length,
                received_crc=received,calculated_crc=expected,coding_rate=header['coding_rate'],coding_rate_index=coding_rate,corrected_spillover_bits=corrected,corrected_payload_codeword_bits=corrected_payload,
                symbols_consumed=required_symbols,validation='Header 5-bit checksum and LoRa payload CRC16 passed; not emitter authenticity')
    try:
        text=payload.decode('utf-8')
        if all(character.isprintable() or character in '\n\r\t' for character in text):
            result['text']=text
    except UnicodeDecodeError:
        pass
    return result
