"""Bounded NBFM IQ to AFSK1200/AX.25 frames, with strict FCS and control-layout inspection."""
from fractions import Fraction
import math
import numpy as np
from scipy import signal

from iqscope_afsk import decode_afsk1200
from iqscope_ax25 import encode_kiss_frame
from iqscope_aprs_calibration import enrich_aprs_telemetry_frames


def _demodulate(x, fs, offset):
    mixed = x*np.exp(-2j*np.pi*offset*np.arange(len(x))/fs)
    down = max(1, math.ceil(fs/48000))
    channel = signal.resample_poly(mixed, 1, down) if down>1 else mixed
    rate = fs/down
    channel = signal.convolve(channel, signal.firwin(129, min(8000, rate*.4), fs=rate), mode='same')
    power = np.minimum(abs(channel[1:])**2, abs(channel[:-1])**2)
    gate = power>max(float(np.percentile(power,99))*.01, 1e-24)
    frequency = np.angle(channel[1:]*np.conj(channel[:-1]))*rate/(2*np.pi)
    dc = float(np.median(frequency[gate])) if np.any(gate) else 0.
    audio = np.where(gate, frequency-dc, 0.)
    audio = signal.convolve(audio, signal.firwin(65, min(3400, rate*.4), fs=rate), mode='same')
    ratio = Fraction(12000/rate).limit_denominator(4096)
    audio = signal.resample_poly(audio, ratio.numerator, ratio.denominator)
    audio_rate = rate*ratio.numerator/ratio.denominator
    metadata = dict(tuning_offset_hz=float(offset), input_sample_rate=float(fs), channel_sample_rate=float(rate),
                    decimation=down, audio_sample_rate=float(audio_rate), audio_start_seconds=.5/rate,
                    discriminator_dc_hz=dc, estimated_offset_hz=float(offset+dc),
                    frequency_estimate='FM discriminator median after spectral/baseband tuning; affected by modulation DC',
                    filter_delay_compensated=True, edge_padding='zero',
                    squelch_power_fraction_of_p99=.01, source_sample_start=0, source_sample_end=len(x))
    return audio, audio_rate, metadata


def search_afsk_fm(x, fs, bands, center_hz=0, max_channels=8, max_seconds=20,
                   max_frames=128, max_flag_pairs=6000):
    result = dict(decoder='afsk1200_fm_ax25', family='Narrowband FM / AFSK1200 / AX.25 UI/I/S/U',
                  frames=[], channels_examined=[], frequency_reference='input_iq_center',
                  validation_scope='CRC-16/X-25 plus bounded UI/I/S/U address/control inspection; I-frame mode and application payload can remain unresolved',
                  limitations=['Complex IQ at 20 kS/s to 2.4 MS/s; at most 20 seconds and 8 million input samples.',
                               'At most eight detected bands of 2-24 kHz, plus a baseband fallback within that budget for input <=96 kS/s.',
                               'Shared stationary detector may miss weak, overlapping or short bursts; FM channel low-pass at at most 8 kHz.',
                               'FM discriminator, compensated FIR/resampling and 1% of p99 channel-power squelch; no FM deemphasis or adjacent-channel cancellation.',
                               'AFSK clock fits within +/-3% of 1200 baud; no tone-frequency estimation, link-session reconstruction or G3RUH-over-FM.',
                               'Spectral/DC frequency estimates and declared RF center do not authenticate a transmitter.'])
    if (not math.isfinite(fs) or not 20000<=fs<=2400000 or not math.isfinite(center_hz)
            or len(x)<fs*.2 or not np.iscomplexobj(x)):
        return dict(result, status='not_applicable')
    original = len(x)
    count = min(original, int(fs*min(20,max(0,max_seconds))), 8000000)
    x = np.asarray(x[:count])
    if x.ndim!=1 or len(x)<fs*.2 or not np.all(np.isfinite(x)):
        return dict(result, status='not_applicable')
    eligible = [b for b in bands if 2000<=b.get('bandwidth_hz',0)<=24000
                and math.isfinite(b.get('offset_hz',float('nan'))) and abs(b['offset_hz'])<fs/2]
    offsets = []
    for band in sorted(eligible, key=lambda b:b.get('spectral_snr_db',0), reverse=True):
        if all(abs(band['offset_hz']-v)>1500 for v in offsets):
            offsets.append(float(band['offset_hz']))
    if fs<=96000 and all(abs(v)>1500 for v in offsets):
        offsets.append(0.)
    limit = min(8,max(0,max_channels))
    selected = offsets[:limit]
    frames, examined = [], 0
    exhausted = False
    for index, offset in enumerate(selected):
        if len(frames)>=max_frames or examined>=max_flag_pairs:
            exhausted = True
            break
        audio, audio_rate, channel = _demodulate(x, fs, offset)
        # Reserve a share of the global flag budget for each remaining channel.
        quota = max(1, (max_flag_pairs-examined)//(len(selected)-index))
        trial = decode_afsk1200(audio, audio_rate, max_seconds=20,
                                max_frames=max_frames-len(frames), max_flag_pairs=quota,accept_link_frames=True)
        examined += trial.get('flag_pairs_examined',0)
        exhausted |= trial.get('budget_exhausted',False)
        result['channels_examined'].append(dict(channel, status=trial['status'],
            accepted_frames=len(trial['frames']), flag_pairs_examined=trial.get('flag_pairs_examined',0),
            flag_pair_budget=quota, budget_exhausted=trial.get('budget_exhausted',False),
            timing_trials=trial.get('timing_trials',[])))
        for frame in trial['frames']:
            frame['time_seconds'] += channel['audio_start_seconds']
            frame['time_end_seconds'] += channel['audio_start_seconds']
            if 'timing_evidence' in frame:
                frame['timing_evidence']['time_reference'] = 'demodulated_audio_start; add fm_frontend.audio_start_seconds for source IQ time'
            frame['demodulated_audio_channel'] = frame['channel']
            frame['frontend'] = 'fm_iq_afsk1200'
            frame['channel'] = dict(offset_hz=channel['estimated_offset_hz'],
                frequency_hz=float(center_hz+channel['estimated_offset_hz']),
                tuning_offset_hz=offset, sample_rate=channel['channel_sample_rate'],
                frequency_estimate=channel['frequency_estimate'],
                rf_center_known=center_hz!=0)
            frame['fm_frontend'] = channel.copy()
            if any(f['hex']==frame['hex'] and abs(f['time_seconds']-frame['time_seconds'])<2/1200
                   and abs(f['channel']['offset_hz']-frame['channel']['offset_hz'])<500 for f in frames):
                continue
            frames.append(frame)
    frames.sort(key=lambda f:f['time_seconds'])
    return dict(result, status='validated_frames' if frames else 'no_valid_frames',
                frames=enrich_aprs_telemetry_frames(frames),
                analyzed_seconds=len(x)/fs, duration_limited=len(x)<original,
                channel_budget=limit, deferred_channel_count=max(0,len(offsets)-len(selected)),
                excluded_wide_band_count=sum(b.get('bandwidth_hz',0)>24000 for b in bands),
                flag_pairs_examined=examined, flag_pair_budget=max_flag_pairs,
                frame_budget=max_frames, budget_exhausted=exhausted)


def write_afsk_fm_artifact(trial, out):
    if trial['frames']:
        import json
        from pathlib import Path
        # Build the entire stream before writing any exports: a bad FCS aborts
        # the export rather than silently dropping or altering a received frame.
        kiss = b''.join(encode_kiss_frame(bytes.fromhex(f['hex'])) for f in trial['frames'])
        for index,frame in enumerate(trial['frames'],1):
            frame['wire_artifact'] = f'fm-ax25-frame-{index}.bin'
            (Path(out)/frame['wire_artifact']).write_bytes(bytes.fromhex(frame['hex']))
            if frame['fields']['frame_type']=='UI':
                frame['payload_artifact'] = f'fm-ax25-payload-{index}.bin'
                (Path(out)/frame['payload_artifact']).write_bytes(bytes.fromhex(frame['fields']['payload_hex']))
        trial['kiss_artifact'] = 'fm-ax25-frames.kiss'
        trial['kiss_export'] = dict(format='KISS', command=0, port=0, frame_count=len(trial['frames']),
                                   fcs_included=False, timestamps_included=False,
                                   channel_mapping='single virtual receive port; RF channels and times remain in this JSON',
                                   frame_order='same as frames; separated repetitions retained',
                                   application_interpretation='unchanged; no link mode or application payload selected by export')
        (Path(out)/trial['kiss_artifact']).write_bytes(kiss)
        trial['artifact'] = 'fm-afsk-frames.json'
        (Path(out)/trial['artifact']).write_text(json.dumps(trial, indent=2))
