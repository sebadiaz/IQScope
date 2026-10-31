"""Offline research: bypass front-end confidence gates, infer erasures without CRC search.

Never used by the production detector or UI. Reads a local SigMF member only.
"""
import argparse
import hashlib
import json
from pathlib import Path
from unittest.mock import patch
import numpy as np
import iqscope_lora as lora
from iqscope import read_iq
from lora_soft_probe import infer_payload


ORIGINAL_PAIR=lora._opposite_chirp_pair


def research_pair(y,chirp,polarity,run_end,bandwidth,**kwargs):
    old=ORIGINAL_PAIR(y,chirp,polarity,run_end,bandwidth,**kwargs)
    if old['status']=='opposite_chirp_pair_candidate':
        return old
    length=len(chirp);template=chirp.conj() if polarity==1 else chirp;best=None
    for start in range(max(0,run_end-length),min(len(y)-2*length,run_end+4*length)+1,max(1,length//32)):
        matrix=y[start:start+2*length].reshape(2,length)
        transformed=np.fft.fft(matrix*template.conj(),axis=1);power=abs(transformed)**2;peaks=power.argmax(axis=1)
        if abs((int(peaks[1])-int(peaks[0])+length//2)%length-length//2)>1:
            continue
        individual=[lora._matched_peak_evidence(row,int(k)) for row,k in zip(power,peaks)]
        if any(e['peak_to_noise_floor']<8 or e['peak_to_competing_peak']<2 for e in individual):
            continue
        peak=int(power.sum(axis=0).argmax());a=transformed[:,peak]
        cosine=float(np.real(a[1]*a[0].conj())/max(abs(a[0]*a[1]),1e-30))
        combined=abs(np.fft.fft(matrix.mean(axis=0)*template.conj()))**2
        evidence=lora._matched_peak_evidence(combined,int(combined.argmax()))
        if cosine<.8 or evidence['status']!='reliable_matched_peak':
            continue
        score=evidence['peak_to_noise_floor']
        if best is None or score>best['joint_score']:
            best={'status':'opposite_chirp_pair_candidate','time_seconds':start/bandwidth,
                'sample_start_at_chip_rate':start,'dechirped_peak_bins':[int(k) for k in peaks],
                'method':'research_joint_pair','joint_score':score,'phase_cosine':cosine,
                'individual_peak_evidence':individual,'combined_peak_evidence':evidence}
    return best or old


def research_sync(y,chirp,polarity,preamble_bin,pair,bandwidth,**kwargs):
    if pair['status']!='opposite_chirp_pair_candidate':
        return {'status':'not_available_without_opposite_pair'}
    length=len(chirp);start=pair['sample_start_at_chip_rate'];down=pair['dechirped_peak_bins'][0]
    phase=((polarity*(down-preamble_bin)+start)/2)%(length/2)
    template=chirp if polarity==1 else chirp.conj();tested=set();hypotheses=[]
    for half in (0,length/2):
        for cycle in range(start//length-1,start//length+2):
            center=round(cycle*length+phase+half)
            for delta in (-1,0,1):
                boundary=center+delta
                if boundary in tested or boundary<3*length or abs(boundary-start)>length/2:
                    continue
                tested.add(boundary)
                matrix=y[boundary-3*length:boundary].reshape(3,length)
                power=abs(np.fft.fft(matrix*template.conj(),axis=1))**2;peaks=power.argmax(axis=1)
                symbols=[(polarity*(int(k)-int(peaks[0])))%length for k in peaks[1:]]
                nibbles=[];errors=[]
                for value in symbols:
                    distances=[min((value-8*n)%length,(8*n-value)%length) for n in range(16)]
                    nibble=int(np.argmin(distances));nibbles.append(nibble);errors.append(distances[nibble])
                if max(errors)>1:
                    continue
                energy=sum(power[np.arange(3),(peaks+d)%length] for d in (-1,0,1))/np.maximum(power.sum(axis=1),1e-30)
                hypotheses.append({'boundary':boundary,'word':16*nibbles[0]+nibbles[1],
                    'symbols':symbols,'errors':errors,'strength':float(min(energy)),
                    'peaks':[lora._matched_peak_evidence(row,int(k)) for row,k in zip(power,peaks)]})
    if not hypotheses:
        return {'status':'no_consistent_sync_word'}
    words={h['word'] for h in hypotheses}
    if len(words)>1:
        return {'status':'ambiguous_sync_word','word_hypotheses_hex':[f'{w:02X}' for w in sorted(words)]}
    best=max(hypotheses,key=lambda h:h['strength'])
    return {'status':'sync_word_candidate','value_hex':f"{best['word']:02X}",
        'opposite_chirp_start_chip':best['boundary'],'opposite_chirp_start_seconds':best['boundary']/bandwidth,
        'relative_symbol_bins':best['symbols'],'symbol_bin_errors':best['errors'],
        'method':'research_ungated_sync','minimum_three_bin_energy_fraction':best['strength'],
        'matched_peak_evidence':best['peaks'],'confidence_gates_bypassed':True}


def research_data(y,chirp,polarity,sync,bandwidth,**kwargs):
    if sync['status']!='sync_word_candidate':
        return {'status':'not_available_without_sync_word'}
    length=len(chirp);sf=length.bit_length()-1;up=chirp if polarity==1 else chirp.conj()
    boundary=sync['opposite_chirp_start_chip'];start=boundary+2*length+length//4
    if start+8*length>len(y):
        return {'status':'insufficient_symbols'}
    reference=abs(np.fft.fft(y[boundary-3*length:boundary-2*length]*up.conj()))**2
    reference_bin=int(reference.argmax());symbols=[];scores=[]
    for index in range(min(64,(len(y)-start)//length)):
        power=abs(np.fft.fft(y[start+index*length:start+(index+1)*length]*up.conj()))**2
        peak=int(power.argmax());distance=(np.arange(length)-peak+length//2)%length-length//2
        noise=float(np.median(power[abs(distance)>2])/np.log(2))
        scores.append((power[(reference_bin+polarity*np.arange(length))%length]/max(noise,1e-30)).tolist())
        symbols.append((polarity*(peak-reference_bin))%length)
    soft=infer_payload(symbols,sf,scores) if sf<=10 else {'status':'unsupported_sf'}
    stored=len(soft.get('selected_symbols',symbols))
    return {'status':'research_raw_css_symbols','candidate_data_start_seconds':start/bandwidth,
        'symbol_bins':symbols[:stored],'raw_symbol_count':len(symbols),'quarter_chirp_validated':False,'quarter_chirp_method':'research_inferred_boundary',
        'confidence_gates_bypassed':True,'boundary_hypotheses_decoded':1,
        'soft_analysis':soft,'noise_normalized_spectra':scores[:stored]}


def run(meta_path):
    if meta_path.suffix!='.sigmf-meta' or meta_path.stat().st_size>65536:
        raise ValueError('Expected local SigMF metadata <=64 KiB')
    data_path=meta_path.with_suffix('.sigmf-data')
    if data_path.stat().st_size>32*1024*1024:
        raise ValueError('Research input exceeds 32 MiB')
    data=data_path.read_bytes();metadata=meta_path.read_bytes();meta=json.loads(metadata)
    if hashlib.sha512(data).hexdigest()!=meta['global'].get('core:sha512'):
        raise ValueError('Publisher SigMF SHA512 mismatch')
    samples,fs,_=read_iq(meta_path)
    with patch.object(lora,'_opposite_chirp_pair',research_pair),patch.object(lora,'_sync_word_candidate',research_sync),patch.object(lora,'_data_symbol_candidates',research_data):
        trial=lora.detect_lora_preamble(samples,fs)
    # Suppress the patched detector's frame list: only research observations are exposed.
    observations=[]
    for candidate in trial['candidates']:
        d=candidate['data_symbols']
        if 'soft_analysis' in d:
            observations.append({'parameters':candidate['parameters'],'analysis_window_index':candidate['analysis_window_index'],
                'preamble_time_seconds':candidate['time_seconds'],'data_time_seconds':d['candidate_data_start_seconds'],
                'carrier_tracking':candidate['carrier_tracking'],'sync_word':candidate['sync_word'],
                'symbol_bins':d['symbol_bins'],'noise_normalized_spectra':d['noise_normalized_spectra'],
                'hard_payload':candidate['payload'],'soft_analysis':d['soft_analysis']})
    return {'scope':'Research only: sync and data confidence gates bypassed; not the automatic product or a new production benchmark score.',
        'source':'https://zenodo.org/records/20341802','doi':'10.5281/zenodo.20341802','license':'CC BY 4.0',
        'creators':['Joachim Tapparel','Andreas Burg'],'source_data_sha256':hashlib.sha256(data).hexdigest(),
        'source_meta_sha256':hashlib.sha256(metadata).hexdigest(),'publisher_sha512_verified':True,
        'oracle_parameters_applied':[],'quarter_chirp_validated':False,'sample_rate_hz':fs,
        'observations':observations,'limitations':['No annotations, expected bytes, SF, CFO or time windows supplied to the detector.',
            'One fixed boundary per unique sync-word hypothesis; no CRC-driven timing or symbol search.',
            'CR4/5 single-symbol-erasure model can fail on multiple errors; spectral margins are heuristic.',
            'No production decoder thresholds changed. Source RF center unverified.']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--out',type=Path,default=Path('corpus-cache/loraiq-forensic/observation.json'))
    args=parser.parse_args();result=run(args.input)
    args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'scope':result['scope'],'observations':[{'data_time_seconds':o['data_time_seconds'],
          'soft_status':o['soft_analysis']['status'],'payload':o['soft_analysis'].get('payload')} for o in result['observations']]}))


if __name__=='__main__':
    main()
