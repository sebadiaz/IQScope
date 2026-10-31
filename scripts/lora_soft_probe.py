"""Research-only CR4/5 single-symbol erasure inference; never search using CRC."""
import numpy as np
from iqscope_lora_payload import _deinterleave


def infer_block(symbols,sf,scores,used_words=None):
    if type(sf) is not int or sf not in (7,8,9,10) or len(symbols)!=5:
        raise ValueError('Exactly five SF7-10 symbols are required')
    length=1<<sf
    if any(type(s) is not int or not 0<=s<length for s in symbols):
        raise ValueError('Invalid symbol')
    power=np.asarray(scores,dtype=float)
    if power.shape!=(5,length) or not np.all(np.isfinite(power)) or np.any(power<0):
        raise ValueError('Expected five finite nonnegative noise-normalized spectra')
    used_words=sf if used_words is None else used_words
    if type(used_words) is not int or not 1<=used_words<=sf:
        raise ValueError('Invalid used-word count')
    words=_deinterleave(symbols,sf,sf,False)
    syndrome=[word.bit_count()&1 if i<used_words else 0 for i,word in enumerate(words)]
    if not any(syndrome):
        return {'status':'parity_already_consistent','symbols':list(symbols),'candidates':[]}
    candidates=[]
    for row in range(5):
        value=(symbols[row]-1)%length
        gray=value^(value>>1)
        for column in range(sf):
            if syndrome[(row-column-1)%sf]:
                gray^=1<<(sf-column-1)
        binary=0
        while gray:
            binary^=gray
            gray>>=1
        replacement=(binary+1)%length
        loss=float(power[row,symbols[row]]-power[row,replacement])
        candidates.append({'row':row,'replacement':replacement,'spectral_loss':loss,
                           'replacement_score':float(power[row,replacement])})
    candidates.sort(key=lambda item:(item['spectral_loss'],item['row']))
    best=candidates[0]
    margin=candidates[1]['spectral_loss']-best['spectral_loss']
    accepted=margin>=8 and best['replacement_score']>=8
    result=list(symbols)
    if accepted:
        result[best['row']]=best['replacement']
    return {'status':'single_erasure_candidate' if accepted else 'ambiguous_or_weak_erasure',
            'symbols':result,'candidates':candidates,'spectral_margin':margin,
            'required_spectral_margin':8,'required_replacement_score':8,
            'scope':'One erasure hypothesis per symbol column, ranked by noise-normalized spectral loss. Heuristic; no payload bytes or CRC used.'}


def infer_payload(symbols,sf,scores):
    from iqscope_lora_header import decode_explicit_header
    if type(sf) is not int or sf not in (7,8,9,10) or not 8<=len(symbols)<=64:
        raise ValueError('Expected 8-64 SF7-10 symbols')
    power=np.asarray(scores,dtype=float)
    if power.shape!=(len(symbols),1<<sf) or not np.all(np.isfinite(power)) or np.any(power<0):
        raise ValueError('Invalid noise-normalized spectra')
    header=decode_explicit_header(symbols,sf)
    if header['status']!='header_checksum_valid' or header['coding_rate_index']!=1 or not header['payload_crc_present']:
        return {'status':'unsupported_or_invalid_header','header':header}
    remaining=2*(header['payload_length_bytes']+2)-(sf-7)
    blocks=max(0,(remaining+sf-1)//sf)
    required=8+5*blocks
    if len(symbols)<required:
        return {'status':'insufficient_symbols','required_symbols':required}
    selected=list(symbols[:required]);reports=[]
    for start in range(8,required,5):
        item=infer_block(list(symbols[start:start+5]),sf,power[start:start+5],min(sf,remaining))
        selected[start:start+5]=item['symbols']
        reports.append(dict(item,start_symbol_index=start))
        remaining-=sf
    # All spectral/parity decisions are complete before this single decode.
    from iqscope_lora_payload import decode_payload
    payload=decode_payload(selected,sf)
    return {'status':'research_crc_valid' if payload['status']=='payload_crc_valid' else 'research_payload_unvalidated',
            'selected_symbols':selected,'blocks':reports,'payload':payload,
            'payload_decode_calls':1,'crc_used_for_candidate_selection':False,
            'scope':'Research only. At most five single-column erasure candidates per CR4/5 block; no header correction or CRC-guided retries.'}
