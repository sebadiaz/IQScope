"""Experimental guarded follow-up on the four exposed LoRaIQ members, not production."""
import argparse
import hashlib
import json
from pathlib import Path
from loraiq_forensic_probe import run as research_run
from loraiq_batch import compare_frames
from loraiq_reference import reference_stem


def run(reference_path):
    reference=json.loads(reference_path.read_text())
    manifest=json.loads(Path('corpus/loraiq-extension-manifest.json').read_text())
    if [e['annotation'] for e in reference['observations']]!=manifest['selected_annotations']:
        raise ValueError('Reference selection differs from the frozen manifest')
    result={'scope':'Experimental guarded follow-up on exposed captures; not the default production decoder.',
        'production_score_from_reference':reference['matched_count'],'selected_count':4,
        'comparison_scope':'One selected annotation per member; additional emissions without that annotation remain unverified here.',
        'reference_report_sha256':hashlib.sha256(reference_path.read_bytes()).hexdigest(),'observations':[]}
    for index,entry in enumerate(reference['observations']):
        report=research_run(Path('corpus-cache/loraiq-extension')/str(index)/'source.sigmf-meta',guarded=True)
        if report['source_data_sha256']!=entry['data_sha256'] or report['source_meta_sha256']!=entry['meta_sha256']:
            raise ValueError('Guarded input differs from integrity-verified benchmark source')
        frames=[dict(o['soft_analysis']['payload'],parameters=o['parameters'],time_seconds=o['data_time_seconds'])
                for o in report['observations'] if o['soft_analysis']['status']=='research_crc_valid']
        comparisons=compare_frames(frames,[entry['annotation']],reference_stem(entry['annotation']),report['sample_rate_hz'])
        matched=any(c['status']=='exact_match' for c in comparisons)
        for observation in report['observations']:
            observation.pop('noise_normalized_spectra',None)
        result['observations'].append({'annotation':entry['annotation'],'payload_matches_selected_reference':matched,
            'reference_comparisons':comparisons,'research_report':report})
        print('GUARDED_MEMBER '+json.dumps({'index':index,'matched_selected_reference':matched}),flush=True)
    result['experimental_guarded_matched_count']=sum(e['payload_matches_selected_reference'] for e in result['observations'])
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference',type=Path,default=Path('corpus-cache/loraiq-extension/observation.json'))
    parser.add_argument('--out',type=Path,default=Path('corpus-cache/loraiq-forensic/guarded-batch.json'))
    args=parser.parse_args();result=run(args.reference)
    args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(result,indent=2)+'\n')
    print('GUARDED_BATCH_RESULT '+json.dumps({k:v for k,v in result.items() if k!='observations'}))


if __name__=='__main__':
    main()
