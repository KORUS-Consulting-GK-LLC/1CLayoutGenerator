"""Repository entry point, installation and distributed archive contracts."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills/1c-form-mockup'


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='repository-check-')
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)

    def run_script(self, script, *args):
        return subprocess.run([sys.executable, '-I', '-X', 'utf8', '-B', str(ROOT / script), *map(str, args)],
                              cwd=self.work, capture_output=True, text=True, encoding='utf-8', timeout=30)

    def test_demo_from_unrelated_working_directory(self):
        run = self.run_script('layout.py', 'demo')
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        result = json.loads(run.stdout)
        self.assertNotIn('warning', result)
        self.assertTrue((self.work / 'mockups/example.html').is_file())
        self.assertNotIn('opened', result)

    def test_install_is_verified_and_idempotent(self):
        folder = self.work / 'Мой harness/skills'
        first = self.run_script('tools/install_skill.py', '--skills-dir', folder)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual(json.loads(first.stdout)['status'], 'installed')
        second = self.run_script('tools/install_skill.py', '--skills-dir', folder)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(json.loads(second.stdout)['status'], 'already-installed')

    def test_install_preserves_modified_existing_skill(self):
        folder = self.work / 'skills'
        self.assertEqual(self.run_script('tools/install_skill.py', '--skills-dir', folder).returncode, 0)
        changed = folder / '1c-form-mockup/SKILL.md'
        changed.write_text('my local version', encoding='utf-8')
        run = self.run_script('tools/install_skill.py', '--skills-dir', folder)
        self.assertNotEqual(run.returncode, 0)
        self.assertEqual(changed.read_text('utf-8'), 'my local version')

    def test_build_archive_and_sha(self):
        run = self.run_script('tools/build_package.py', '--out', self.work / 'out')
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        result = json.loads(run.stdout)
        archive = Path(result['archive'])
        self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), result['sha256'])
        self.check_archive(archive)

    def test_downloaded_archive_matches_current_source(self):
        version = (ROOT / 'VERSION').read_text('utf-8').strip()
        self.check_archive(ROOT / 'downloads' / ('1c-form-mockup-' + version + '.zip'))

    def check_archive(self, path):
        manifest = json.loads((SKILL / 'MANIFEST.json').read_text('utf-8'))
        with zipfile.ZipFile(path) as bundle:
            self.assertEqual(json.loads(bundle.read('1c-form-mockup/MANIFEST.json')), manifest)
            for name, digest in manifest['files'].items():
                self.assertEqual(hashlib.sha256(bundle.read('1c-form-mockup/' + name)).hexdigest(), digest)
                self.assertEqual(hashlib.sha256((SKILL / name).read_bytes()).hexdigest(), digest)
            self.assertFalse(any('__pycache__' in name or '.env' in name for name in bundle.namelist()))
