"""Inspect bounded VKSDR IQ WAV prefixes; export complete local SigMF excerpts."""
import argparse
import json
from pathlib import Path
from iqscope_recordings import read_prefix, inspect_prefix, probe


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name',action='append',default=[])
    parser.add_argument('--out',default='corpus-cache/vksdr')
    parser.add_argument('--manifest',default=str(Path(__file__).resolve().parents[1]/'corpus/vksdr.json'))
    args = parser.parse_args()
    entries = json.loads(Path(args.manifest).read_text())['entries']
    known = {e['id']:e for e in entries}
    selected = args.name or list(known)
    if set(selected)-known.keys():
        parser.error('Unknown VKSDR recording')
    for name in selected:
        probe(known[name],args.out)


if __name__=='__main__':
    main()
