"""Regression cases from the standalone repository review; no browser is run."""
import base64
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import test_form_html as fixtures

engine = fixtures.form_html
SKILL = Path(__file__).resolve().parents[1]
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j/pkAAAAASUVORK5CYII=')


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.src = self.root / 'src'
        self.xml = self.src / 'Documents/X/Forms/F/Ext/Form.xml'
        self.xml.parent.mkdir(parents=True)
        self.xml.write_text(fixtures.FORM, encoding='utf-8')

    def cli(self, *args, verify=False):
        name = 'verify_package.py' if verify else 'form_html.py'
        return subprocess.run([sys.executable, '-I', '-X', 'utf8', '-B', str(SKILL / 'scripts' / name),
                               *map(str, args)], capture_output=True, text=True, encoding='utf-8', timeout=20)

    def test_bad_form_json_returns_json_error_without_traceback(self):
        path = self.root / 'bad.json'
        path.write_text('[]', encoding='utf-8')
        run = self.cli('render', '--json', path, '--out', self.root / 'out.html')
        self.assertEqual(run.returncode, 2)
        self.assertIn('error', json.loads(run.stdout))
        self.assertNotIn('Traceback', run.stderr)

    def test_arbitrary_xml_is_not_accepted_as_managed_form(self):
        self.xml.write_text('<Something/>', encoding='utf-8')
        run = self.cli('build', '--form', self.xml, '--profile', 'none', '--out', self.root / 'out.html')
        self.assertEqual(run.returncode, 2)
        self.assertFalse((self.root / 'out.html').exists())

    def test_build_cannot_overwrite_source_xml(self):
        original = self.xml.read_bytes()
        run = self.cli('build', '--form', self.xml, '--profile', 'none', '--out', self.xml)
        self.assertEqual(run.returncode, 2)
        self.assertEqual(self.xml.read_bytes(), original)

    def test_build_cannot_write_inside_dump(self):
        out = self.src / 'output.html'
        run = self.cli('build', '--form', self.xml, '--src', self.src, '--profile', 'none', '--out', out)
        self.assertEqual(run.returncode, 2)
        self.assertFalse(out.exists())

    def test_render_cannot_overwrite_input_json(self):
        path = self.root / 'form.json'
        path.write_bytes((SKILL / 'assets/example.form.json').read_bytes())
        original = path.read_bytes()
        run = self.cli('render', '--json', path, '--out', path)
        self.assertEqual(run.returncode, 2)
        self.assertEqual(path.read_bytes(), original)

    def test_metadata_reference_cannot_escape_selected_dump(self):
        outside = self.root / 'outside.xml'
        outside.write_text(fixtures.METADATA, encoding='utf-8')
        with self.assertRaises(ValueError):
            engine.Metadata(str(self.src)).load('..', 'outside')

    def test_explicit_profile_is_not_ignored_for_extracted_json(self):
        path = self.root / 'form.json'
        form = engine.Extractor(str(self.xml), str(self.src)).extract()
        form['profile_report'] = None
        path.write_text(json.dumps(form), encoding='utf-8')
        profile = self.root / 'profile.json'
        profile.write_text(json.dumps({'buttons': ['Наблюдаемая кнопка']}), encoding='utf-8')
        run = self.cli('render', '--json', path, '--profile', profile, '--out', self.root / 'out.html')
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn('profile_report', json.loads(run.stdout))
        self.assertIn('Наблюдаемая кнопка', (self.root / 'out.html').read_text('utf-8'))

    def png_call(self, code=0, payload=PNG):
        def call(args, **kwargs):
            target = next((x.split('=', 1)[1] for x in args if x.startswith('--screenshot=')), None)
            if target:
                Path(target).write_bytes(payload)
            return SimpleNamespace(returncode=code, stdout='', stderr='failed' if code else '')
        return call

    def test_failed_browser_keeps_existing_png(self):
        path = self.root / 'old.png'
        path.write_bytes(PNG)
        with patch.object(engine, 'find_chrome', return_value='fake-browser'), \
                patch.object(engine.subprocess, 'run', side_effect=self.png_call(code=1)):
            error = engine.screenshot('<html/>', str(path), size='900,600')
        self.assertIsNotNone(error)
        self.assertEqual(path.read_bytes(), PNG)

    def test_invalid_png_is_not_reported_as_success(self):
        path = self.root / 'old.png'
        path.write_bytes(PNG)
        with patch.object(engine, 'find_chrome', return_value='fake-browser'), \
                patch.object(engine.subprocess, 'run', side_effect=self.png_call(payload=b'not an image')):
            error = engine.screenshot('<html/>', str(path), size='900,600')
        self.assertIsNotNone(error)
        self.assertEqual(path.read_bytes(), PNG)

    def test_successful_png_replaces_destination_after_validation(self):
        path = self.root / 'new.png'
        with patch.object(engine, 'find_chrome', return_value='fake-browser'), \
                patch.object(engine.subprocess, 'run', side_effect=self.png_call()):
            self.assertIsNone(engine.screenshot('<html/>', str(path), size='900,600'))
        self.assertEqual(path.read_bytes(), PNG)

    def test_oversized_auto_png_is_not_silently_cropped(self):
        with patch.object(engine, 'find_chrome', return_value='fake-browser'), \
                patch.object(engine.subprocess, 'run', return_value=SimpleNamespace(
                    returncode=0, stdout='<body data-height="12000">', stderr='')) as run:
            error = engine.screenshot('<html/>', str(self.root / 'out.png'))
        self.assertIsNotNone(error)
        self.assertEqual(run.call_count, 1)

    def test_empty_manifest_fails(self):
        (self.root / 'MANIFEST.json').write_text('{"files": {}}', encoding='utf-8')
        run = self.cli(self.root, verify=True)
        self.assertEqual(run.returncode, 1)
        self.assertFalse(json.loads(run.stdout)['passed'])

    def test_malformed_manifest_fails_without_traceback(self):
        (self.root / 'MANIFEST.json').write_text('{"files": ["a"]}', encoding='utf-8')
        run = self.cli(self.root, verify=True)
        self.assertEqual(run.returncode, 1)
        self.assertFalse(json.loads(run.stdout)['passed'])
        self.assertNotIn('Traceback', run.stderr)
