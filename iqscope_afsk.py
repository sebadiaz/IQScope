"""Bounded 1200-baud / 1200–2200-Hz audio trials, accepted by AX.25 UI FCS."""
from fractions import Fraction
import numpy as np
from scipy import signal
from iqscope_ax25 import decode_ax25


def decode_afsk1200(audio,fs,max_seconds=20,max_frames=128,max_flag_pairs=6000):
    result = {'decoder':'afsk1200_ax25','family':'AFSK1200 / AX.25 UI','frames':[],
              'validation_scope':'CRC-16/X-25 and AX.25 UI structure; no APRS semantics or sender authentication',
              'limitations':['Audio frontend only: 1200 baud and 1200/2200-Hz tones, 32 fixed clock phases.',
                             'No frequency/clock tracking, RF FM discriminator, G3RUH or connected-mode AX.25.',
                             'Counts of rejected hypotheses are not a bit/frame error rate.',
                             'Lossy MP3 compression may destroy packet symbols; uncompressed WAV is preferred.']}
    if not 8000<=fs<=48000 or len(audio)<fs*.2:
        return dict(result,status='not_applicable')
    original = len(audio)
    audio = np.asarray(audio[:int(fs*max_seconds)],dtype=float)
    if not np.all(np.isfinite(audio)):
        return dict(result,status='not_applicable')
    ratio = Fraction(48000/fs).limit_denominator(4096)
    waveform = signal.resample_poly(audio,ratio.numerator,ratio.denominator)
    analytic = signal.hilbert(waveform)
    time = np.arange(len(waveform))/48000
    width = 40
    energies = [abs(signal.convolve(analytic*np.exp(-2j*np.pi*f*time),np.ones(width)/width,mode='same'))**2
                for f in (1200,2200)]
    d = (energies[1]-energies[0])/np.maximum(energies[1]+energies[0],1e-20)
    trials = []
    for phase in range(32):
        origin = (phase+.5)*width/32
        centers = np.arange(origin,len(d)-width/2,width)
        values = np.interp(centers,np.arange(len(d)),d)
        trials.append((float(np.mean(abs(values))) if len(values) else 0,phase,centers,values))
    trials.sort(reverse=True,key=lambda t:t[0])
    frames,examined,rejected,phase_trials = [],0,0,0
    exhausted = False
    for _,phase,centers,values in trials:
        if examined>=max_flag_pairs or len(frames)>=max_frames:
            exhausted = True
            break
        phase_trials += 1
        bits = ''.join('1' if value>0 else '0' for value in values)
        candidate = {'bits':bits,'parameters':{'baud':1200,'first_symbol_center_seconds':float(centers[0]/48000)},
                     'channel':{'audio_frequency_hz':1700}}
        trial = decode_ax25([candidate],max_frames=max_frames,max_flag_pairs=max_flag_pairs-examined)
        examined += trial['flag_pairs_examined']
        rejected += trial['crc_rejected']
        exhausted |= trial['budget_exhausted']
        for frame in trial['frames']:
            if any(f['hex']==frame['hex'] and abs(f['time_seconds']-frame['time_seconds'])<2/1200 for f in frames):
                continue
            if len(frames)>=max_frames:
                exhausted = True
                break
            frame['frontend'] = 'audio_afsk1200'
            frame['clock_phase_index'] = phase
            frame['tone_frequencies_hz'] = [1200,2200]
            frames.append(frame)
    frames.sort(key=lambda f:f['time_seconds'])
    result.update(status='validated_frames' if frames else 'no_valid_frames',frames=frames,
                  analyzed_seconds=len(audio)/fs,duration_limited=len(audio)<original,
                  phase_trials=phase_trials,phase_budget=32,flag_pairs_examined=examined,
                  flag_pair_budget=max_flag_pairs,crc_rejected_across_hypotheses=rejected,
                  frame_budget=max_frames,budget_exhausted=exhausted)
    return result
