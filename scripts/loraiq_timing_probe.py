"""Diagnostic phase sweep on the fixed SNR-stratified corpus, not a decoder score."""
import json
from pathlib import Path
from scipy import signal
from iqscope import read_iq
from iqscope_lora import detect_lora_preamble


def main():
    root=Path('corpus-cache/loraiq-batch')
    reference=json.loads((root/'observation.json').read_text())
    results=[]
    for index,observation in enumerate(reference['observations']):
        if not 15<=float(observation['annotation']['snr'])<20:
            continue
        x,fs,_=read_iq(root/str(index)/'source.sigmf-meta')
        # Known short member only; never allocate a large upsampled capture.
        if len(x)>100000:
            raise ValueError('Phase diagnostic requires a short capture')
        oversampled=signal.resample_poly(x,8,1)
        phases=[]
        for phase in range(16):
            shifted=oversampled[phase::8]
            trial=detect_lora_preamble(shifted,fs)
            phases.append({'input_shift_chips':phase*125000/(fs*8),'status':trial['status'],
                'frames':trial.get('frames',[]),
                'candidates':[{'parameters':c['parameters'],'sync_word':c['sync_word'],
                    'data_symbols':c['data_symbols'],'explicit_header':c['explicit_header'],
                    'payload':c['payload']} for c in trial['candidates']]})
        results.append({'source_member':observation['annotation']['sigmf_file'],
            'data_sha256':observation['data_sha256'],'phase_sweep':phases})
    out={'scope':'Diagnostic fractional input-delay sensitivity; reference payload not supplied to detector',
         'source':reference['source'],'license':reference['license'],'creators':reference['creators'],'results':results}
    (root/'timing-probe.json').write_text(json.dumps(out,indent=2))
    print('TIMING_PROBE '+json.dumps(out),flush=True)


if __name__=='__main__':
    main()
