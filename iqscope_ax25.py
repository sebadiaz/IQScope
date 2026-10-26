"""Bounded AX.25 UI frame extraction from candidate binary-FSK tone bits."""


def crc_x25(data):
    crc = 0xffff
    for octet in data:
        crc ^= octet
        for _ in range(8):
            crc = (crc>>1)^0x8408 if crc&1 else crc>>1
    return crc^0xffff


def unstuff(bits):
    out,ones = [],0
    for bit in bits:
        if ones==5:
            if bit!='0':
                return None
            ones = 0
            continue
        out.append(bit)
        ones = ones+1 if bit=='1' else 0
    if ones==5 or len(out)%8:
        return None
    return bytes(sum(int(out[i+j])<<j for j in range(8)) for i in range(0,len(out),8))


def parse_ui(data):
    addresses = []
    cursor = 0
    for _ in range(10):
        address = data[cursor:cursor+7]
        if len(address)!=7 or any(octet&1 for octet in address[:6]) or address[6]&0x60!=0x60:
            return None
        name = ''.join(chr(octet>>1) for octet in address[:6])
        if not name.rstrip() or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 ' for c in name):
            return None
        # Spaces are permitted only as trailing callsign padding.
        if ' ' in name.rstrip():
            return None
        addresses.append({'callsign':name.rstrip(),'ssid':(address[6]>>1)&15,
                          'high_bit':bool(address[6]&128)})
        cursor += 7
        if address[6]&1:
            break
    else:
        return None
    if len(addresses)<2 or len(data)<cursor+2 or data[cursor]&0xef!=3:
        return None
    payload = data[cursor+2:]
    if len(payload)>256:
        return None
    fields = {'destination':addresses[0],'source':addresses[1],'via':addresses[2:],
              'control':data[cursor],'pid':data[cursor+1],'frame_type':'UI',
              'payload_hex':payload.hex()}
    if fields['pid']==0xf0:
        # UI text is an interpretation, not proof of APRS or sender identity.
        fields['text'] = ''.join(c if c.isprintable() or c in '\r\n\t' else '\ufffd'
                                 for c in payload.decode('utf-8',errors='replace'))
    return fields


def decode_ax25(candidates,max_frames=128,max_flag_pairs=2000):
    frames = []
    examined = 0
    exhausted = False
    rejected_crc = 0
    for candidate_index,candidate in enumerate(candidates):
        tone_bits = candidate['bits']
        nrzi = ''.join('1' if a==b else '0' for a,b in zip(tone_bits,tone_bits[1:]))
        streams = [('nrzi',nrzi,1),('nrz',tone_bits,0),
                   ('nrz_inverted',tone_bits.translate(str.maketrans('01','10')),0)]
        for coding,bits,origin_shift in streams:
            previous = bits.find('01111110')
            while previous>=0:
                following = bits.find('01111110',previous+8)
                if following<0:
                    break
                if examined>=max_flag_pairs or len(frames)>=max_frames:
                    exhausted = True
                    break
                examined += 1
                start,end = previous+8,following
                previous = following
                if not 18*8<=end-start<=330*8*6//5:
                    continue
                packet = unstuff(bits[start:end])
                if packet is None or len(packet)<18 or len(packet)>330:
                    continue
                if crc_x25(packet[:-2])!=int.from_bytes(packet[-2:],'little'):
                    rejected_crc += 1
                    continue
                fields = parse_ui(packet[:-2])
                if fields is None:
                    continue
                p = candidate['parameters']
                # The NRZI bit is associated with its second tone symbol.
                bit_start = start+origin_shift
                frames.append({'decoder':'ax25_ui','hex':packet.hex(),'fields':fields,
                               'line_coding':coding,'fcs':'CRC-16/X-25','fcs_valid':True,
                               'candidate_index':candidate_index,'bit_start':bit_start,
                               'time_seconds':p['first_symbol_center_seconds']+bit_start/p['baud'],
                               'channel':candidate.get('channel'),
                               'validation_scope':'FCS and AX.25 UI structure; sender authenticity and APRS semantics not established'})
            if exhausted:
                break
        if exhausted:
            break
    return {'decoder':'ax25_ui','family':'AX.25 UI','status':'validated_frames' if frames else 'no_valid_frames',
            'frames':frames,'flag_pairs_examined':examined,'crc_rejected':rejected_crc,
            'budget_exhausted':exhausted,'frame_budget':max_frames,'flag_pair_budget':max_flag_pairs,
            'limitations':['AX.25 UI only, at most ten addresses and 256 payload octets; NRZI/NRZ trials on recovered 2-FSK bits.',
                           'No AFSK-over-FM frontend, G3RUH descrambler, connected-mode frames or APRS field parsing.',
                           'Upstream demodulation may miss frames; a valid CRC does not authenticate an emitter.',
                           'Wideband detection can merge sidelobes into a band >24 kHz and exclude even a low-baud signal.']}
