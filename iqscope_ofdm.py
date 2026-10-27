"""Bounded cyclic-prefix repetition evidence, not an OFDM protocol decoder."""
import numpy as np
from scipy import signal


def detect_cyclic_prefix(x,fs,max_samples=262144):
    base = {'decoder':'ofdm_cp','family':'Cyclic-prefix repetition / OFDM compatible','candidates':[]}
    if not np.isfinite(fs) or fs<=0 or len(x)<2048:
        return dict(base,status='not_applicable')
    original = len(x)
    if not isinstance(max_samples, int) or not 2048 <= max_samples <= 262144:
        return dict(base,status='not_applicable',reason='sample budget must be an integer from 2048 to 262144')
    total = min(original,max_samples)
    count = min(3, (original+131071)//131072)
    sizes = [total//count + (i < total%count) for i in range(count)]
    # Non-overlapping windows, including both ends, with a strict aggregate budget.
    starts = [sum(sizes[:i]) + (round(i*(original-total)/(count-1)) if count>1 else 0)
              for i in range(count)]
    candidates = []
    trials = 0
    windows = []
    for start,size in zip(starts,sizes):
        block = np.asarray(x[start:start+size],dtype=np.complex128)
        if not np.all(np.isfinite(block)):
            return dict(base,status='not_applicable',reason='nonfinite samples in a selected window')
        block = block-np.mean(block)
        power = abs(block)**2
        _,psd = signal.welch(block,fs,nperseg=min(1024,len(block)),return_onesided=False)
        occupied = float(np.sum(psd)**2/max(len(psd)*np.sum(psd**2),1e-30))
        windows.append({'sample_start':int(start),'sample_count':len(block),'effective_spectral_bin_fraction':occupied})
        if occupied<.05 or np.mean(power)<1e-20:
            continue
        for useful in (16,32,64,128,256,512,1024,2048):
            if useful>=len(block):
                continue
            products = block[:-useful]*np.conj(block[useful:])
            for guard in sorted({useful//divisor for divisor in (4,8,16,32) if useful//divisor>=2}):
                period = useful+guard
                cycles = len(products)//period
                if cycles<32:
                    continue
                trials += 1
                count = cycles*period
                correlation = np.mean(products[:count].reshape(cycles,period),axis=0)
                first_energy = np.mean(power[:count].reshape(cycles,period),axis=0)
                second_energy = np.mean(power[useful:useful+count].reshape(cycles,period),axis=0)
                profile = abs(correlation)/np.maximum(np.sqrt(first_energy*second_energy),1e-20)
                wrapped = np.r_[profile,profile[:guard-1]]
                cumulative = np.r_[0,np.cumsum(wrapped)]
                band = (cumulative[guard:]-cumulative[:-guard])/guard
                phase = int(np.argmax(band))
                peak = float(band[phase])
                mask = np.ones(period,dtype=bool)
                mask[(phase+np.arange(-guard,2*guard))%period] = False
                background = float(np.median(profile[mask]))
                contrast = peak-background
                if peak<.6 or contrast<.35:
                    continue
                indices = (phase+np.arange(guard))%period
                halves = []
                matrix = products[:count].reshape(cycles,period)
                a = power[:count].reshape(cycles,period)
                b = power[useful:useful+count].reshape(cycles,period)
                for part in (slice(0,cycles//2),slice(cycles//2,None)):
                    numerator = abs(np.sum(matrix[part][:,indices]))
                    denominator = np.sqrt(np.sum(a[part][:,indices])*np.sum(b[part][:,indices]))
                    halves.append(float(numerator/max(denominator,1e-20)))
                if min(halves)<.55:
                    continue
                candidates.append({'parameters':{'useful_samples':useful,'guard_samples':guard,
                    'symbol_samples':period,'guard_fraction':guard/useful,
                    'useful_seconds':useful/fs,'guard_seconds':guard/fs,'symbol_seconds':period/fs,
                    'first_guard_phase_sample':int(start)+phase},
                    'evidence':{'folded_prefix_correlation':peak,'background_correlation':background,
                                'correlation_contrast':contrast,'symbols_averaged':cycles,'first_half_correlation':halves[0],'second_half_correlation':halves[1],
                                'effective_spectral_bin_fraction':occupied},
                    'score':peak*contrast,'score_kind':'heuristic_not_probability',
                    'window_sample_start':int(start),'window_sample_count':len(block),
                    'validation_scope':'periodic repeated-guard evidence only; no protocol, FFT-bin contents, CRC or payload decoded'})
    candidates.sort(key=lambda c:c['score'],reverse=True)
    distinct = []
    for candidate in candidates:
        key = (candidate['parameters']['useful_samples'],candidate['parameters']['guard_samples'])
        if any((c['parameters']['useful_samples'],c['parameters']['guard_samples'])==key for c in distinct):
            continue
        distinct.append(candidate)
        if len(distinct)==3:
            break
    return dict(base,status='periodic_prefix_candidate' if distinct else 'no_consistent_candidate',
                candidates=distinct,trials=trials,windows_examined=windows,
                analyzed_samples=total,analyzed_seconds=total/fs,sample_budget=max_samples,
                sample_budget_reached=original>total,
                source_samples=original,source_span_seconds=original/fs,
                sampled_fraction=total/original,window_selection='distributed_nonoverlapping',
                coverage_complete=total==original,
                limitations=['Repetition compatible with a cyclic prefix does not uniquely identify OFDM, Wi-Fi, LTE or DVB-T.',
                             'Single source, powers-of-two useful lengths 16–2048, guard ratios 1/4 to 1/32; at least 32 symbols per window.',
                             'At most three non-overlapping windows distributed across the source; aggregate budget at most 262144 samples. Unsampled gaps are not inspected. Bursts, overlapping channels, resampling, clock drift and other guards may be missed.',
                             'No frequency/channel search, synchronization guarantee, demodulated bits, checksum or payload interpretation.'])
