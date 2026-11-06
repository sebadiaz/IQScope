"""Bounded inspection of a pinned conducted RF laboratory capture archive."""
import hashlib
import csv
import io
import json
from pathlib import Path
import sys
import urllib.request
import zipfile
import xml.etree.ElementTree as ET

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from iqscope_qam import decode_qam16
from iqscope_psk_rrc import _line

PIN='3f9ea40d9b187d0819b14cb254dc04905d398889'
URL=f'https://raw.githubusercontent.com/billjgavin/28_and_75GHz_Capture_Files/{PIN}/IQ_28_Ghz.zip'
BLOB='fa11ded813f4407afb6c9cad3ac37dc4c135dced'
SIZE=8425587
SHA256='4959f58182b54a8ba25893106be939f34716d0c3832afa4d88d1658e54844240'


def read_keysight_csv(raw):
    """BASIC:WAV result 0: alternating I/Q, result 1: scalar metadata."""
    rows=list(csv.reader(io.StringIO(raw.decode('utf-8-sig'))))
    if rows[:2]!=[['MeasResult'],['BASIC:WAV']]:
        raise ValueError('Unsupported instrument export')
    start=rows.index(['MeasResult0','MeasResult1','MeasResult2'])
    header={row[0]:row[1] for row in rows[:start] if len(row)==2}
    data=rows[start+1:]
    scalars=[float(row[1]) for row in data if len(row)>1 and row[1]]
    if len(scalars)!=7:raise ValueError('Expected seven waveform scalar results')
    dt=scalars[0];count=int(scalars[3])
    values=np.array([float(row[0]) for row in data if row and row[0]])
    if not 0<dt<=.001 or not 1024<=count<=288000 or scalars[3]!=count:
        raise ValueError('Invalid waveform interval or count')
    if len(values)!=2*count or not np.all(np.isfinite(values)):
        raise ValueError('IQ point count or finite-value check failed')
    duration=float(header['WAV_Used_CaptureTime'])
    if not np.isclose((count-1)*dt,duration,rtol=1e-6,atol=dt/100):
        raise ValueError('Sample interval, count and capture duration disagree')
    x=values[::2]+1j*values[1::2]
    return x,1/dt,{'sample_interval_seconds':dt,'sample_count':count,
                  'capture_duration_seconds':duration,'center_frequency_hz':float(header['Center Frequency']),
                  'format':'BASIC:WAV result 0, alternating I then Q; result 1 scalars',
                  'sample_rate_basis':'inverse of first MeasResult1 scalar, checked against point count and capture duration'}


def trial_summary(raw):
    x,fs,layout=read_keysight_csv(raw)
    trial=decode_qam16(x,fs)
    normalized=x/np.sqrt(np.mean(abs(x)**2))
    energy=abs(normalized)**2
    clock=_line(energy-energy.mean(),32000,30,8000,.001)
    carrier=_line(normalized**4,32000,-16000,16000,.005)
    return {'layout':layout,'source_sha256':hashlib.sha256(raw).hexdigest(),
            'status':trial['status'],'processing':trial.get('processing'),
            'diagnostics':{'clock_baud':clock[0]*fs/32000 if clock else None,
                           'clock_energy_fraction':clock[1] if clock else None,
                           'carrier_offset_hz':carrier[0]/4*fs/32000 if carrier else None,
                           'carrier_energy_fraction':carrier[1] if carrier else None},
            'candidates':[{'symbol_count':c['symbol_count'],'parameters':c['parameters'],
                           'evidence':c['evidence']} for c in trial['candidates']],
            'validation':'structural constellation only; upstream filename is a modulation label, not decoded ground-truth bits or CRC'}


def main():
    root=Path('corpus-cache/qam-lab');root.mkdir(parents=True,exist_ok=True)
    with urllib.request.urlopen(URL,timeout=45) as response:data=response.read(SIZE+1)
    if len(data)!=SIZE or hashlib.sha1(b'blob '+str(SIZE).encode()+b'\0'+data).hexdigest()!=BLOB or hashlib.sha256(data).hexdigest()!=SHA256:
        raise ValueError('Pinned archive size or Git blob hash mismatch')
    (root/'IQ_28_Ghz.zip').write_bytes(data)
    result={'source_url':URL,'source_git_blob':BLOB,'source_sha256':hashlib.sha256(data).hexdigest(),
            'source_bytes':len(data),'origin':'conducted laboratory RF acquisition per upstream README; not radiated',
            'sample_rate_hz_declared':200e6,'symbol_rate_baud_declared':50e6,
            'license':'not established; no raw IQ redistributed','members':[],'previews':[],
            'qam_trials':{},'embedded_readme_text':[]}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members=archive.infolist()
        if len(members)>2000:raise ValueError('Too many archive members')
        for member in members:
            result['members'].append({'name':member.filename,'bytes':member.file_size})
        selected=[m for m in members if not m.is_dir() and ('16qam' in m.filename.lower() or m.filename.lower().endswith('.m'))]
        for member in selected[:10]:
            if member.file_size>2_000_000:continue
            raw=archive.read(member)
            result['previews'].append({'name':member.filename,'sha256':hashlib.sha256(raw).hexdigest(),
                                       'prefix_hex':raw[:32].hex(),'text_prefix':raw[:1800].decode('utf-8',errors='replace')})
        for member in members:
            if member.file_size>2_000_000:continue
            if member.filename.lower().endswith('.csv'):
                result['qam_trials'][member.filename]=trial_summary(archive.read(member))
            elif member.filename.lower().endswith('.docx'):
                with zipfile.ZipFile(io.BytesIO(archive.read(member))) as doc:
                    info=doc.getinfo('word/document.xml')
                    if info.file_size>100000:raise ValueError('Oversized embedded readme')
                    xml=ET.fromstring(doc.read(info))
                    text=' '.join(t.text or '' for t in xml.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t'))
                    result['embedded_readme_text'].append({'name':member.filename,'text':text})
    (root/'inspection.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
