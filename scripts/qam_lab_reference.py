"""Bounded inspection of a pinned conducted RF laboratory capture archive."""
import hashlib
import io
import json
from pathlib import Path
import urllib.request
import zipfile

PIN='3f9ea40d9b187d0819b14cb254dc04905d398889'
URL=f'https://raw.githubusercontent.com/billjgavin/28_and_75GHz_Capture_Files/{PIN}/IQ_28_Ghz.zip'
BLOB='fa11ded813f4407afb6c9cad3ac37dc4c135dced'
SIZE=8425587


def main():
    root=Path('corpus-cache/qam-lab');root.mkdir(parents=True,exist_ok=True)
    with urllib.request.urlopen(URL,timeout=45) as response:data=response.read(SIZE+1)
    if len(data)!=SIZE or hashlib.sha1(b'blob '+str(SIZE).encode()+b'\0'+data).hexdigest()!=BLOB:
        raise ValueError('Pinned archive size or Git blob hash mismatch')
    (root/'IQ_28_Ghz.zip').write_bytes(data)
    result={'source_url':URL,'source_git_blob':BLOB,'source_sha256':hashlib.sha256(data).hexdigest(),
            'source_bytes':len(data),'origin':'conducted laboratory RF acquisition per upstream README; not radiated',
            'sample_rate_hz_declared':200e6,'symbol_rate_baud_declared':50e6,
            'license':'not established; no raw IQ redistributed','members':[],'previews':[]}
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
    (root/'inspection.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
