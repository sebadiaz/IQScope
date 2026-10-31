"""Opt-in experimental LoRa policy; per-call callbacks, no process-global patching."""
from functools import partial
import numpy as np
import iqscope_lora as lora
from iqscope_lora_soft import infer_payload
from iqscope_lora_sync_scores import evaluate_sync_spectra

ORIGINAL_PAIR=lora._opposite_chirp_pair
ORIGINAL_SYNC=lora._sync_word_candidate
ORIGINAL_DATA=lora._data_symbol_candidates


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
                    'peaks':[lora._matched_peak_evidence(row,int(k)) for row,k in zip(power,peaks)],
                    'alphabet_score_gate':evaluate_sync_spectra(power,polarity) if length<=1024 else {'status':'unsupported_sf'},
                    'local_alphabet_score_gate':evaluate_sync_spectra(power,polarity,noise_model='local') if length<=1024 else {'status':'unsupported_sf'},
                    'pooled_local_alphabet_score_gate':evaluate_sync_spectra(power,polarity,noise_model='pooled_local') if length<=1024 else {'status':'unsupported_sf'}})
    if not hypotheses:
        return {'status':'no_consistent_sync_word'}
    if kwargs.get('apply_composite_gates'):
        hypotheses=[h for h in hypotheses if all(h.get(key,{}).get('status')=='score_gate_passed'
                    for key in ('alphabet_score_gate','pooled_local_alphabet_score_gate'))]
        if not hypotheses:
            return {'status':'research_sync_evidence_rejected'}
    words={h['word'] for h in hypotheses}
    if len(words)>1:
        return {'status':'ambiguous_sync_word','word_hypotheses_hex':[f'{w:02X}' for w in sorted(words)]}
    best=max(hypotheses,key=lambda h:h['strength'])
    return {'status':'sync_word_candidate','value_hex':f"{best['word']:02X}",
        'opposite_chirp_start_chip':best['boundary'],'opposite_chirp_start_seconds':best['boundary']/bandwidth,
        'relative_symbol_bins':best['symbols'],'symbol_bin_errors':best['errors'],
        'method':'research_ungated_sync','minimum_three_bin_energy_fraction':best['strength'],
        'matched_peak_evidence':best['peaks'],'alphabet_score_gate':best['alphabet_score_gate'],
        'local_alphabet_score_gate':best['local_alphabet_score_gate'],
        'pooled_local_alphabet_score_gate':best['pooled_local_alphabet_score_gate'],
        'confidence_gates_bypassed':True}


def research_data(y,chirp,polarity,sync,bandwidth,**kwargs):
    if sync['status']!='sync_word_candidate':
        return {'status':'not_available_without_sync_word'}
    if kwargs.get('minimum_mean_score') is not None:
        return guarded_data(y,chirp,polarity,sync,bandwidth,**kwargs)
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
    soft=infer_payload(symbols,sf,scores,minimum_mean_score=kwargs.get('minimum_mean_score')) if sf<=10 else {'status':'unsupported_sf'}
    stored=len(soft.get('selected_symbols',symbols))
    return {'status':'research_raw_css_symbols','candidate_data_start_seconds':start/bandwidth,
        'symbol_bins':symbols[:stored],'raw_symbol_count':len(symbols),'quarter_chirp_validated':False,'quarter_chirp_method':'research_inferred_boundary',
        'confidence_gates_bypassed':kwargs.get('minimum_mean_score') is None,'boundary_hypotheses_decoded':1,
        'confidence_model':'experimental_code_block_scores' if kwargs.get('minimum_mean_score') is not None else 'ungated_research',
        'soft_analysis':soft,'noise_normalized_spectra':scores[:stored]}


def guarded_data(y,chirp,polarity,sync,bandwidth,**kwargs):
    length=len(chirp);sf=length.bit_length()-1;up=chirp if polarity==1 else chirp.conj()
    if sf>10:
        return {'status':'research_unsupported_sf'}
    physical=ORIGINAL_DATA(y,chirp,polarity,sync,bandwidth,
        refined_timing=kwargs.get('refined_timing',False),noise_fallback=kwargs.get('noise_fallback',False))
    if physical['status']=='raw_css_symbol_candidates':
        header=lora.decode_explicit_header(physical.get('symbol_bins',[]),sf)
        if header['status']=='header_checksum_valid' and header['coding_rate_index']!=1:
            payload=lora.decode_payload(physical['symbol_bins'],sf)
            soft={'status':'research_crc_valid' if payload['status']=='payload_crc_valid' else 'research_payload_unvalidated',
                  'payload':payload,'blocks':[],'selected_symbols':physical['symbol_bins'],
                  'method':'standard_non_cr45_path','payload_decode_calls':1,'crc_used_for_candidate_selection':False}
            return dict(physical,soft_analysis=soft,noise_normalized_spectra=[])
    if physical['status']=='raw_css_symbol_candidates':
        start=round(physical['candidate_data_start_seconds']*bandwidth)
        boundary=start-2*length-length//4
        quarter_validated=physical.get('quarter_chirp_validated',True)
        boundary_method=physical['quarter_chirp_method']
    else:
        boundary=sync['opposite_chirp_start_chip']
        start=boundary+2*length+length//4
        quarter_validated=False
        boundary_method='research_single_inferred_boundary'
    if boundary<8*length or start+8*length>len(y):
        return {'status':'research_insufficient_reference'}
    reference=np.mean(y[boundary-8*length:boundary-2*length].reshape(6,length),axis=0)*up.conj()
    ref_power=abs(np.fft.fft(reference))**2;peak=int(ref_power.argmax())
    reliability=lora._matched_peak_evidence(ref_power,peak)
    tone=lora._interpolated_tone_bin(reference,peak)
    if tone is None or reliability['status']!='reliable_matched_peak':
        return {'status':'research_reference_rejected','reference_peak':reliability}
    correction=np.exp(-2j*np.pi*tone*np.arange(length)/length)
    symbols=[];scores=[]
    for index in range(min(64,(len(y)-start)//length)):
        values=y[start+index*length:start+(index+1)*length]*up.conj()*correction
        power=abs(np.fft.fft(values))**2;k=int(power.argmax())
        distance=(np.arange(length)-k+length//2)%length-length//2
        noise=float(np.median(power[abs(distance)>2])/np.log(2))
        aligned=power[(polarity*np.arange(length))%length]
        symbols.append(int(aligned.argmax()));scores.append((aligned/max(noise,1e-30)).tolist())
    soft=infer_payload(symbols,sf,scores,minimum_mean_score=kwargs['minimum_mean_score'])
    stored=len(soft.get('selected_symbols',symbols))
    return {'status':'research_guarded_css_symbols','candidate_data_start_seconds':start/bandwidth,
        'symbol_bins':symbols[:stored],'raw_symbol_count':len(symbols),'quarter_chirp_validated':quarter_validated,
        'quarter_chirp_method':boundary_method,'confidence_model':'experimental_composite_and_block_scores',
        'confidence_gates_bypassed':False,'boundary_hypotheses_decoded':1,
        'reference_tone_bin':tone,'reference_blocks':6,'reference_peak_evidence':reliability,
        'soft_analysis':soft,'noise_normalized_spectra':scores[:stored]}


def guarded_sync(*args,**kwargs):
    existing=ORIGINAL_SYNC(*args,**kwargs)
    if existing['status']=='sync_word_candidate':
        return dict(existing,confidence_gates_bypassed=False,research_policy_branch='existing_physical_sync')
    result=research_sync(*args,**dict(kwargs,apply_composite_gates=True))
    if result['status']!='sync_word_candidate':
        return result
    passed=all(result.get(key,{}).get('status')=='score_gate_passed'
               for key in ('alphabet_score_gate','pooled_local_alphabet_score_gate'))
    if not passed:
        return {'status':'research_sync_evidence_rejected','research_candidate':result}
    return dict(result,confidence_gates_bypassed=False,method='research_composite_sync',research_policy_branch='experimental_composite_sync')


def analyse_samples(samples,fs,guarded=False):
    sync=guarded_sync if guarded else research_sync
    data=partial(research_data,minimum_mean_score=8) if guarded else research_data
    trial=lora.detect_lora_preamble(samples,fs,policy={'pair':research_pair,'sync':sync,'data':data})
    trial.pop('frames',None)
    trial['raw_detector_status']=trial.get('status')
    trial['status']='research_observations_only'
    return trial



def _experimental_payload(data,sf):
    soft=data.get('soft_analysis',{})
    if soft.get('status')!='research_crc_valid':
        return {'status':soft.get('status','no_valid_experimental_evidence'),
                'scope':'Experimental confidence and parity policy; no validated payload.'}
    corrections=[]
    for block in soft['blocks']:
        if block['status']=='single_erasure_candidate':
            best=block['candidates'][0]
            index=block['start_symbol_index']+best['row']
            corrections.append({'symbol_index':index,'from_bin':data['symbol_bins'][index],
                                'to_bin':best['replacement'],'spectral_margin':block['spectral_margin']})
    return dict(soft['payload'],experimental_mode=True,soft_symbol_corrections=corrections)


def detect_guarded_lora(samples,fs):
    def data(*args,**kwargs):
        result=research_data(*args,**dict(kwargs,minimum_mean_score=8))
        result.pop('noise_normalized_spectra',None)
        return result
    trial=lora.detect_lora_preamble(samples,fs,policy={
        'pair':research_pair,'sync':guarded_sync,'data':data,'payload':_experimental_payload})
    trial['mode']='experimental_guarded'
    trial.setdefault('limitations',[]).append('Experimental composite sync and soft CR4/5 erasure policy; not calibrated for general radio false positives. Inferred boundaries retain unconfirmed quarter flags.')
    return trial
