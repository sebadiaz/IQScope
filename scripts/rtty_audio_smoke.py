"""Check receiver-audio import on an explicitly transformed real SDRangel IQ excerpt."""
import argparse
import json
from pathlib import Path
import numpy as np
from scipy.io import wavfile
from iqscope import read_iq
from iqscope_audio import analyze_audio
from sdrangel_corpus import run


def main():
    manifest = Path(__file__).resolve().parents[1]/'corpus/sdrangel.json'
    entry = next(e for e in json.loads(manifest.read_text())['entries'] if e['id']=='rtty')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reuse-source-root',type=Path)
    args = parser.parse_args()
    root = Path('corpus-cache/rtty-audio')
    root.mkdir(parents=True,exist_ok=True)
    source_root = args.reuse_source_root or root
    if args.reuse_source_root:
        source = json.loads((source_root/'rtty/provenance.json').read_text())
        if source['excerpt_sha256']!=entry['expected_excerpt_sha256_16m']:
            raise ValueError('Cached RTTY source provenance does not match the pinned reference')
    else:
        source = run(entry,root)
    report = json.loads((source_root/'rtty/results/report.json').read_text())
    direct = next(t for t in report['wideband_trials'] if t['decoder']=='rtty_ita2')['candidates'][0]
    x,fs,_ = read_iq(source_root/'rtty/excerpt.sigmf-data')
    p = direct['parameters']
    offset = fs/4-(p['low_tone_hz']+p['high_tone_hz'])/2
    audio = np.real(x*np.exp(2j*np.pi*offset*np.arange(len(x))/fs)).astype(np.float32)
    path = root/'receiver-audio-derived.wav'
    wavfile.write(path,int(fs),audio)
    result = analyze_audio(path,root/'audio-results',seconds=20)
    trial = next(t for t in result['wideband_trials'] if t['decoder']=='rtty_ita2')
    matches = [c for c in trial['candidates'] if c['text']==direct['text']]
    evidence = {'source_url':source['archive_url'],'source_excerpt_sha256':source['excerpt_sha256'],
                'source_kind':'real_iq_transformed_to_receiver_audio','frequency_translation_hz':offset,
                'same_candidate_text_recovered':bool(matches),
                'source_audio_rate_hz':fs,'analysis_audio_rate_hz':result['sample_rate'],
                'rf_center_is_null':result['center_frequency_hz'] is None,
                'text_candidate':matches[0]['text'] if matches else None,
                'scope':'Real IQ translated into audio then imported; not an independent receiver-audio capture or known payload transcript.'}
    (root/'provenance.json').write_text(json.dumps(evidence,indent=2))
    print(json.dumps(evidence),flush=True)
    if not matches:
        raise ValueError('The transformed real RTTY audio did not preserve the direct IQ text candidate')


if __name__=='__main__':
    main()
