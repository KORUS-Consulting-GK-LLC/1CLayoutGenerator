"""Build the portable skill ZIP and its SHA256; Python standard library only."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills/1c-form-mockup'


def payload():
    return sorted(p for p in SKILL.rglob('*') if p.is_file() and '__pycache__' not in p.parts
                  and p.suffix != '.pyc' and p.name != 'MANIFEST.json')


def verify():
    spec = importlib.util.spec_from_file_location('integrity', SKILL / 'scripts/verify_package.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.verify(SKILL)
    if not result['passed']:
        raise ValueError('; '.join(result['errors']))


def build(out, refresh=False):
    version = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
    if refresh:
        manifest = {'name': '1c-form-mockup', 'version': version,
                    'files': {p.relative_to(SKILL).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in payload()}}
        with (SKILL / 'MANIFEST.json').open('w', encoding='utf-8', newline='\n') as stream:
            stream.write(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    verify()
    if json.loads((SKILL / 'MANIFEST.json').read_text('utf-8'))['version'] != version:
        raise ValueError('VERSION and skill manifest disagree')
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    archive = out / ('1c-form-mockup-' + version + '.zip')
    temporary = archive.with_suffix('.zip.tmp')
    with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for path in sorted(payload() + [SKILL / 'MANIFEST.json']):
            entry = zipfile.ZipInfo('1c-form-mockup/' + path.relative_to(SKILL).as_posix(), (2026, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(entry, path.read_bytes())
    temporary.replace(archive)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    with archive.with_suffix('.zip.sha256').open('w', encoding='ascii', newline='\n') as stream:
        stream.write(digest + '  ' + archive.name + '\n')
    return {'archive': str(archive), 'sha256': digest, 'version': version}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', default='dist')
    parser.add_argument('--refresh-manifest', action='store_true', help='Maintainer: refresh after reviewing source changes')
    args = parser.parse_args()
    try:
        print(json.dumps(build(args.out, args.refresh_manifest), ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, 'Build failed: ' + str(error) + '\n')
