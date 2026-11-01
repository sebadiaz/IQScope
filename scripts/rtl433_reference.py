"""Build a pinned optional decoder and verify non-redistributed OOK/FSK public captures."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import urllib.request

import numpy as np
from scipy.signal import resample_poly

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from iqscope import discover
from iqscope_rtl433 import search_rtl433

RTL_COMMIT = 'f35183aaf1d2d905d422fd70bcae4eb7349d6186'
RTL_HASH = '6920df3b291359ed36fd9ba04d9cf67d82a235f609612071d3208f925b85523f'
DATA_COMMIT = '1aa8c29d6b9383739d1aeed495dbc5069b704392'
DATA_HASH = 'b68fa16227ebb86e77f70f17409f9ce59d1542d787d002c9295afcb50ef71393'
DATA_URL = f'https://raw.githubusercontent.com/merbanan/rtl_433_tests/{DATA_COMMIT}/tests/fineoffset/fineoffset_wh2/01/gfile001.cu8'
EXPECTED = {'model':'Fineoffset-WH2','id':209,'temperature_C':24.6,'humidity':33,'mic':'CRC'}

FSK_HASH = 'a4c0dbb2ab0c82e41b2db393fab0ab129f8b94a2c07f24f9479f38f021a57604'
FSK_URL = f'https://raw.githubusercontent.com/merbanan/rtl_433_tests/{DATA_COMMIT}/tests/fineoffset/fineoffset_wh25/01/gfile001.cu8'
FSK_EXPECTED = {'model':'Fineoffset-WH25','id':80,'battery_ok':1,'temperature_C':23.2,
                'humidity':57,'pressure_hPa':1001.1,'mic':'CRC'}


def matching_messages(report, expected):
    if report['status'] != 'completed':
        raise AssertionError(f'Incomplete reference analysis: {report}')
    return [message for message in report['messages']
            if all(message['fields'].get(key)==value for key,value in expected.items())]


def read_cu8(data):
    raw=np.frombuffer(data,dtype='u1').astype(np.float32)
    return ((raw[::2]-127.5)+1j*(raw[1::2]-127.5))/127.5


def download(url, expected, limit):
    with urllib.request.urlopen(url, timeout=45) as response:
        data = response.read(limit+1)
    if len(data)>limit or hashlib.sha256(data).hexdigest()!=expected:
        raise ValueError('Reference download size/hash mismatch')
    return data


def build(root):
    archive = download(f'https://codeload.github.com/merbanan/rtl_433/tar.gz/{RTL_COMMIT}',RTL_HASH,16_000_000)
    source_root = root/'source'
    source_root.mkdir(exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
        for member in stream.getmembers():
            if member.issym() or member.islnk() or not (member.isfile() or member.isdir()) or member.name.startswith('/') or '..' in Path(member.name).parts:
                raise ValueError('Unsafe source archive')
        # Validate paths/types ourselves for Python 3.10 compatibility.
        stream.extractall(source_root)
    source = source_root/f'rtl_433-{RTL_COMMIT}'
    cmake = shutil.which('cmake')
    if not cmake:
        raise RuntimeError('Install CMake and a C compiler to run --build')
    subprocess.run([cmake,'-S',str(source),'-B',str(root/'build'),'-DENABLE_RTLSDR=OFF',
                    '-DENABLE_SOAPYSDR=OFF','-DENABLE_OPENSSL=OFF','-DBUILD_TESTING=OFF'],check=True,timeout=60)
    subprocess.run([cmake,'--build',str(root/'build'),'-j','4'],check=True,timeout=180)
    return root/'build'/'src'/'rtl_433'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build',action='store_true')
    parser.add_argument('--executable',type=Path)
    args=parser.parse_args()
    root=Path('corpus-cache/rtl433-reference').resolve()
    root.mkdir(parents=True,exist_ok=True)
    binary=build(root) if args.build else args.executable
    if binary:
        os.environ['PATH']=str(binary.resolve().parent)+os.pathsep+os.environ.get('PATH','')
    executable=shutil.which('rtl_433')
    if not executable:
        raise RuntimeError('rtl_433 required; use --build or --executable')
    data=download(DATA_URL,DATA_HASH,131072)
    (root/'gfile001.cu8').write_bytes(data)
    x=read_cu8(data)
    fsk_data=download(FSK_URL,FSK_HASH,131072)
    (root/'wh25.cu8').write_bytes(fsk_data)
    fsk=read_cu8(fsk_data)
    up=resample_poly(x,4,1)
    t=np.arange(len(up))/1_000_000
    two=up*np.exp(2j*np.pi*240_000*t)+.8*up*np.exp(-2j*np.pi*280_000*t)
    mixed=up*np.exp(2j*np.pi*240_000*t)+resample_poly(fsk,4,1)*np.exp(-2j*np.pi*280_000*t)
    reports={}
    for name,samples,rate in [('original',x,250_000),('two_frequency_shifted_copies',two,1_000_000),('silence',np.zeros_like(x),250_000),('fsk_original',fsk,250_000),('mixed_ook_fsk',mixed,1_000_000)]:
        bands,*_=discover(samples,rate)
        report=search_rtl433(samples,rate,bands)
        reports[name]=report
        matches=matching_messages(report,EXPECTED)
        if name=='original' and len(matches)!=1:
            raise AssertionError(f'WH2 expected values missing: {report}')
        if name=='two_frequency_shifted_copies':
            offsets=[report['channels_examined'][m['channel_index']]['offset_hz'] for m in matches]
            if not (any(v< -150_000 for v in offsets) and any(v>100_000 for v in offsets)):
                raise AssertionError(f'Two automatically discovered channels not decoded: {report}')
        if name=='fsk_original' and len(matching_messages(report,FSK_EXPECTED))!=1:
            raise AssertionError(f'WH25 expected values missing: {report}')
        if name=='mixed_ook_fsk':
            ook_matches=matching_messages(report,EXPECTED)
            fsk_matches=matching_messages(report,FSK_EXPECTED)
            if not ook_matches or not fsk_matches:
                raise AssertionError(f'Mixed OOK/FSK values missing: {report}')
            if not any(a['channel_index']!=b['channel_index'] for a in ook_matches for b in fsk_matches):
                raise AssertionError('Mixed references not recovered on separate channel trials')
        if name=='silence' and report['messages']:
            raise AssertionError('Unexpected silence detection')
    version=subprocess.run([executable,'-V'],capture_output=True,check=True,timeout=5)
    provenance={'source_url':DATA_URL,'source_sha256':DATA_HASH,'source_bytes':len(data),
                'sample_rate_hz':250000,'sample_rate_basis':'upstream test convention and pulse widths; not independently calibrated',
                'rf_center_hz':None,'sample_license':'not established; raw samples not redistributed',
                'decoder_commit':RTL_COMMIT,'decoder_source_archive_sha256':RTL_HASH,
                'decoder_version':(version.stdout+version.stderr).decode(errors='replace')[:2000],
                'expected_fields':EXPECTED,'expected_fields_source':DATA_URL.replace('.cu8','.json'),
                'derived_case':'two frequency-shifted copies of ONE recording; not two independent captures',
                'fsk_reference':{'source_url':FSK_URL,'source_sha256':FSK_HASH,'source_bytes':len(fsk_data),
                                 'sample_rate_hz':250000,'sample_rate_basis':'upstream test convention, not independently calibrated',
                                 'rf_center_hz':None,'expected_fields':FSK_EXPECTED,
                                 'expected_fields_source':FSK_URL.replace('.cu8','.json'),
                                 'modulation_basis':'pinned rtl_433 fineoffset_WH25 descriptor: FSK_PULSE_PCM',
                                 'sample_license':'not established; raw samples not redistributed'},
                'mixed_case':'two independently recorded sensors shifted and summed numerically; not a simultaneous RF acquisition',
                'integrity':'rtl_433 CRC claim; not an independent IQScope CRC implementation'}
    (root/'provenance.json').write_text(json.dumps(provenance,indent=2))
    (root/'results.json').write_text(json.dumps(reports,indent=2))
    print('WH2 OOK and WH25 FSK values verified; mixed automatic channels recovered; silence negative passed.')


if __name__=='__main__':
    main()
