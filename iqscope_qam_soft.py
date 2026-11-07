"""Bounded square-16-QAM likelihoods; no protocol, CRC or pattern correction."""
import numpy as np
from scipy.special import logsumexp

_ranks=np.arange(16)
POINTS=((2*(_ranks//4)-3)+1j*(2*(_ranks%4)-3))/np.sqrt(10)


def _samples(values):
    values=np.asarray(values,dtype=np.complex128)
    if values.ndim!=1 or not 1<=len(values)<=10000 or not np.all(np.isfinite(values)):
        raise ValueError('Expected 1 to 10000 finite complex symbols')
    return values


def estimate_awgn(values,iterations=32):
    values=_samples(values)
    if not 1<=iterations<=32 or np.mean(abs(values)**2)<1e-15:raise ValueError('Invalid model-fit budget or power')
    gain=1+0j
    nearest=np.argmin(abs(values[:,None]-POINTS[None,:]),axis=1)
    variance=max(float(np.mean(abs(values-POINTS[nearest])**2)),1e-5)
    for _ in range(iterations):
        distance=abs(values[:,None]-gain*POINTS[None,:])**2
        logits=-distance/max(variance,1e-5)
        weights=np.exp(logits-logits.max(axis=1,keepdims=True))
        weights/=weights.sum(axis=1,keepdims=True)
        mean=weights@POINTS
        energy=weights@(abs(POINTS)**2)
        gain=np.sum(values*np.conj(mean))/np.sum(energy)
        variance=float(np.sum(weights*abs(values[:,None]-gain*POINTS[None,:])**2)/len(values))
    if not .5<abs(gain)<2:raise ValueError('Unbounded blind gain estimate')
    return {'gain_i':float(gain.real),'gain_q':float(gain.imag),
            'noise_variance_complex':max(variance,1e-9),'iterations':iterations,
            'fit_scope':'unlabelled supplied symbols; uniform square-16-QAM circular-AWGN model'}


def bit_llrs(values,label_to_nibble=None,*,gain=1+0j,noise_variance=1.):
    """log P(bit=0|sample) / P(bit=1|sample), MSB first, clipped to +/-80."""
    values=_samples(values)
    mapping=np.arange(16) if label_to_nibble is None else np.asarray(label_to_nibble)
    if mapping.shape!=(16,) or mapping.dtype.kind not in 'iu' or set(mapping.tolist())!=set(range(16)):
        raise ValueError('Bit labeling must be a permutation of 0 through 15')
    if not np.isfinite(gain) or abs(gain)<1e-12 or not np.isfinite(noise_variance) or noise_variance<=0:
        raise ValueError('Invalid gain or complex noise variance')
    metrics=-abs(values[:,None]-gain*POINTS[None,:])**2/noise_variance
    bits=(mapping[:,None]>>np.arange(3,-1,-1))&1
    output=np.column_stack([logsumexp(metrics[:,bits[:,column]==0],axis=1)-
                            logsumexp(metrics[:,bits[:,column]==1],axis=1) for column in range(4)])
    return np.clip(output,-80,80).reshape(-1)
