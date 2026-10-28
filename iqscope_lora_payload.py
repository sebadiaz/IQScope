"""Bounded explicit LoRa CR4/5 payload decoding; no LoRaWAN parsing or decryption."""
from binascii import crc_hqx
from iqscope_lora_header import decode_explicit_header, _hamming_nibble


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
    if header['coding_rate_index']!=1 or sf>10:
        return dict(base,status='unsupported_coding_rate_or_low_data_rate_mode')
    length=header['payload_length_bytes']
    has_crc=header['payload_crc_present']
    if has_crc and length<2:
        return dict(base,status='unsupported_short_crc_payload')
    required_nibbles=2*(length+(2 if has_crc else 0))
    spill=sf-7
    blocks=max(0,(required_nibbles-spill+sf-1)//sf)
    required_symbols=8+5*blocks
    if len(symbols)<required_symbols:
        return dict(base,status='insufficient_symbols',required_symbols=required_symbols,available_symbols=len(symbols))
    if len(symbols)>64 or any(type(value) is not int or not 0<=value<(1<<sf) for value in symbols):
        return dict(base,status='invalid_or_oversized_symbol_input')
    nibbles=[]
    corrected=0
    for word in _deinterleave(symbols[:8],sf-2,sf,True)[5:5+required_nibbles]:
        decoded=_hamming_nibble(word)
        if decoded is None:
            return dict(base,status='uncorrectable_first_block_spillover')
        nibbles.append(decoded[0])
        corrected+=decoded[1]
    for start in range(8,required_symbols,5):
        for word in _deinterleave(symbols[start:start+5],sf,sf,False):
            if len(nibbles)>=required_nibbles:
                break
            # CR4/5 is data in reversed bit order plus even parity; detect, do not guess a correction.
            if word.bit_count()&1:
                return dict(base,status='payload_parity_mismatch')
            data=word>>1
            nibbles.append(int(f'{data:04b}'[::-1],2))
    raw=bytes(nibbles[index]|(nibbles[index+1]<<4) for index in range(0,required_nibbles,2))
    payload=bytes(a^b for a,b in zip(raw[:length],whitening_bytes(length)))
    if not has_crc:
        return dict(base,status='payload_without_crc',candidate_payload_hex=payload.hex(),payload_length_bytes=length)
    received=int.from_bytes(raw[length:length+2],'little')
    expected=payload_crc(payload)
    if received!=expected:
        return dict(base,status='payload_crc_mismatch',received_crc=received,calculated_crc=expected)
    result=dict(base,status='payload_crc_valid',payload_hex=payload.hex(),payload_length_bytes=length,
                received_crc=received,calculated_crc=expected,corrected_spillover_bits=corrected,
                symbols_consumed=required_symbols,validation='Header 5-bit checksum and LoRa payload CRC16 passed; not emitter authenticity')
    try:
        text=payload.decode('utf-8')
        if all(character.isprintable() or character in '\n\r\t' for character in text):
            result['text']=text
    except UnicodeDecodeError:
        pass
    return result
