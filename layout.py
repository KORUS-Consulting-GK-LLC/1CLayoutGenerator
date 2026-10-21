"""1C Layout Generator: a short entry point for the standalone form engine."""
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parent
SKILL = ROOT / 'skills/1c-form-mockup'


def main():
    args = sys.argv[1:]
    if args and args[0] == 'demo':
        args = ['render', '--json', str(SKILL / 'assets/example.form.json'),
                '--data', str(SKILL / 'assets/example.data.json'), *args[1:]]
        if '--out' not in args:
            args += ['--out', 'mockups/example.html']
    engine = runpy.run_path(str(SKILL / 'scripts/form_html.py'))
    return engine['main'](args)


if __name__ == '__main__':
    raise SystemExit(main())
