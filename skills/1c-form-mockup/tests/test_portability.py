"""Behavior after extraction and relocation; no browser or live 1C access."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.parse

import test_form_html as fixtures

engine = fixtures.form_html
SKILL = Path(__file__).resolve().parents[1]


class PortabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='portable-form-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.src = self.root / 'Проект с пробелами' / 'dump'
        self.form = self.src / 'Documents' / 'ТестЗаказ' / 'Forms' / 'ФормаДокумента' / 'Ext' / 'Form.xml'
        self.form.parent.mkdir(parents=True)
        (self.src / 'Documents/ТестЗаказ.xml').write_text(fixtures.METADATA, encoding='utf-8')
        self.form.write_text(fixtures.FORM, encoding='utf-8')

    def run_cli(self, *args, script=None, cwd=None):
        return subprocess.run([sys.executable, '-I', '-X', 'utf8', '-B',
                               str(script or SKILL / 'scripts/form_html.py'), *map(str, args)],
                              cwd=cwd or self.root, capture_output=True, text=True, encoding='utf-8', timeout=30)

    def test_default_find_is_workspace_relative_not_harness_relative(self):
        with patch('os.getcwd', return_value=str(self.root / 'Новый проект')):
            self.assertEqual(Path(engine.default_src()), self.root / 'Новый проект/src')

    def test_profiles_remain_bound_to_dump_after_cwd_changes(self):
        form = engine.Extractor(str(self.form), str(self.src), 'erp-demo').extract()
        with patch('os.getcwd', return_value=str(self.root / 'unrelated')):
            path = Path(engine.own_profile_path(form))
        self.assertEqual(path.parent, self.src.parent / '.1c-form-mockup/profiles')
        self.assertTrue(path.name.startswith('erp-demo.'))

    def test_explicit_profile_directory_and_scopes_are_respected(self):
        profiles = self.root / 'Свои профили'
        profiles.mkdir()
        first = engine.Extractor(str(self.form), str(self.src), 'first', str(profiles)).extract()
        second = engine.Extractor(str(self.form), str(self.src), 'second', str(profiles)).extract()
        path = profiles / engine.profile_name(first)
        path.write_text('{}', encoding='utf-8')
        self.assertEqual(Path(engine.profile_path(first)), path)
        self.assertIsNone(engine.profile_path(second))
        self.assertEqual(engine.configuration_id('ERP_DEMO'), 'erp_demo')

    def test_invalid_scope_cannot_escape_profile_directory(self):
        for value in ('../other', '/tmp', 'x/y', 'x\\y', '', 'x' * 65):
            with self.subTest(value=value), self.assertRaises(ValueError):
                engine.Extractor(str(self.form), str(self.src), value)
        form = engine.Extractor(str(self.form), str(self.src), 'safe').extract()
        form['form'] = '../outside'
        with self.assertRaises(ValueError):
            engine.own_profile_path(form)

    def test_cli_any_configuration_product_and_bom_data_without_touching_xml(self):
        before = hashlib.sha256(self.form.read_bytes()).hexdigest()
        spec, page, data = [self.root / n for n in ('Макет.json', 'Макет.html', 'Данные.json')]
        out = self.run_cli('extract', '--form', self.form, '--src', self.src,
                           '--configuration', 'another-erp', '--product', 'Другая конфигурация',
                           '--profile', 'none', '--out', spec)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        out = self.run_cli('add', '--json', spec, '--kind', 'column', '--title', 'Пример скидки',
                           '--after', 'Цена', '--table', 'Товары')
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        data.write_text(json.dumps({'fields': {'Клиент': '<img src=x onerror=alert(1)>'}}), encoding='utf-8-sig')
        out = self.run_cli('render', '--json', spec, '--data', data, '--out', page)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        result = json.loads(out.stdout)
        self.assertNotIn('warning', result)
        self.assertNotIn('opened', result)
        self.assertNotIn('png', result)
        html = page.read_text(encoding='utf-8')
        self.assertIn('Другая конфигурация', html)
        self.assertIn('Пример скидки', html)
        self.assertNotIn('<img src=x', html)
        self.assertNotIn('Комплексная автоматизация', html)
        self.assertEqual(hashlib.sha256(self.form.read_bytes()).hexdigest(), before)

    def test_relocated_script_works_without_original_repository_or_current_src(self):
        other = self.root / 'Другой harness' / 'skills' / '1c-form-mockup'
        shutil.copytree(SKILL, other, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        out = self.run_cli('build', '--src', self.src, '--configuration', 'isolated',
                           '--form', self.form, '--profile', 'none', '--new-form',
                           '--out', self.root / 'Другой результат.html',
                           script=other / 'scripts/form_html.py', cwd=self.root)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        result = json.loads(out.stdout)
        self.assertEqual(result['highlight'], 'none (new form)')
        self.assertTrue(Path(result['html']).is_file())

    def test_synthetic_example_creates_self_contained_html_without_browser(self):
        out = self.run_cli('render', '--json', SKILL / 'assets/example.form.json',
                           '--data', SKILL / 'assets/example.data.json', '--out', self.root / 'example.html')
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        html = Path(json.loads(out.stdout)['html']).read_text(encoding='utf-8')
        self.assertNotIn('<script src=', html)
        self.assertNotIn('<link ', html)
        self.assertIn('Скидка, %', html)
        self.assertNotIn('warning', json.loads(out.stdout))

    def test_file_uri_encodes_spaces_and_cyrillic_correctly(self):
        path = self.root / 'Имя с пробелами.html'
        link = engine.file_link(str(path))
        self.assertEqual(link, path.resolve().as_uri())
        self.assertNotIn(' ', link)
        self.assertEqual(urllib.parse.urlsplit(link).scheme, 'file')

    def test_manifest_checker_detects_tampering(self):
        fake = self.root / 'package'
        fake.mkdir()
        data = fake / 'payload.txt'
        data.write_text('original', encoding='utf-8')
        (fake / 'MANIFEST.json').write_text(json.dumps({'files': {
            'payload.txt': hashlib.sha256(data.read_bytes()).hexdigest()}}), encoding='utf-8')
        command = [sys.executable, '-I', '-X', 'utf8', '-B', str(SKILL / 'scripts/verify_package.py'), str(fake)]
        good = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', timeout=20)
        self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
        data.write_text('tampered', encoding='utf-8')
        bad = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', timeout=20)
        self.assertEqual(bad.returncode, 1)
        self.assertIn('SHA256 mismatch', bad.stdout)
