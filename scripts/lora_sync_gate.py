"""Research-only alphabet score gate and counterexamples; not a production confidence."""
import argparse
import json
from pathlib import Path
import numpy as np


def evaluate_sync_spectra(power,polarity=1,noise_model='global'):
    p=np.asarray(power,dtype=float)
    if p.ndim!=2 or p.shape[0]!=3 or p.shape[1] not in (128,256,512,1024) or polarity not in (-1,1):
        raise ValueError('Expected three SF7-10 spectra and chirp polarity')
    if not np.all(np.isfinite(p)) or np.any(p<0):
        raise ValueError('Expected finite nonnegative power')
    if noise_model not in ('global','local','pooled_local'):
        raise ValueError('Unknown noise model')
    scale=float(np.max(p))
    if scale>0:
        p=p/scale
    length=p.shape[1];peaks=p.argmax(axis=1);ratios=[]
    for row,peak in zip(p,peaks):
        distance=(np.arange(length)-int(peak)+length//2)%length-length//2
        if noise_model=='pooled_local':
            background=p[:,(int(peak)+np.array([-4,-3,-2,2,3,4]))%length].ravel()
        elif noise_model=='local':
            background=row[(int(peak)+np.array([-4,-3,-2,2,3,4]))%length]
        else:
            background=row[abs(distance)>2]
        noise=float(np.median(background)/np.log(2))
        ratios.append(float(row[peak]/max(noise,1e-30)))
    indices=(int(peaks[0])+polarity*(8*np.arange(16)[:,None]+np.array([-1,0,1])[None,:]))%length
    letters=[];errors=[];masses=[];legal_margins=[]
    for row,peak,ratio in zip(p[1:],peaks[1:],ratios[1:]):
        scores=np.max(row[indices],axis=1)
        best=int(scores.argmax());letters.append(best)
        symbol=(polarity*(int(peak)-int(peaks[0])))%length
        errors.append(min((symbol-8*best)%length,(8*best-symbol)%length))
        noise=float(row[peak]/max(ratio,1e-30))
        normalized=scores/max(noise,1e-30)
        weights=np.exp(normalized-float(normalized.max()))
        masses.append(float(weights[best]/max(float(weights.sum()),1e-30)))
        competing=float(np.max(np.delete(scores,best)))
        legal_margins.append(float(scores[best]/max(competing,1e-30)))
    mass=float(np.prod(masses))
    accepted=min(ratios)>=8 and sum(ratios)>=32 and max(errors)<=1 and mass>=.99
    return {'noise_model':noise_model,'status':'score_gate_passed' if accepted else 'score_gate_rejected',
            'value_hex':f'{16*letters[0]+letters[1]:02X}','symbol_bin_errors':errors,
            'peak_to_noise_floor':ratios,'required_minimum_peak_to_noise_floor':8,
            'summed_peak_to_noise_floor':sum(ratios),'required_summed_peak_to_noise_floor':32,
            'legal_alphabet_peak_margin':legal_margins,'relative_word_score_mass':mass,
            'required_relative_word_score_mass':.99,
            'scope':'Research score concentration under a simplified noise model; not a calibrated word probability or complete synchronization.'}


def audit(trials=4096,seed=20261031):
    if not 1<=trials<=16384:
        raise ValueError('Trial count must be 1..16384')
    rng=np.random.default_rng(seed);length=128
    omega=2*np.pi*np.arange(length)/length
    colored_shape=1/(1+.9**2-2*.9*np.cos(omega))
    counts={family:{'global':0,'global_and_local':0,'global_and_pooled_local':0} for family in ('white_noise','smooth_coloured_noise')}
    for _ in range(trials):
        white=rng.exponential(size=(3,length))
        for family,power in (('white_noise',white),('smooth_coloured_noise',white*colored_shape)):
            global_pass=evaluate_sync_spectra(power)['status']=='score_gate_passed'
            counts[family]['global']+=global_pass
            if global_pass:
                counts[family]['global_and_local']+=evaluate_sync_spectra(power,noise_model='local')['status']=='score_gate_passed'
                counts[family]['global_and_pooled_local']+=evaluate_sync_spectra(power,noise_model='pooled_local')['status']=='score_gate_passed'
    repeated=np.ones((3,length));repeated[:,0]=100
    tied=repeated.copy();tied[1,8]=100
    counterexamples={'preamble_continuation':evaluate_sync_spectra(repeated),
                     'preamble_continuation_local':evaluate_sync_spectra(repeated,noise_model='local'),
                     'preamble_continuation_pooled':evaluate_sync_spectra(repeated,noise_model='pooled_local'),
                     'equal_legal_alternatives':evaluate_sync_spectra(tied)}
    return {'seed':seed,'trials_per_noise_family':trials,'passed_by_noise_family':counts,
        'counterexamples':counterexamples,
        'sufficient_for_production':False,
        'limitations':['Conditional spectrum-level audit, not a false-alarm rate of the whole detector.',
            'Exponential powers model independent complex-Gaussian FFT noise; the colored family multiplies a smooth spectral shape.',
            'Reference peak and alphabet are selected in each trial; raw IQ acquisition, pair and CRC are not tested here.',
            'Repeated dechirped tones can resemble an all-zero sync word; score concentration does not prove packet boundaries.',
            'Local model uses six neighboring bins at offsets +/-2..4; it is an additional leave-peak-out check, not guaranteed whitening.',
            'Pooled-local uses the same neighboring bins across three spectra, assuming stationary noise across the three chirps.',
            'Thresholds are engineering hypotheses, not calibrated probabilities.']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trials',type=int,default=4096)
    parser.add_argument('--seed',type=int,default=20261031)
    parser.add_argument('--out',type=Path,default=Path('corpus-cache/loraiq-forensic/sync-audit.json'))
    args=parser.parse_args();result=audit(args.trials,args.seed)
    args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='counterexamples'}))


if __name__=='__main__':
    main()
