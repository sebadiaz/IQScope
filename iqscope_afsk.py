"""Bounded nominal-1200-baud audio trials with transition clocks and strict UI FCS."""
from fractions import Fraction
import numpy as np
from scipy import signal
from iqscope_ax25 import decode_ax25
from iqscope_aprs_calibration import enrich_aprs_telemetry_frames


def _transition_clocks(d, power):
    """Fit at most sixteen coherent edge chains; never infer content or repair bits."""
    width = 40.
    indices = np.flatnonzero(np.diff(d > 0))
    edges = indices-d[indices]/(d[indices+1]-d[indices])
    grid = np.arange(len(d))
    edges = edges[np.interp(edges, grid, power) > .03*float(np.max(power))]
    edge_count = len(edges)
    if len(edges) > 50000:
        return [], [], dict(clock_edge_budget_exhausted=True, clock_fit_budget_exhausted=False,
                            clock_edges=len(edges), clock_groups=0)
    gaps = np.diff(edges)
    # Stuffed HDLC data/flags have no arbitrarily long constant NRZI runs.
    # Split silence, missing transitions and implausibly close crossings.
    groups = np.split(edges, np.flatnonzero((gaps > 8.5*width) | (gaps < .45*width))+1)
    groups = sorted((e for e in groups if len(e) >= 24 and e[-1]-e[0] >= 4800),
                    key=len, reverse=True)
    trials, diagnostics = [], []
    for edges in groups[:16]:
        numbers = np.r_[0, np.cumsum(np.round(np.diff(edges)/width))]
        period, origin = np.polyfit(numbers, edges-edges[0], 1)
        origin += edges[0]
        baud = float(48000/period)
        residual = float(np.sqrt(np.mean(((edges-origin)/period-numbers)**2)))
        accepted = abs(baud/1200-1) <= .03 and residual <= .1
        evidence = dict(method='transition_fit', estimated_baud=baud, transitions=len(edges),
                        residual_rms_symbols=residual, timing_accepted=bool(accepted),
                        edge_start_seconds=float(edges[0]/48000), edge_end_seconds=float(edges[-1]/48000))
        diagnostics.append(evidence)
        if not accepted:
            continue
        first = origin+period/2
        left, right = max(0, edges[0]-8*period), min(len(d)-20, edges[-1]+8*period)
        lo, hi = int(np.ceil((left-first)/period)), int(np.floor((right-first)/period))+1
        centers = first+np.arange(lo, hi)*period
        if len(centers):
            trials.append((None, baud, centers, np.interp(centers, grid, d), evidence))
    return trials, diagnostics, dict(clock_edge_budget_exhausted=False,
                                    clock_fit_budget_exhausted=len(groups)>16,
                                    clock_edges=edge_count,
                                    clock_groups=len(groups))


def decode_afsk1200(audio,fs,max_seconds=20,max_frames=128,max_flag_pairs=6000):
    result = {'decoder':'afsk1200_ax25','family':'AFSK1200 / AX.25 UI','frames':[],
              'validation_scope':'CRC-16/X-25 and AX.25 UI structure; optional APRS position/telemetry definitions are declared content, not independent content or sender verification',
              'limitations':['Audio frontend only: nominal 1200 baud and 1200/2200-Hz tones; 32 fixed phases plus at most 16 transition-clock fits.',
                             'Clock fits require 24 transitions over 0.1 second, rate within +/-3% and RMS residual <=0.1 symbol; power gate at 3% of peak tone energy.',
                             'No tone-frequency estimation, intra-burst clock tracking, RF FM discriminator, G3RUH or connected-mode AX.25.',
                             'Counts of rejected hypotheses are not a bit/frame error rate.',
                             'Telemetry definitions are self-addressed, same source/SSID and channel, received before sample and at most 600 seconds old; no cross-window state.',
                             'Lossy MP3 compression may destroy packet symbols; uncompressed WAV is preferred.']}
    if not 8000<=fs<=48000 or len(audio)<fs*.2:
        return dict(result,status='not_applicable')
    original = len(audio)
    audio = np.asarray(audio[:int(fs*min(20,max(0,max_seconds)))],dtype=float)
    if audio.ndim!=1 or len(audio)<fs*.2 or not np.all(np.isfinite(audio)):
        return dict(result,status='not_applicable')
    ratio = Fraction(48000/fs).limit_denominator(4096)
    waveform = signal.resample_poly(audio,ratio.numerator,ratio.denominator)
    analytic = signal.hilbert(waveform)
    time = np.arange(len(waveform))/48000
    width = 40
    energies = [abs(signal.convolve(analytic*np.exp(-2j*np.pi*f*time),np.ones(width)/width,mode='same'))**2
                for f in (1200,2200)]
    power = energies[1]+energies[0]
    d = (energies[1]-energies[0])/np.maximum(power,1e-20)
    trials = []
    for phase in range(32):
        origin = (phase+.5)*width/32
        centers = np.arange(origin,len(d)-width/2,width)
        values = np.interp(centers,np.arange(len(d)),d)
        trials.append((float(np.mean(abs(values))) if len(values) else 0,phase,centers,values))
    trials.sort(reverse=True,key=lambda t:t[0])
    fitted, diagnostics, clock_limits = _transition_clocks(d, power)
    trials = fitted+[(phase,1200.,centers,values,None) for _,phase,centers,values in trials]
    frames,examined,rejected,phase_trials,clock_fit_trials = [],0,0,0,0
    exhausted = False
    for phase,baud,centers,values,evidence in trials:
        if examined>=max_flag_pairs or len(frames)>=max_frames:
            exhausted = True
            break
        if evidence is None:
            phase_trials += 1
        else:
            clock_fit_trials += 1
        bits = ''.join('1' if value>0 else '0' for value in values)
        candidate = {'bits':bits,'parameters':{'baud':baud,'first_symbol_center_seconds':float(centers[0]/48000)},
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
            frame['clock_recovery'] = 'fixed_phase' if evidence is None else 'transition_fit'
            frame['clock_baud'] = baud
            if evidence is None:
                frame['clock_phase_index'] = phase
            else:
                frame['timing_evidence'] = evidence.copy()
            frame['tone_frequencies_hz'] = [1200,2200]
            frames.append(frame)
    frames.sort(key=lambda f:f['time_seconds'])
    result.update(status='validated_frames' if frames else 'no_valid_frames',frames=enrich_aprs_telemetry_frames(frames),
                  analyzed_seconds=len(audio)/fs,duration_limited=len(audio)<original,
                  phase_trials=phase_trials,phase_budget=32,flag_pairs_examined=examined,
                  clock_fit_trials=clock_fit_trials,clock_fit_budget=16,clock_edge_budget=50000,
                  timing_trials=diagnostics,**clock_limits,
                  flag_pair_budget=max_flag_pairs,crc_rejected_across_hypotheses=rejected,
                  frame_budget=max_frames,budget_exhausted=exhausted)
    return result
