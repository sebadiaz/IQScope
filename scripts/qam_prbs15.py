"""Known-pattern laboratory measurement, separate from blind QAM demodulation.

Acquire a bit labeling and PN phase on a prefix; evaluate a disjoint suffix.
This does not identify a protocol or correct/relabel the runtime QAM exports.
"""
import hashlib
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
    prefix=labels[:ACQUISITION_BITS//4]
    counts=np.bincount(prefix,minlength=16)
    result['minimum_acquisition_label_occurrences']=int(counts.min())
    if counts.min()<8:return dict(result,status='insufficient_label_coverage')
    # For each PN phase, infer each label's four bits from their prefix-only
    # correlations. This permits cross-axis and nonlinear bit labelings.
    impulses=np.zeros((16,PERIOD))
    impulses[prefix,4*np.arange(len(prefix))]=1
    indicator_spectrum=np.conj(fft.rfft(impulses,axis=1))
    canonical=prbs15_period()
    references=(canonical,canonical[::-1])
    trials=[]
    for reverse,reference in enumerate(references):
        correlation=fft.irfft(indicator_spectrum*fft.rfft(1-2*reference.astype(float))[None,:],n=PERIOD,axis=1)
        correlation=np.rint(correlation).astype(np.int16)
        tables=np.zeros((16,PERIOD),dtype=np.uint8)
        scores=np.zeros(PERIOD,dtype=np.int32)
        for bit in range(4):
            lane=np.roll(correlation,-bit,axis=1)
            tables=(tables<<1)|(lane<0)
            scores+=np.abs(lane).sum(axis=0,dtype=np.int32)
        ordered=np.sort(tables,axis=0)
        bijective=np.all(ordered[1:]!=ordered[:-1],axis=0)
        # A non-bijective majority table is never accepted. No assignment
        # optimization is attempted for that phase.
        eligible=np.where(bijective,scores,-1)
        phase=int(np.argmax(eligible if bijective.any() else scores))
        trials.append((int((ACQUISITION_BITS-scores[phase])//2),phase,bool(reverse),
                       tables[:,phase].copy(),bool(bijective[phase]),int(bijective.sum())))
    # Never use the evaluation suffix to choose a mapping or phase.
    train_errors,phase,reverse,table,is_bijective,eligible_count=min(trials,key=lambda t:(not t[4],t[0]))
    bits=((table[labels,None]>>np.arange(3,-1,-1))&1).astype(np.uint8).reshape(-1)
    reference=references[int(reverse)][(phase+np.arange(len(bits)))%PERIOD]
    errors=int(np.count_nonzero(bits[ACQUISITION_BITS:]!=reference[ACQUISITION_BITS:]))
    ber=errors/result['evaluation_bits']
    result.update(status='prbs15_consistent' if is_bijective and train_errors/ACQUISITION_BITS<=.1 and ber<=.1 else 'no_consistent_prbs15',
                  phase_hypotheses=2*PERIOD,label_mapping_method='per-label bit majority per PN phase; retain bijective tables',
                  mapping_is_bijective=is_bijective,eligible_phase_tables_in_selected_direction=eligible_count,
                  label_to_nibble=table.tolist(),
                  canonical_sequence_reversed=bool(reverse),phase_index=phase,
                  acquisition_error_count=train_errors,
                  evaluation_error_count=errors,evaluation_ber=ber,
                  recovered_bits_sha256=hashlib.sha256(np.packbits(bits,bitorder='big').tobytes()).hexdigest(),
                  predicted_bits_sha256=hashlib.sha256(np.packbits(reference,bitorder='big').tobytes()).hexdigest(),
                  hash_convention='all analyzed bits packed MSB-first; zero padding to complete the final byte')
    return result
