#!/usr/bin/env python3
"""Compare a release ZIP and checksum against this exact repository tree."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT=Path(__file__).resolve().parent

def verify(archive,checksum):
    digest=hashlib.sha256(archive.read_bytes()).hexdigest()
    rows=[s.split() for s in checksum.read_text().splitlines() if s.strip()]
    assert rows==[[digest,archive.name]], 'ZIP checksum or filename differs'
    manifest=json.loads((ROOT/'MANIFEST.json').read_text())
    expected={r['path'] for r in manifest['files']}|{'MANIFEST.json'}
    with zipfile.ZipFile(archive) as z:
        names=z.namelist()
        assert len(names)==len(set(names)), 'Duplicate ZIP path'
        assert set(names)==expected, 'ZIP and repository file sets differ'
        for name in names:
            assert z.read(name)==(ROOT/name).read_bytes(), 'ZIP differs: '+name
    return {'package_matches_repository':True,'files':len(expected),'zip_sha256':digest}

if __name__=='__main__':
    assert len(sys.argv)==3, 'Provide the release ZIP and SHA256SUMS.txt'
    print(json.dumps(verify(Path(sys.argv[1]),Path(sys.argv[2]))))
