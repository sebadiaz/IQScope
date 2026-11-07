"""Prefix-trained receiver experiments; no PRBS feedback into signal processing."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from scipy import signal
from iqscope_qam import LEVELS, decode_qam16
from iqscope_psk_rrc import rrc_taps
from scripts.qam_lab_reference import read_keysight_csv, SHA256, SIZE, URL
from scripts.qam_prbs15 import check_prbs15

TRAIN_SYMBOLS=512
POINTS=(LEVELS[:,None]+1j*LEVELS[None,:]).reshape(-1)


def slice_labels(values):
    i=np.argmin(abs(values.real[:,None]-LEVELS),axis=1)
    q=np.argmin(abs(values.imag[:,None]-LEVELS),axis=1)
    return 4*i+q


def reconstruct_symbols(x,fs,fit):
    """Reproduce one fixed blind fit in physical time units."""
    x=np.array(x,dtype=np.complex128,copy=True)
    x/=np.sqrt(np.mean(abs(x)**2))
    corrected=x*np.exp(-2j*np.pi*fit['carrier_offset_hz']*np.arange(len(x))/fs)
    up=2 if fs/fit['baud']<8 else 1
    if up>1:corrected=signal.resample_poly(corrected,up,1)
    down=max(1,int(fs*up/(16*fit['baud'])))
    y=signal.resample_poly(corrected,1,down) if down>1 else corrected
    rate=fs*up/down
    filtered=signal.fftconvolve(y,rrc_taps(rate/fit['baud'],fit['rrc_rolloff_trial']),mode='same')
    centers=(fit['first_symbol_center_seconds']+np.arange(fit['symbol_count'])/fit['baud'])*rate
    values=np.interp(centers,np.arange(len(filtered)),filtered.real)+1j*np.interp(centers,np.arange(len(filtered)),filtered.imag)
    values/=np.sqrt(np.mean(abs(values)**2))
    return values*np.exp(-1j*fit['phase_origin_radians'])


def affine_em(values):
    """Fit a noisy affine square-QAM mixture on prefix samples without labels."""
    train=np.column_stack((values[:TRAIN_SYMBOLS].real,values[:TRAIN_SYMBOLS].imag))
    grid=np.column_stack((POINTS.real,POINTS.imag,np.ones(16)))
    coef=np.zeros((3,2))
    coef[:2]=np.diag(np.sqrt(2*np.var(train,axis=0)))
    coef[2]=train.mean(axis=0)
    variance=.02
    for _ in range(32):
        means=grid@coef
        distance=np.sum((train[:,None,:]-means[None,:,:])**2,axis=2)
        logits=-distance/(2*max(variance,1e-5))
        weights=np.exp(logits-logits.max(axis=1,keepdims=True))
        weights/=weights.sum(axis=1,keepdims=True)
        normal=grid.T@(weights.sum(axis=0)[:,None]*grid)
        cross=(weights@grid).T@train
        coef=np.linalg.solve(normal+1e-8*np.eye(3),cross)
        distance=np.sum((train[:,None,:]-(grid@coef)[None,:,:])**2,axis=2)
        variance=float(np.sum(weights*distance)/(2*len(train)))
    if np.linalg.cond(coef[:2])>4:raise ValueError('Ill-conditioned affine mixture')
    raw=np.column_stack((values.real,values.imag))
    corrected=(raw-coef[2])@np.linalg.inv(coef[:2])
    return corrected[:,0]+1j*corrected[:,1],{'linear_matrix':coef[:2].tolist(),
                'offset_iq':coef[2].tolist(),'prefix_noise_variance_per_axis':variance,'iterations':32}


def variants(values):
    train=values[:TRAIN_SYMBOLS]
    yield 'baseline',values,{}
    center=complex(train.mean())
    yield 'prefix_dc',values-center,{'offset_iq':[center.real,center.imag]}
    corrected,parameters=affine_em(values)
    yield 'prefix_affine_em',corrected,parameters
    # Two causal postcursor taps and current symbol. Prefix decisions are
    # the only targets; no reference bits enter this equalizer.
    taps=3
    positions=np.arange(taps-1,len(values))
    matrix=values[positions[:,None]-np.arange(taps)[None,:]]
    count=TRAIN_SYMBOLS-taps+1
    target=POINTS[slice_labels(values[taps-1:TRAIN_SYMBOLS])]
    ridge=.05*count
    prior=np.array([1,0,0],dtype=complex)
    coefficients=np.linalg.solve(matrix[:count].conj().T@matrix[:count]+ridge*np.eye(taps),
                                 matrix[:count].conj().T@target+ridge*prior)
    output=values.copy();output[taps-1:]=matrix@coefficients
    yield 'prefix_decision_directed_fir3',output,{'coefficients_i':coefficients.real.tolist(),
                           'coefficients_q':coefficients.imag.tolist(),'ridge_per_symbol':.05}


def summarize(values):
    labels=slice_labels(values)
    error=values-POINTS[labels]
    return {'prbs15':check_prbs15(labels),'evaluation_decision_evm_rms':float(np.sqrt(np.mean(abs(error[TRAIN_SYMBOLS:])**2)))}


def main():
    root=Path('corpus-cache/qam-lab')
    raw=(root/'IQ_28_Ghz.zip').read_bytes()
    if len(raw)!=SIZE or hashlib.sha256(raw).hexdigest()!=SHA256:raise ValueError('Unverified laboratory archive')
    results={'source_url':URL,'source_sha256':SHA256,'training_symbols':TRAIN_SYMBOLS,
             'scope':'predeclared prefix-trained experiments; all results reported, no PRBS feedback or automatic acceptance change',
             'files':{},'noise_reference_power':{}}
    with zipfile.ZipFile(root/'IQ_28_Ghz.zip') as archive:
        for name in sorted(archive.namelist()):
            basename=Path(name).name
            if basename in ('noise a.csv','noise b.csv'):
                x,fs,_=read_keysight_csv(archive.read(name))
                results['noise_reference_power'][basename]=float(np.mean(abs(x)**2))
            if not (basename.startswith('16qam ') and basename.endswith('.csv')):continue
            x,fs,layout=read_keysight_csv(archive.read(name))
            fits=[]
            def observe(fit,labels):fits.append((fit,labels))
            decoded=decode_qam16(x,fs,trial_observer=observe)
            # Same first fixed RRC trial for all captures; no selection by BER.
            fit,expected=fits[0]
            values=reconstruct_symbols(x,fs,fit)
            labels=slice_labels(values)
            if not np.array_equal(labels,expected):raise AssertionError('Symbol reconstruction differs from receiver')
            results['files'][basename]={'layout':layout,'generic_status':decoded['status'],
                'source_mean_power':float(np.mean(abs(x)**2)),
                'variants':{method:dict(summarize(output),parameters=parameters) for method,output,parameters in variants(values)}}
    (root/'receiver-study.json').write_text(json.dumps(results,indent=2))
    print(json.dumps(results,indent=2))


if __name__=='__main__':main()
