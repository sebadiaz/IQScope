"""Offline research: bypass front-end confidence gates, infer erasures without CRC search.

Never used by the production detector or UI. Reads a local SigMF member only.
"""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
import iqscope_lora as lora
from iqscope import read_iq
from lora_soft_probe import infer_payload
from lora_sync_gate import evaluate_sync_spectra


from iqscope_lora_experimental import (research_pair,research_sync,research_data,
    guarded_data,guarded_sync,analyse_samples)


def run(meta_path,guarded=False):
    if meta_path.suffix!='.sigmf-meta' or meta_path.stat().st_size>65536:
        raise ValueError('Expected local SigMF metadata <=64 KiB')
    data_path=meta_path.with_suffix('.sigmf-data')
    if data_path.stat().st_size>32*1024*1024:
        raise ValueError('Research input exceeds 32 MiB')
    data=data_path.read_bytes();metadata=meta_path.read_bytes();meta=json.loads(metadata)
    if hashlib.sha512(data).hexdigest()!=meta['global'].get('core:sha512'):
        raise ValueError('Publisher SigMF SHA512 mismatch')
    samples,fs,_=read_iq(meta_path)
    trial=analyse_samples(samples,fs,guarded)
    # Suppress the patched detector's frame list: only research observations are exposed.
    observations=[]
    for candidate in trial['candidates']:
        d=candidate['data_symbols']
        if 'soft_analysis' in d:
            observations.append({'parameters':candidate['parameters'],'analysis_window_index':candidate['analysis_window_index'],
                'preamble_time_seconds':candidate['time_seconds'],'data_time_seconds':d['candidate_data_start_seconds'],
                'carrier_tracking':candidate['carrier_tracking'],'sync_word':candidate['sync_word'],
                'symbol_bins':d['symbol_bins'],'noise_normalized_spectra':d['noise_normalized_spectra'],
                'quarter_chirp_validated':d.get('quarter_chirp_validated',False),
                'boundary_method':d.get('quarter_chirp_method'),
                'reference_tone_bin':d.get('reference_tone_bin'),
                'hard_payload':candidate['payload'],'soft_analysis':d['soft_analysis']})
    return {'scope':('Research only: experimental composite sync and block-score gates applied; not the automatic product.' if guarded else
        'Research only: sync and data confidence gates bypassed; not the automatic product or a new production benchmark score.'),
        'experimental_guarded_policy_applied':guarded,
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
    parser.add_argument('--guarded',action='store_true',help='Apply experimental composite sync and block-score gates')
    parser.add_argument('--out',type=Path,default=Path('corpus-cache/loraiq-forensic/observation.json'))
    args=parser.parse_args();result=run(args.input,guarded=args.guarded)
    args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'scope':result['scope'],'observations':[{'data_time_seconds':o['data_time_seconds'],
          'soft_status':o['soft_analysis']['status'],'payload':o['soft_analysis'].get('payload')} for o in result['observations']]}))


if __name__=='__main__':
    main()
