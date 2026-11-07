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
from scripts.qam_prbs15 import check_prbs15

PIN='3f9ea40d9b187d0819b14cb254dc04905d398889'
URL=f'https://raw.githubusercontent.com/billjgavin/28_and_75GHz_Capture_Files/{PIN}/IQ_28_Ghz.zip'
BLOB='fa11ded813f4407afb6c9cad3ac37dc4c135dced'
SIZE=8425587
SHA256='4959f58182b54a8ba25893106be939f34716d0c3832afa4d88d1658e54844240'
FORMAT_REFERENCE='https://www.keysight.com/so/en/assets/9018-04709/user-manuals/9018-04709.pdf'


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


def candidate_summary(candidate):
    shuffled=np.random.default_rng(20261107).permutation(candidate['symbols'])
    control=check_prbs15(shuffled)
    return {'symbol_count':candidate['symbol_count'],'parameters':candidate['parameters'],
            'evidence':candidate['evidence'],'prbs15':check_prbs15(candidate['symbols']),
            'prbs15_shuffled_control':{'status':control['status'],
                                     'evaluation_ber':control.get('evaluation_ber')}}


def trial_summary(raw,diagnose=False):
    x,fs,layout=read_keysight_csv(raw)
    rejected_fits=[]
    def observe(diagnostic,labels):
        control=check_prbs15(np.random.default_rng(20261107).permutation(labels))
        rejected_fits.append({'fit':diagnostic,'prbs15':check_prbs15(labels),
                              'shuffled_control':{'status':control['status'],'evaluation_ber':control.get('evaluation_ber')},
                              'scope':'diagnostic of fixed RRC trials; labels remain rejected by the generic quality gates'})
    trial=decode_qam16(x,fs,trial_observer=observe if diagnose else None)
    acquisition=trial.get('acquisition',{})
    return {'layout':layout,'source_sha256':hashlib.sha256(raw).hexdigest(),
            'status':trial['status'],'processing':trial.get('processing'),
            'rejection_reason':trial.get('rejection_reason'),'filter_trials':trial['filter_trials'],
            'rejected_fit_diagnostics':rejected_fits,
            'diagnostics':{'clock_baud':acquisition.get('clock_baud'),
                           'clock_energy_fraction':acquisition.get('clock_line_energy_fraction'),
                           'carrier_offset_hz':acquisition.get('carrier_offset_hz'),
                           'carrier_energy_fraction':acquisition.get('carrier_line_energy_fraction'),
                           'clock_search_mode':acquisition.get('clock_search_mode'),
                           'clock_boundary_margin_baud':acquisition.get('clock_boundary_margin_baud')},
            'candidates':[candidate_summary(c) for c in trial['candidates']],
            'validation':'structural constellation plus separately reported known PRBS15 test-pattern comparison; no protocol or CRC'}


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
            'qam_trials':{},'embedded_readme_text':[], 'format_reference':FORMAT_REFERENCE,
            'regression_oracle':'expected structural outcomes observed during development; no independent bit oracle'}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members=archive.infolist()
        if len(members)>2000:raise ValueError('Too many archive members')
        for member in members:
            result['members'].append({'name':member.filename,'bytes':member.file_size})
        selected=[m for m in members if not m.is_dir() and ('16qam' in m.filename.lower() or m.filename.lower().endswith('.m'))]
        for member in selected[:10]:
            if member.file_size>2_000_000:continue
            raw=archive.read(member)
            preview=raw[:1800].decode('utf-8',errors='replace')
            if member.filename.lower().endswith('.csv'):
                preview=preview.split('MeasResult0,MeasResult1,MeasResult2')[0]
            result['previews'].append({'name':member.filename,'sha256':hashlib.sha256(raw).hexdigest(),
                                       'prefix_hex':raw[:32].hex(),'text_prefix':preview})
        for member in members:
            if member.file_size>2_000_000:continue
            if member.filename.lower().endswith('.csv'):
                result['qam_trials'][member.filename]=trial_summary(archive.read(member),diagnose=Path(member.filename).name=='16qam f.csv')
            elif member.filename.lower().endswith('.docx'):
                with zipfile.ZipFile(io.BytesIO(archive.read(member))) as doc:
                    info=doc.getinfo('word/document.xml')
                    if info.file_size>100000:raise ValueError('Oversized embedded readme')
                    xml=ET.fromstring(doc.read(info))
                    text=' '.join(t.text or '' for t in xml.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t'))
                    result['embedded_readme_text'].append({'name':member.filename,'text':text})
    (root/'inspection.json').write_text(json.dumps(result,indent=2))
    accepted={Path(name).name for name,trial in result['qam_trials'].items() if trial['candidates']}
    expected={f'16qam {level}.csv' for level in 'abcde'}
    if len(result['qam_trials'])!=32 or accepted!=expected:
        raise AssertionError(f'Laboratory QAM regression: accepted {sorted(accepted)}')
    for trial in result['qam_trials'].values():
        for candidate in trial['candidates']:
            if not 49.9e6<candidate['parameters']['baud']<50.1e6 or not 4900<=candidate['symbol_count']<=5000:
                raise AssertionError('Physical baud or recovered symbol-count regression')
            pn=candidate['prbs15']
            if (pn['status']!='prbs15_consistent' or pn['acquisition_error_count']!=0
                    or pn['evaluation_bits']<17000 or pn['evaluation_error_count']!=0):
                raise AssertionError('Laboratory PRBS15 bit comparison regression')
            if candidate['prbs15_shuffled_control']['status']=='prbs15_consistent':
                raise AssertionError('Shuffled real symbols falsely accepted as PRBS15')
    refused=[trial for name,trial in result['qam_trials'].items() if Path(name).name=='16qam f.csv']
    if len(refused)!=1 or refused[0]['rejection_reason']!='filter_trials_failed_quality_gates':
        raise AssertionError('Expected the laboratory f capture to retain its quality refusal')
    fits=refused[0]['rejected_fit_diagnostics']
    if [item['fit']['rrc_rolloff_trial'] for item in fits]!=[.2,.35,.5]:
        raise AssertionError('Expected three fixed rejected filter diagnostics')
    for item in fits:
        fit=item['fit'];pn=item['prbs15']
        if (set(fit['rejection_reasons'])!={'evm_rms_above_0.12','half_evm_above_0.14'}
                or not .20<fit['symbol_evm_rms']<.25 or fit['minimum_state_occupancy']<.015):
            raise AssertionError('Unexpected laboratory f quality-gate diagnostic')
        if pn['status']!='prbs15_consistent' or pn['evaluation_bits']<17000 or not .02<pn['evaluation_ber']<.06:
            raise AssertionError('Rejected laboratory f PRBS error measurement regression')
        if item['shuffled_control']['status']=='prbs15_consistent':
            raise AssertionError('Shuffled rejected-fit labels falsely accepted as PRBS15')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
