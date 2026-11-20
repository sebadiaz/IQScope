"""Bounded NOAA APT image candidates from FM IQ; sync evidence, never a CRC claim."""
from fractions import Fraction
import json
import math
from pathlib import Path
import struct
import zlib

import numpy as np
from scipy import signal


WORD_RATE = 4160
LINE_WORDS = 2080
# NOAA KLM User's Guide, section 4.2.3, Fig. 4.2.3-3.
SYNC_A = [0]*4 + [1,1,0,0]*7 + [0]*7
SYNC_B = [0]*4 + [1,1,1,0,0]*7


def _correlation(values, words):
    template = np.repeat(words, 2).astype(float)
    template -= template.mean()
    width = len(template)
    sums = np.concatenate(([0.], np.cumsum(values)))
    squares = np.concatenate(([0.], np.cumsum(values*values)))
    mean = (sums[width:]-sums[:-width])/width
    energy = np.maximum(0, squares[width:]-squares[:-width]-mean**2*width)
    numerator = signal.correlate(values, template, mode='valid', method='direct')
    # Constant envelopes have undefined normalized correlation. Do not turn
    # floating-point cancellation into perfect A/B sync evidence.
    usable = energy>width*np.maximum(mean**2*1e-6,1e-24)
    score = np.divide(numerator,np.sqrt(energy*np.dot(template,template)),out=np.zeros_like(numerator),where=usable)
    return np.clip(score, -1, 1)


def _envelope(x, fs, offset):
    mixed = x*np.exp(-2j*np.pi*offset*np.arange(len(x))/fs)
    down = max(1, math.ceil(fs/96000))
    channel = signal.resample_poly(mixed,1,down) if down>1 else mixed
    rate = fs/down
    channel = signal.convolve(channel,signal.firwin(129,min(22000,rate*.45),fs=rate),mode='same')
    audio = np.angle(channel[1:]*np.conj(channel[:-1]))*rate/(2*np.pi)
    # Centered filters preserve the sample clock; no FM audio de-emphasis.
    audio = signal.convolve(audio,signal.firwin(257,[400,4500],pass_zero=False,fs=rate),mode='same')
    ratio = Fraction(20800/rate).limit_denominator(4096)
    audio = signal.resample_poly(audio,ratio.numerator,ratio.denominator)
    audio_rate = rate*ratio.numerator/ratio.denominator
    envelope = abs(signal.hilbert(audio))
    envelope = signal.convolve(envelope,signal.firwin(129,2000,fs=audio_rate),mode='same')
    ratio2 = Fraction(8320/audio_rate).limit_denominator(4096)
    envelope = signal.resample_poly(envelope,ratio2.numerator,ratio2.denominator)
    envelope_rate = audio_rate*ratio2.numerator/ratio2.denominator
    return envelope,envelope_rate,dict(tuning_offset_hz=float(offset),input_sample_rate=float(fs),
        channel_sample_rate=float(rate),envelope_sample_rate=float(envelope_rate),
        discriminator_start_seconds=.5/rate,filter_delay_compensated=True,edge_padding='zero',
        audio_bandpass_hz=[400,4500],fm_deemphasis=False)


def _image(envelope,rate,channel,max_lines):
    a = _correlation(envelope,SYNC_A)
    b = _correlation(envelope,SYNC_B)
    peaks,_ = signal.find_peaks(a,height=.65,distance=int(rate*.45))
    # Guard against FIR/resampling/Hilbert boundary transients.
    peaks = peaks[(peaks>rate*.02)&(peaks<len(envelope)-rate*.02)]
    best=[];run=[];runs=0
    for start,end in zip(peaks,peaks[1:]):
        period = (end-start)/rate
        middle = (start+end)/2
        lo=max(0,int(middle)-8);hi=min(len(b),int(middle)+9)
        second = lo+int(np.argmax(b[lo:hi])) if hi>lo else 0
        valid = .495<=period<=.505 and hi>lo and b[second]>=.60
        if valid:
            if run and run[-1][1]!=start:
                if len(run)>len(best):best=run
                run=[]
            run.append((int(start),int(end),int(second)))
        else:
            if len(run)>len(best):best=run
            if run:runs+=1
            run=[]
    if len(run)>len(best):best=run
    if run:runs+=1
    if len(best)<3:return None,dict(sync_a_peaks=len(peaks),longest_dual_sync_run=len(best),sync_runs=runs)
    selected=best[:max_lines]
    # Fit each observed line independently; never fill a missing line.
    grid=np.arange(len(envelope))
    rows=np.array([np.interp(start+(np.arange(LINE_WORDS)+.5)*(end-start)/LINE_WORDS,grid,envelope)
                   for start,end,_ in selected])
    low,high=np.percentile(rows,[1,99])
    if high<=low or not np.isfinite(high):return None,dict(sync_a_peaks=len(peaks),longest_dual_sync_run=len(best))
    pixels=np.rint(np.clip((rows-low)/(high-low),0,1)*255).astype('u1')
    origin=channel['discriminator_start_seconds']
    evidence=[dict(time_seconds=start/rate+origin,time_end_seconds=end/rate+origin,
                   sync_a_correlation=float(a[start]),next_sync_a_correlation=float(a[end]),
                   sync_b_correlation=float(b[second]),sync_b_offset_words=(second-start)*LINE_WORDS/(end-start),
                   measured_line_seconds=(end-start)/rate,
                   clock_error_ppm=((end-start)/rate/.5-1)*1e6) for start,end,second in selected]
    image=dict(width=LINE_WORDS,height=len(selected),pixels_u8_hex=pixels.tobytes().hex(),
        channel=channel,time_seconds=evidence[0]['time_seconds'],time_end_seconds=evidence[-1]['time_end_seconds'],
        lines=evidence,channel_image_columns=dict(A=[86,995],B=[1126,2035]),
        column_interval='zero-based half-open',line_order='reception order; no geographic orientation inferred',
        pixel_encoding='uint8 row-major display-normalized AM envelope; not transmitted digital bytes',
        normalization=dict(method='linear 1st/99th percentile of the selected full lines, rounded and clipped',
                           envelope_low=float(low),envelope_high=float(high),envelope_units='FM discriminator Hz'),
        line_budget_exhausted=len(best)>len(selected))
    return image,dict(sync_a_peaks=len(peaks),longest_dual_sync_run=len(best),sync_runs=runs)


def search_apt(x,fs,bands,center_hz=0,max_channels=2,max_seconds=20,max_lines=40):
    result=dict(decoder='noaa_apt',family='NOAA APT / FM-AM images',images=[],channels_examined=[],
        validation_scope='Repeated A/B sync and line timing only; analog images have no CRC or authenticated satellite identity',
        budgets=dict(channels=min(2,max(0,max_channels)),seconds=min(20,max(0,max_seconds)),input_samples=8000000,
                     lines_per_image=min(40,max(0,max_lines))),
        limitations=['48 kS/s to 2.4 MS/s complex IQ; at most two automatic spectral/baseband channels, twenty seconds and eight million samples.',
            'Requires at least three consecutive full lines with A correlation >=0.65, B >=0.60 and 0.495-0.505 second spacing.',
            'Only the longest contiguous dual-sync run per channel is exported; gaps are not filled or joined across windows.',
            'Pixels are contrast-normalized envelope intensity, not radiometric measurements, temperatures or calibrated 8-bit source words.',
            'No telemetry calibration, spectral-band identification, geolocation, map overlays or satellite identification.',
            'Historical NOAA APT recordings; no claim that retired NOAA satellites are currently transmitting.'])
    if (not math.isfinite(fs) or not 48000<=fs<=2400000 or not math.isfinite(center_hz)
            or not np.iscomplexobj(x) or np.ndim(x)!=1 or len(x)<fs*2 or result['budgets']['lines_per_image']<3):
        return dict(result,status='not_applicable')
    count=min(len(x),int(fs*result['budgets']['seconds']),8000000)
    samples=np.asarray(x[:count])
    if len(samples)<fs*2 or not np.all(np.isfinite(samples)):return dict(result,status='not_applicable')
    offsets=[]
    for band in sorted(bands,key=lambda b:b.get('spectral_snr_db',0),reverse=True):
        offset=band.get('offset_hz',float('nan'))
        if (18000<=band.get('bandwidth_hz',0)<=60000 and math.isfinite(offset)
                and abs(offset)+22000<fs/2 and all(abs(offset-v)>6000 for v in offsets)):
            offsets.append(float(offset))
    if all(abs(v)>6000 for v in offsets):offsets.append(0.)
    for offset in offsets[:result['budgets']['channels']]:
        values,rate,frontend=_envelope(samples,fs,offset)
        frontend.update(offset_hz=offset,frequency_hz=float(center_hz+offset),rf_center_known=center_hz!=0)
        image,evidence=_image(values,rate,frontend,result['budgets']['lines_per_image'])
        result['channels_examined'].append(dict(frontend,**evidence,status='image_candidate' if image else 'no_image'))
        if image:result['images'].append(image)
    return dict(result,status='image_candidates' if result['images'] else 'no_image',
        analyzed_seconds=count/fs,duration_limited=count<len(x),deferred_channel_count=max(0,len(offsets)-result['budgets']['channels']))


def _png(pixels):
    """Encode measured grayscale pixels as PNG without an imaging dependency."""
    def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    height,width=pixels.shape
    raw=b''.join(b'\x00'+row.tobytes() for row in pixels)
    return (b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,0,0,0,0))
            +chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b''))


def write_apt_artifacts(trial,out):
    if not trial['images']:return
    out=Path(out)
    for index,image in enumerate(trial['images'],1):
        pixels=np.frombuffer(bytes.fromhex(image['pixels_u8_hex']),dtype='u1').reshape(image['height'],image['width'])
        prefix=f'apt-{index:02d}'
        image['artifacts']=dict(full=prefix+'.png',A=prefix+'-a.png',B=prefix+'-b.png',
                                pixels=prefix+'-pixels.bin',csv=prefix+'-pixels.csv')
        for key,values in [('full',pixels),('A',pixels[:,86:995]),('B',pixels[:,1126:2035])]:
            (out/image['artifacts'][key]).write_bytes(_png(values))
        (out/image['artifacts']['pixels']).write_bytes(pixels.tobytes())
        np.savetxt(out/image['artifacts']['csv'],pixels,delimiter=',',fmt='%d',
                   header='display-normalized uint8 intensity; rows in reception order; 2080 columns; no radiometric calibration',comments='# ')
    trial['artifact']='apt-images.json'
    (out/trial['artifact']).write_text(json.dumps(trial,indent=2))
