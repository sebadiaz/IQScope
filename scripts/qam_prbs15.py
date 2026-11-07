"""Known-pattern laboratory measurement, separate from blind QAM demodulation.

Acquire a bit labeling and PN phase on a prefix; evaluate a disjoint suffix.
This does not identify a protocol or correct/relabel the runtime QAM exports.
"""
import hashlib
import itertools
import numpy as np
from scipy import fft

PERIOD=32767
ACQUISITION_BITS=2048


def prbs15_period():
    """Reciprocal PRBS15 convention: b[n] = b[n-14] XOR b[n-15]."""
    bits=np.ones(PERIOD,dtype=np.uint8)
    for n in range(15,PERIOD):bits[n]=bits[n-14]^bits[n-15]
    return bits


def check_prbs15(symbols):
    values=np.asarray(symbols)
    if values.ndim!=1 or values.dtype.kind not in 'iu' or np.any((values<0)|(values>15)):
        raise ValueError('Expected integer square-QAM labels from 0 to 15')
    labels=values[:10000].astype(np.uint8)
    result={'status':'not_enough_bits','analyzed_symbols':len(labels),'symbol_budget_reached':len(values)>len(labels),
            'acquisition_bits':ACQUISITION_BITS,'evaluation_bits':max(0,4*len(labels)-ACQUISITION_BITS),
            'reference':'PRBS15, period 32767; canonical recurrence b[n]=b[n-14] XOR b[n-15], all-one initial state; both time directions searched',
            'scope':'known test-pattern consistency only; no CRC, protocol identification or authenticated transmitter',
            'fit_scope':'labeling, sequence direction and phase selected only on acquisition prefix; evaluation suffix never used for selection'}
    if len(labels)<1024:return result
    ranks=np.arange(16,dtype=np.uint8)
    i=ranks//4;q=ranks%4
    masks=((np.arange(16)[:,None]>>np.arange(3,-1,-1))&1).astype(np.uint8)
    prefix=labels[:ACQUISITION_BITS//4]
    scored=[]
    # 4 axis-code combinations x 24 bit permutations x 16 XOR masks.
    for gray_i,gray_q in itertools.product((False,True),repeat=2):
        a=i^(i>>1) if gray_i else i
        b=q^(q>>1) if gray_q else q
        base=np.column_stack((a>>1,a&1,b>>1,b&1)).astype(np.uint8)
        for order in itertools.permutations(range(4)):
            tables=base[:,order][None,:,:]^masks[:,None,:]
            streams=tables[:,prefix,:].reshape(16,-1)
            for reverse,lag in ((False,14),(True,1)):
                syndrome=streams[:,15:]^streams[:,15-lag:-lag]^streams[:,:-15]
                errors=np.count_nonzero(syndrome,axis=1)
                for m,error in enumerate(errors):
                    scored.append((int(error),reverse,tables[m].copy()))
    shortlisted=sorted(scored,key=lambda v:v[0])[:8]
    canonical=prbs15_period()
    references=(canonical,canonical[::-1])
    spectra=[fft.rfft(1-2*r.astype(float)) for r in references]
    trials=[]
    for syndrome_errors,reverse,table in shortlisted:
        bits=table[labels].reshape(-1)
        training=1-2*bits[:ACQUISITION_BITS].astype(float)
        correlation=fft.irfft(np.conj(fft.rfft(training,n=PERIOD))*spectra[int(reverse)],n=PERIOD)
        phase=int(np.argmax(correlation))
        reference=references[int(reverse)][(phase+np.arange(len(bits)))%PERIOD]
        train_errors=int(np.count_nonzero(bits[:ACQUISITION_BITS]!=reference[:ACQUISITION_BITS]))
        trials.append((train_errors,phase,reverse,table,bits,reference,syndrome_errors))
    # Never use the evaluation suffix to choose a mapping or phase.
    train_errors,phase,reverse,table,bits,reference,syndrome_errors=min(trials,key=lambda t:t[0])
    errors=int(np.count_nonzero(bits[ACQUISITION_BITS:]!=reference[ACQUISITION_BITS:]))
    ber=errors/result['evaluation_bits']
    result.update(status='prbs15_consistent' if train_errors/ACQUISITION_BITS<=.1 and ber<=.1 else 'no_consistent_prbs15',
                  mapping_hypotheses=len(scored),phase_acquisitions=len(shortlisted),
                  label_to_nibble=(table@np.array([8,4,2,1])).tolist(),
                  canonical_sequence_reversed=bool(reverse),phase_index=phase,
                  acquisition_syndrome_errors=syndrome_errors,acquisition_error_count=train_errors,
                  evaluation_error_count=errors,evaluation_ber=ber,
                  recovered_bits_sha256=hashlib.sha256(np.packbits(bits,bitorder='big').tobytes()).hexdigest(),
                  predicted_bits_sha256=hashlib.sha256(np.packbits(reference,bitorder='big').tobytes()).hexdigest(),
                  hash_convention='all analyzed bits packed MSB-first; zero padding to complete the final byte')
    return result
