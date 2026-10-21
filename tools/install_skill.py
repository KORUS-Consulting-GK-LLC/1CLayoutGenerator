"""Install into an explicitly selected skills directory without overwriting changes."""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'skills/1c-form-mockup'


def install(skills_dir):
    spec = importlib.util.spec_from_file_location('integrity', SOURCE / 'scripts/verify_package.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    check = module.verify(SOURCE)
    if not check['passed']:
        raise ValueError('Source integrity failed: ' + '; '.join(check['errors']))
    parent = Path(skills_dir).expanduser().resolve()
    target = parent / '1c-form-mockup'
    if target.exists():
        existing = module.verify(target)
        if not existing['passed'] or (target / 'MANIFEST.json').read_bytes() != (SOURCE / 'MANIFEST.json').read_bytes():
            raise ValueError('Different or modified installation exists; preserve it and install a candidate elsewhere')
        return {'installed': str(target), 'status': 'already-installed'}
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.mockup-install-', dir=parent) as temp:
        candidate = Path(temp) / '1c-form-mockup'
        shutil.copytree(SOURCE, candidate, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        if not module.verify(candidate)['passed']:
            raise ValueError('Installation copy integrity failed')
        candidate.rename(target)
    return {'installed': str(target), 'status': 'installed', 'automatic_discovery': 'depends on harness'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skills-dir', required=True, help='Parent skills directory of the selected harness')
    args = parser.parse_args()
    try:
        print(json.dumps(install(args.skills_dir), ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, 'Install failed: ' + str(error) + '\n')
