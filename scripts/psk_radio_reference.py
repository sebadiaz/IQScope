"""Bounded recorded receiver-audio regression; no original RF IQ claim."""
import hashlib
import json
from pathlib import Path
import sys
import urllib.request

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from iqscope_audio import analyze_audio
from iqscope_ax25 import crc_x25

PIN='952ddfe53f62a150c53559249c83370630254cab'
RECORDINGS={
    'picsat':(288996,'41d9eb1fb24b2c1c637f161a44c738576853cbf5396d959c38eff218ddf0fabd'),
    'pwsat2':(1284374,'017910fff961278abb9b0ea97c9302e5740940bb5226008e3de8c2353fb8180a'),
    'ao73':(535530,'d8758c1a860309185dc2b863a431b2266e050fb0e7c8e8d6d1f67a5b206ace9c')}
# Payload hashes are development regression oracles from the first CRC-valid
# decode, not independently supplied ground truth from the recording author.
PAYLOAD_HASHES={
    '4171091c943892f60041564c49e595dc1888a0c19fcc19914b904cf31d92b86c',
    '597d97bdef95e92a99b2f9bc3c2237d4f1dc3124837785b2a7a1061081e8b561',
    '6565ab6859ecad80f3415ff1cd000238e44c64df9e63aaf13274ae22b3156137'}


def main():
    root=Path('corpus-cache/psk-radio');root.mkdir(parents=True,exist_ok=True)
    summaries={}
    for name,(size,digest) in RECORDINGS.items():
        url=f'https://raw.githubusercontent.com/daniestevez/satellite-recordings/{PIN}/{name}.wav'
        with urllib.request.urlopen(url,timeout=45) as response:
            data=response.read(size+1)
        if len(data)!=size or hashlib.sha256(data).hexdigest()!=digest:
            raise ValueError('Recorded audio size/hash mismatch')
        path=root/(name+'.wav');path.write_bytes(data)
        out=root/(name+'-result')
        report=analyze_audio(path,out,20)
        psk=next(t for t in report['wideband_trials'] if t['decoder']=='psk_generic')
        frames=next(t for t in report['wideband_trials'] if t.get('frontend')=='bpsk_g3ruh')['frames']
        hashes=set()
        payload_hashes=[]
        for frame in frames:
            raw=bytes.fromhex(frame['hex'])
            if crc_x25(raw[:-2])!=int.from_bytes(raw[-2:],'little'):
                raise AssertionError('Invalid FCS in accepted recorded frame')
            payload=bytes.fromhex(frame['fields']['payload_hex'])
            if (out/frame['payload_artifact']).read_bytes()!=payload:
                raise AssertionError('Payload export changed bytes')
            digest_payload=hashlib.sha256(payload).hexdigest()
            hashes.add(digest_payload)
            payload_hashes.append(digest_payload)
        ao40=next(t for t in report['wideband_trials'] if t['decoder']=='ao40_fec')
        fec_hashes=[]
        for decoded in ao40['frames']:
            payload=bytes.fromhex(decoded['payload_hex'])
            if (out/decoded['payload_artifact']).read_bytes()!=payload:
                raise AssertionError('AO-40 payload export mismatch')
            fec_hashes.append(hashlib.sha256(payload).hexdigest())
        if name=='ao73':
            if fec_hashes!=['220bb05857d4220084ca46bcb7e48759226935627a25767144d588dc4a43b112']:
                raise AssertionError('AO-73 AO-40 FEC payload regression')
            if ao40['frames'][0]['crc_valid'] is not None:
                raise AssertionError('AO-40 FEC claimed a CRC')
        if name=='picsat':
            if not any(c['modulation']=='BPSK' and 1190<c['parameters']['baud']<1210 for c in psk['candidates']):
                raise AssertionError('PicSat recorded BPSK structural regression')
            if len(frames)!=1 or hashes!={'2c95b8abea7c459f8ca46c6315375036017b3d93d5f4f47f3e76a1eae61674f7'}:
                raise AssertionError('PicSat CRC-valid payload regression')
        if name=='pwsat2':
            expected=sorted([*PAYLOAD_HASHES,'597d97bdef95e92a99b2f9bc3c2237d4f1dc3124837785b2a7a1061081e8b561'])
            if len(frames)!=4 or sorted(payload_hashes)!=expected:
                raise AssertionError('PW-Sat2 recorded payload regression')
            if any(f['fields']['source']['callsign']!='PWSAT2' for f in frames):
                raise AssertionError('Unexpected AX.25 source address')
        if report['center_frequency_hz'] is not None or report['source_kind']!='receiver_audio':
            raise AssertionError('Receiver audio promoted to RF IQ')
        provenance={'source_url':url,'source_sha256':digest,'source_bytes':size,
                    'collection_readme':f'https://github.com/daniestevez/satellite-recordings/blob/{PIN}/README.md',
                    'collection_license':f'https://github.com/daniestevez/satellite-recordings/blob/{PIN}/LICENSE',
                    'recording_origin':'upstream amateur-satellite receiver-audio collection; receiver details not independently established',
                    'input_kind':'mono receiver audio, not original RF IQ','rf_center_hz':None,
                    'sample_rate_basis':'WAV header, then explicit ffmpeg mono resampling to 8 kHz',
                    'payload_oracle':'development regression from FCS- or FEC-verified decoding; not independent upstream golden bytes',
                    'validated_scope':'AX.25 UI/FCS or AO-40 FEC parity, explicitly separated; no authenticated emitter or telemetry semantics',
                    'ao40_fec_payload_sha256':fec_hashes,'ao40_fec_payload_count':len(ao40['frames']),
                    'psk_candidates':len(psk['candidates']),'crc_valid_frames':len(frames),
                    'payload_sha256':sorted(hashes),'windows_examined':psk['windows_examined']}
        (out/'provenance.json').write_text(json.dumps(provenance,indent=2))
        summaries[name]={'ao40_fec_payload_sha256':fec_hashes,'ao40_fec_payload_count':len(ao40['frames']),
                    'psk_candidates':len(psk['candidates']),'crc_valid_frames':len(frames),'payload_sha256':sorted(hashes)}
    (root/'summary.json').write_text(json.dumps(summaries,indent=2))
    print(json.dumps(summaries))


if __name__=='__main__':
    main()
