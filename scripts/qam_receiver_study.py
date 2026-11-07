"""Prefix-trained receiver experiments; no PRBS feedback into signal processing."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from scipy import signal, optimize
from iqscope_qam import LEVELS, decode_qam16
from iqscope_psk_rrc import rrc_taps
from scripts.qam_lab_reference import read_keysight_csv, SHA256, SIZE, URL
from scripts.qam_prbs15 import check_prbs15
from scripts.qam_prbs15 import prbs15_period, ACQUISITION_BITS
from iqscope_qam_soft import estimate_awgn, bit_llrs

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
    up=fit.get('resample_up',2 if fs/fit['baud']<8 else 1)
    if up>1:corrected=signal.resample_poly(corrected,up,1)
    down=fit.get('resample_down',max(1,int(fs*up/(16*fit['baud']))))
    y=signal.resample_poly(corrected,1,down) if down>1 else corrected
    rate=fs*up/down
    filtered=signal.fftconvolve(y,rrc_taps(fit.get('rrc_samples_per_symbol',rate/fit['baud']),fit['rrc_rolloff_trial']),mode='same')
    centers=(fit['first_symbol_center_seconds']+np.arange(fit['symbol_count'])/fit['baud'])*rate
    values=np.interp(centers,np.arange(len(filtered)),filtered.real)+1j*np.interp(centers,np.arange(len(filtered)),filtered.imag)
    values/=np.sqrt(np.mean(abs(values)**2))
    return values*np.exp(-1j*fit['phase_origin_radians'])


def lanczos_samples(values,centers,radius=8):
    indices=np.floor(centers).astype(int)[:,None]+np.arange(-radius+1,radius+1)[None,:]
    distance=centers[:,None]-indices
    weights=np.sinc(distance)*np.sinc(distance/radius)
    weights[abs(distance)>=radius]=0
    weights/=weights.sum(axis=1,keepdims=True)
    return np.sum(values[np.clip(indices,0,len(values)-1)]*weights,axis=1)


def frontend_variants(x,fs,fit,baseline):
    source=np.asarray(x,dtype=complex)/np.sqrt(np.mean(abs(x)**2))
    source*=np.exp(-2j*np.pi*fit['carrier_offset_hz']*np.arange(len(source))/fs)
    up=fit.get('resample_up',2 if fs/fit['baud']<8 else 1)
    source=signal.resample_poly(source,up,1) if up>1 else source
    down=fit.get('resample_down',max(1,int(fs*up/(16*fit['baud']))))
    source=signal.resample_poly(source,1,down) if down>1 else source
    rate=fs*up/down;period=rate/fit['baud']
    centers=(fit['first_symbol_center_seconds']+np.arange(fit['symbol_count'])/fit['baud'])*rate
    for span,rolloff in ((10,.2),(20,.1),(20,.15),(20,.2),(20,.25)):
        filtered=signal.fftconvolve(source,rrc_taps(period,rolloff,span=span),mode='same')
        def recover(shift):
            values=lanczos_samples(filtered,centers+shift*period)
            values/=np.sqrt(np.mean(abs(values)**2))
            origin=(np.angle(np.mean(values**4))-np.pi)/4
            return values*np.exp(-1j*origin)
        def objective(shift):
            sampled=recover(shift)
            return np.mean(abs(sampled-POINTS[slice_labels(sampled)])**2)
        fit_phase=optimize.minimize_scalar(objective,
                                         bounds=(-.125,.125),method='bounded',options={'maxiter':24,'xatol':1e-5})
        corrected=recover(fit_phase.x)
        rotations=np.exp(.5j*np.pi*np.arange(4))
        rotation=int(np.argmax([np.real(np.vdot(baseline,corrected*r)) for r in rotations]))
        corrected*=rotations[rotation]
        # Preserve baseline boundary symbols so every method evaluates the
        # same bits without padding artifacts from the longer filter.
        corrected[:16]=baseline[:16];corrected[-16:]=baseline[-16:]
        parameters={'rrc_span':span,'rrc_rolloff':rolloff,'interpolator':'Lanczos radius 8',
                    'timing_shift_symbols':float(fit_phase.x),'quarter_turn_alignment':rotation,'preserved_boundary_symbols':16,
                    'fit_scope':'unlabelled full window; no PRBS feedback'}
        yield f'rrc{span}_alpha{rolloff}_lanczos',corrected,parameters


def affine_em(values,fit_count=TRAIN_SYMBOLS):
    """Fit a noisy affine square-QAM mixture on prefix samples without labels."""
    selected=values if fit_count is None else values[:fit_count]
    train=np.column_stack((selected.real,selected.imag))
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
                'offset_iq':coef[2].tolist(),'noise_variance_per_axis':variance,'iterations':32,
                'fit_symbol_count':len(train),'fit_scope':'prefix' if fit_count is not None else 'unlabelled full window'}


def circular_em(values,iterations=32):
    """Blind circular-AWGN likelihood; gain/phase/noise, without bit references."""
    parameters=estimate_awgn(values,iterations)
    gain=parameters['gain_i']+1j*parameters['gain_q']
    return values/gain,parameters


def soft_comparison(values):
    acquisition=check_prbs15(slice_labels(values))
    if (not acquisition.get('mapping_is_bijective',False)
            or acquisition.get('acquisition_error_count',ACQUISITION_BITS)>.1*ACQUISITION_BITS):
        return {'status':'no_prefix_mapping'}
    model=estimate_awgn(values)
    gain=model['gain_i']+1j*model['gain_q']
    llrs=bit_llrs(values,acquisition['label_to_nibble'],gain=gain,noise_variance=model['noise_variance_complex'])
    predicted=(llrs<0).astype(np.uint8)
    pn=prbs15_period()
    if acquisition['canonical_sequence_reversed']:pn=pn[::-1]
    reference=pn[(acquisition['phase_index']+np.arange(len(predicted)))%len(pn)]
    hard_labels=slice_labels(values)
    hard=((np.asarray(acquisition['label_to_nibble'])[hard_labels,None]>>np.arange(3,-1,-1))&1).reshape(-1)
    hard_wrong=hard[ACQUISITION_BITS:]!=reference[ACQUISITION_BITS:]
    soft_wrong=predicted[ACQUISITION_BITS:]!=reference[ACQUISITION_BITS:]
    errors=int(np.count_nonzero(predicted[ACQUISITION_BITS:]!=reference[ACQUISITION_BITS:]))
    return {'status':'measured','model':model,'evaluation_bits':len(predicted)-ACQUISITION_BITS,
            'evaluation_error_count':errors,'evaluation_ber':errors/(len(predicted)-ACQUISITION_BITS),
            'hard_errors_corrected':int(np.count_nonzero(hard_wrong & ~soft_wrong)),
            'new_errors_introduced':int(np.count_nonzero(~hard_wrong & soft_wrong)),
            'mapping_scope':'same codebook and PN phase acquired on baseline prefix; no evaluation-bit feedback',
            'llr_convention':'log P0/P1, MSB first, clipped to +/-80; uniform symbol priors',
            'waveform_fit':'blind unlabelled samples; codebook is known-pattern calibration, not a generic protocol identification'}


def blind_variants(values):
    corrected,parameters=circular_em(values)
    yield 'blind_circular_em',corrected,parameters
    corrected,parameters=affine_em(values,fit_count=None)
    parameters['fit_scope']='unlabelled full window'
    yield 'blind_affine_em',corrected,parameters
    phase=0.
    for _ in range(8):
        rotated=values*np.exp(-1j*phase)
        decisions=POINTS[slice_labels(rotated)]
        phase=float(np.angle(np.vdot(decisions,values)))
    yield 'blind_phase_only',values*np.exp(-1j*phase),{'phase_radians':phase,'iterations':8,'fit_scope':'unlabelled full window'}
    m2=float(np.mean(abs(values)**2));m4=float(np.mean(abs(values)**4))
    signal_power=np.sqrt(max((2*m2*m2-m4)/.68,1e-12))
    if .25<signal_power<4:
        yield 'blind_m2m4_gain',values/np.sqrt(signal_power),{'signal_power':float(signal_power),'fit_scope':'unlabelled full window'}


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
             'scope':'prefix-trained and declared blind full-window experiments; all results reported, no PRBS feedback or automatic acceptance change',
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
                'receiver_acquisition':decoded.get('acquisition'),'receiver_processing':decoded.get('processing'),
                'reference_fit':fit,
                'source_mean_power':float(np.mean(abs(x)**2)),
                'soft_bit_comparison':soft_comparison(values),
                'variants':{method:dict(summarize(output),parameters=parameters) for method,output,parameters in list(variants(values))+list(blind_variants(values))+list(frontend_variants(x,fs,fit,values))}}
    weak=results['files']['16qam f.csv']['source_mean_power']
    results['weak_capture_noise_comparison']={
        'assumption':'same voltage calibration and representative receiver noise; separate noise recordings, not a calibrated simultaneous SNR measurement',
        'estimates':{name:{'noise_to_total_power_ratio':noise/weak,
                            'excess_power_to_noise_db':float(10*np.log10((weak-noise)/noise)) if 0<noise<weak else None}
                     for name,noise in results['noise_reference_power'].items()}}
    # Preserve measurements even if a regression assertion subsequently fails.
    (root/'receiver-study.json').write_text(json.dumps(results,indent=2))
    print(json.dumps(results,indent=2),flush=True)
    if set(results['files'])!={f'16qam {letter}.csv' for letter in 'abcdef'}:
        raise AssertionError('Expected six laboratory captures in receiver study')
    if any(item['prbs15']['evaluation_bits']!=17904 for capture in results['files'].values() for item in capture['variants'].values()):
        raise AssertionError('Receiver comparison changed the evaluation interval')
    for name,capture in results['files'].items():
        soft=capture['soft_bit_comparison']
        if soft['status']!='measured' or soft['evaluation_bits']!=17904:
            raise AssertionError('Missing bitwise-likelihood comparison')
        baseline=capture['variants']['baseline']['prbs15']['evaluation_error_count']
        if name=='16qam f.csv':
            if not soft['evaluation_error_count']<baseline:raise AssertionError('Weak-capture bitwise gain regression')
        elif soft['evaluation_error_count']!=0:
            raise AssertionError('Bitwise demapping damaged a clean reference')


if __name__=='__main__':main()
