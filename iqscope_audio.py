"""Explicit bounded receiver-audio import. Audio is never represented as RF IQ."""
import json
from pathlib import Path
import shutil
import subprocess

import numpy as np
from scipy import signal
from scipy.io import wavfile
from iqscope_cw import search_cw


def decode_audio(path,seconds=20):
    path = Path(path)
    if path.suffix.lower() not in ('.mp3','.wav'):
        raise ValueError('Receiver audio must be MP3 or WAV')
    if not 1<=seconds<=20:
        raise ValueError('Audio duration must be 1 to 20 seconds')
    if not shutil.which('ffmpeg'):
        raise ValueError('Audio import requires ffmpeg installed on PATH')
    process = subprocess.run(['ffmpeg','-nostdin','-v','quiet','-protocol_whitelist','file,pipe',
                              '-f','mp3' if path.suffix.lower()=='.mp3' else 'wav','-i',str(path),
                              '-t',str(seconds),'-ac','1','-ar','8000',
                              '-f','f32le','pipe:1'],capture_output=True,timeout=20)
    if process.returncode or not process.stdout:
        raise ValueError('ffmpeg could not decode this audio input')
    if len(process.stdout)>seconds*8000*4:
        raise ValueError('Decoded audio exceeded duration budget')
    audio = np.frombuffer(process.stdout,dtype='<f4')
    if len(audio)<8000 or not np.all(np.isfinite(audio)):
        raise ValueError('Need at least one second of finite decoded audio')
    return audio,8000


def analyze_audio(path,out,seconds=20):
    audio,fs = decode_audio(path,seconds)
    out = Path(out)
    out.mkdir(parents=True,exist_ok=True)
    cw = search_cw(signal.hilbert(audio),fs)
    for candidate in cw['candidates']:
        candidate['channel'] = {'audio_frequency_hz':candidate['channel']['frequency_hz']}
    for channel in cw.get('channels_examined',[]):
        channel['audio_frequency_hz'] = channel.pop('frequency_hz')
        channel.pop('offset_hz',None)
    frequency,power = signal.welch(audio,fs,nperseg=min(1024,len(audio)))
    power_db = 10*np.log10(np.maximum(power,1e-30))
    size = 512
    starts = np.unique(np.linspace(0,len(audio)-size,min(96,len(audio)//size),dtype=int))
    window = np.hanning(size)
    rows = np.array([audio[start:start+size]*window for start in starts])
    waterfall = 10*np.log10(np.maximum(abs(np.fft.rfft(rows,axis=1))**2/(fs*np.sum(window**2)),1e-30))
    wavfile.write(out/'audio-preview.wav',fs,(np.clip(audio,-1,1)*32767).astype(np.int16))
    report = {'schema_version':'0.3','source':str(path),'source_kind':'receiver_audio',
              'sample_rate':fs,'center_frequency_hz':None,'frequency_reference':'audio_hz',
              'analyzed_seconds':len(audio)/fs,'requested_seconds':seconds,
              'duration_scope':'At most the requested first audio seconds; source duration is not measured.',
              'audio_artifact':'audio-preview.wav','signals':[],'wideband_trials':[cw],
              'spectrum':{'frequency_hz':frequency.tolist(),'power_db':power_db.tolist()},
              'waterfall':{'power_db':waterfall.tolist(),'time_seconds':(starts/fs).tolist(),'sampled_windows':True},
              'capabilities':[{'id':'cw_morse','family':'CW / Morse','validation':'timing candidates only; no checksum'}],
              'limitations':['Receiver audio, not original RF IQ; no RF center, phase or original bandwidth can be recovered.',
                             'Mono mixdown at 8 kHz; stereo cancellation and lossy compression may affect results.',
                             'Only CW text trials are enabled for audio; no voice transcription or military protocol decoding.',
                             'First 1–20 seconds only; CW text remains a timing candidate, not a verified transcript.']}
    if cw['candidates']:
        (out/'cw-candidate.txt').write_text(cw['candidates'][0]['text'],encoding='utf-8')
    (out/'report.json').write_text(json.dumps(report,indent=2))
    return report
