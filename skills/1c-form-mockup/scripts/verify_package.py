"""Verify an extracted portable skill without extra dependencies or executing it."""
import argparse
import hashlib
import json
import re
from pathlib import Path


def verify(root):
    root = Path(root).resolve()
    manifest = json.loads((root / 'MANIFEST.json').read_text(encoding='utf-8'))
    if not isinstance(manifest, dict) or not isinstance(manifest.get('files'), dict) or not manifest['files']:
        raise ValueError('Manifest must contain a nonempty files object')
    errors = []
    expected = set(manifest['files'])
    for name, digest in manifest['files'].items():
        if (not isinstance(name, str) or '\\' in name or name.startswith('/')
                or any(part in ('', '.', '..') for part in name.split('/'))
                or not isinstance(digest, str) or not re.fullmatch(r'[a-fA-F0-9]{64}', digest)):
            raise ValueError('Invalid manifest path or SHA256')
        path = (root / name).resolve()
        if root not in path.parents or not path.is_file():
            errors.append('missing or outside package: ' + name)
        elif hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            errors.append('SHA256 mismatch: ' + name)
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()
              and '__pycache__' not in p.parts and p.suffix != '.pyc'
              and p.relative_to(root).as_posix() != 'MANIFEST.json'}
    errors.extend('unexpected file: ' + name for name in sorted(actual - expected))
    return {'passed': not errors, 'files_checked': len(expected), 'errors': errors}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', nargs='?', default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args()
    try:
        result = verify(args.root)
    except (OSError, ValueError, KeyError) as error:
        result = {'passed': False, 'errors': [str(error)]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result['passed'] else 1)
