"""End-to-end synthetic IQ audit of an experimental guarded LoRa research policy."""
import argparse
import json
from pathlib import Path
import numpy as np
from scipy import signal
from loraiq_forensic_probe import analyse_samples

HELLO=[17,13,125,1,1,17,5,5,54,102,33,71,85,38,107,0,81,73]
BAD_CRC=[17,13,125,1,1,17,5,5,54,102,33,71,85,27,107,0,81,76]
BAD_HEADER=[41,49,1,13,105,29,101,85]
NEGATIVES=('white_noise','colored_noise','periodic_wideband','preamble_only',
           'random_css_payload','bad_header','bad_crc','truncated_payload')
CONTROLS=('valid_strong','valid_weak','valid_zero_sync')
ABLATIONS=('missing_downchirps','missing_quarter')


def waveform(kind,seed):
    rng=np.random.default_rng(seed);n=np.arange(256)/2
    up=np.exp(2j*np.pi*(n*n/(2*128)-n/2));prefix=17+seed%47
    def noise(count):return rng.normal(size=count)+1j*rng.normal(size=count)
    if kind=='white_noise':return noise(12000),250000
    if kind=='colored_noise':
        x=signal.lfilter([1],[1,-.85],noise(12000))
        return x/np.sqrt(np.mean(abs(x)**2)),250000
    if kind=='periodic_wideband':return np.tile(noise(256),40),250000
    if kind=='preamble_only':return np.r_[np.zeros(prefix),np.tile(up,12),noise(4096)],250000
    symbols=list(HELLO)
    if kind=='bad_crc':symbols=list(BAD_CRC)
    if kind=='bad_header':symbols=BAD_HEADER+HELLO[8:]
    if kind=='truncated_payload':symbols=HELLO[:12]
    if kind=='random_css_payload':symbols=[int(v) for v in rng.integers(0,128,40)]
    word=0 if kind=='valid_zero_sync' else 0x34
    pair=np.tile(up.conj(),2) if kind!='missing_downchirps' else np.zeros(512)
    quarter=up.conj()[:64] if kind!='missing_quarter' else np.zeros(64)
    x=np.r_[np.zeros(prefix),np.tile(up,8),np.roll(up,-16*(word>>4)),np.roll(up,-16*(word&15)),
            pair,quarter,np.concatenate([np.roll(up,-2*v) for v in symbols]),np.zeros(4096)]
    cfo=(seed%9-4)*.1
    x*=np.exp(2j*np.pi*cfo*np.arange(len(x))/256)
    x+=(.75 if kind=='valid_weak' else .05)*noise(len(x))
    return x,250000


def inspect(samples,fs):
    trial=analyse_samples(samples,fs,guarded=True)
    accepted=[];soft_statuses=[]
    for c in trial['candidates']:
        soft=c['data_symbols'].get('soft_analysis',{})
        if soft:soft_statuses.append(soft['status'])
        if soft.get('status')=='research_crc_valid':
            accepted.append({'payload_hex':soft['payload']['payload_hex'],
                'time_seconds':c['data_symbols']['candidate_data_start_seconds'],
                'sync_word':c['sync_word'].get('value_hex'),
                'quarter_chirp_validated':c['data_symbols'].get('quarter_chirp_validated',False)})
    return {'candidate_count':len(trial['candidates']),'soft_statuses':soft_statuses,'accepted_research_payloads':accepted}


def audit(trials_per_family=8,seed=130700):
    if not 1<=trials_per_family<=16:
        raise ValueError('Trials per family must be 1..16')
    result={'scope':'Synthetic IQ, full acquisition plus experimental composite sync and block-score policy; not production acceptance.',
        'seed':seed,'trials_per_family':trials_per_family,'observations':[],
        'limitations':['SF7/BW125k/CR4/5 only; controlled synthetic channels, not real-radio false-alarm validation.',
            'Every input starts with the same bounded detector; no known CFO, timing, SF, payload or expected CRC passed to it.',
            'Correct-byte checks are post-decode controls only. No CRC-driven hypothesis retries.',
            'Ablated delimiters are reported separately: coded payload bytes still exist in these inputs.',
            'Research policy uses alternative confidence criteria and inferred quarter boundaries; production remains unchanged.']}
    families=NEGATIVES+CONTROLS+ABLATIONS
    for family_index,kind in enumerate(families):
        for index in range(trials_per_family):
            case_seed=seed+family_index*1000+index
            samples,fs=waveform(kind,case_seed)
            observation=inspect(samples,fs)
            observation.update(family=kind,seed=case_seed,input_samples=len(samples))
            result['observations'].append(observation)
        selected=[o for o in result['observations'] if o['family']==kind]
        print('IQ_AUDIT_FAMILY '+json.dumps({'family':kind,'trials':len(selected),
            'cases_with_accepted_payload':sum(bool(o['accepted_research_payloads']) for o in selected)}),flush=True)
    result['families']={kind:{'trials':trials_per_family,
        'cases_with_accepted_payload':sum(bool(o['accepted_research_payloads']) for o in result['observations'] if o['family']==kind),
        'cases_with_exact_hello':sum(any(p['payload_hex']=='48454c4c4f' for p in o['accepted_research_payloads']) for o in result['observations'] if o['family']==kind)} for kind in families}
    result['negative_cases_with_accepted_payload']=sum(bool(o['accepted_research_payloads']) for o in result['observations'] if o['family'] in NEGATIVES)
    result['negative_case_count']=len(NEGATIVES)*trials_per_family
    result['positive_cases_with_exact_payload']=sum(result['families'][kind]['cases_with_exact_hello'] for kind in CONTROLS)
    result['positive_case_count']=len(CONTROLS)*trials_per_family
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trials-per-family',type=int,default=8)
    parser.add_argument('--out',type=Path,default=Path('corpus-cache/loraiq-forensic/iq-policy-audit.json'))
    args=parser.parse_args();result=audit(args.trials_per_family)
    args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(result,indent=2)+'\n')
    print('IQ_AUDIT_RESULT '+json.dumps({k:v for k,v in result.items() if k not in ('observations','families')}))


if __name__=='__main__':
    main()
