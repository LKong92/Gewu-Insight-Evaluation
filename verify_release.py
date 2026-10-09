#!/usr/bin/env python3
"""Verify released bytes, English-only text and basic publication boundaries."""
import hashlib
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parent
def main():
    manifest=json.loads((ROOT/'MANIFEST.json').read_text());expected={r['path']:r for r in manifest['files']}
    actual={str(p.relative_to(ROOT)):p for p in ROOT.rglob('*') if p.is_file() and '.git' not in p.parts and '__pycache__' not in p.parts and p.name not in ['MANIFEST.json','.DS_Store'] and p.suffix!='.pyc'}
    assert set(actual)==set(expected),'Missing or unmanifested release files'
    cjk=re.compile('[\u3400-\u9fff]')
    for name,path in actual.items():
        data=path.read_bytes();row=expected[name]
        assert hashlib.sha256(data).hexdigest()==row['sha256'] and len(data)==row['bytes'],name
        assert not cjk.search(name),name
        text=data.decode('utf-8')
        if path.suffix=='.json':
            text=json.dumps(json.loads(text),ensure_ascii=False)
        assert not cjk.search(text),'Non-English character found in '+name
        assert not re.search(r'/(?:Users|home)/[A-Za-z0-9_.-]+/|/private/var/folders/[a-z0-9]+/',text),'Personal path in '+name
        assert not re.search(r'(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{25,}|sk-[A-Za-z0-9]{24,})',text),'Potential credential in '+name
    print(json.dumps({'verified':True,'files':len(actual),'english_only_scan':True,'checksums':True,'scope':'Byte integrity and publication checks; not independent scientific validation.'}))
if __name__=='__main__':main()
