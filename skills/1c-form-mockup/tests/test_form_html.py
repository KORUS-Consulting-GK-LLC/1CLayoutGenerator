# -*- coding: utf-8 -*-
"""Form XML -> JSON -> HTML on a small synthetic configuration dump."""
import json
from html.parser import HTMLParser
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).parents[1] / 'scripts' / 'form_html.py'
sys.path.insert(0, str(SCRIPT.parent))
import form_html  # noqa: E402

LF = 'http://v8.1c.ru/8.3/xcf/logform'
V8 = 'http://v8.1c.ru/8.1/data/core'


class Markup(HTMLParser):
    """Inspect generated elements, never strings inside script/style or a live browser."""
    def __init__(self):
        super().__init__()
        self.elements, self.visible_marks, self.stack = [], set(), []

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        classes = attributes.get('class', '').split()
        hidden = (self.stack[-1][1] if self.stack else False) or ('page' in classes and 'active' not in classes)
        self.elements.append(attributes)
        if not hidden and 'data-mark' in attributes:
            self.visible_marks.add(int(attributes['data-mark']))
        if tag not in {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta',
                       'param', 'source', 'track', 'wbr'}:
            self.stack.append((tag, hidden))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break


def snapshot_markup(form):
    views = form_html.Renderer(form).change_tabs() or [[]]
    snapshots = []
    for view in views:
        renderer = form_html.Renderer(form)
        renderer.open_tab.update((id(pages), index) for pages, index, _ in view)
        markup = Markup()
        markup.feed(renderer.page(snapshot=True))
        snapshots.append(markup)
    return views, snapshots


def title(t):
    return '<Title><v8:item><v8:lang>ru</v8:lang><v8:content>%s</v8:content></v8:item></Title>' % t


METADATA = '''<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:v8="%s"><Document uuid="1">
<Properties><Name>ТестЗаказ</Name><Synonym><v8:item><v8:lang>ru</v8:lang><v8:content>Тестовый заказ</v8:content></v8:item></Synonym></Properties>
<ChildObjects>
 <Attribute uuid="2"><Properties><Name>Партнер</Name><Synonym><v8:item><v8:lang>ru</v8:lang><v8:content>Клиент</v8:content></v8:item></Synonym>
  <Type><v8:Type>cfg:CatalogRef.Партнеры</v8:Type></Type></Properties></Attribute>
 <TabularSection uuid="3"><Properties><Name>Товары</Name><Synonym><v8:item><v8:lang>ru</v8:lang><v8:content>Товары</v8:content></v8:item></Synonym></Properties>
  <ChildObjects><Attribute uuid="4"><Properties><Name>Цена</Name><Synonym><v8:item><v8:lang>ru</v8:lang><v8:content>Цена</v8:content></v8:item></Synonym>
   <Type><v8:Type>xs:decimal</v8:Type></Type></Properties></Attribute></ChildObjects></TabularSection>
</ChildObjects></Document></MetaDataObject>''' % V8

FORM = '''<?xml version="1.0" encoding="UTF-8"?>
<Form xmlns="%(lf)s" xmlns:v8="%(v8)s" version="2.20">
 <AutoCommandBar name="ФормаКоманднаяПанель" id="-1"><Autofill>false</Autofill><ChildItems>
  <Button name="ФормаПровести" id="1"><Type>CommandBarButton</Type><DefaultButton>true</DefaultButton><CommandName>Form.Command.Провести</CommandName></Button>
  <Popup name="ПодменюПечать" id="2">%(print)s<ChildItems><Button name="Счет" id="3"><CommandName>Form.Command.ПечатьСчета</CommandName></Button></ChildItems></Popup>
 </ChildItems></AutoCommandBar>
 <ChildItems>
  <UsualGroup name="Шапка" id="10"><Group>Horizontal</Group><ShowTitle>false</ShowTitle><ChildItems>
   <InputField name="Партнер" id="11"><DataPath>Объект.Партнер</DataPath></InputField>
   <InputField name="Скрытое" id="12"><DataPath>Объект.Партнер</DataPath><Visible>false</Visible></InputField>
   <LabelDecoration name="Надпись" id="13">%(label)s<Hyperlink>true</Hyperlink></LabelDecoration>
  </ChildItems></UsualGroup>
  <Pages name="Страницы" id="20"><ChildItems>
   <Page name="Основное" id="21">%(main)s<ChildItems><CheckBoxField name="Флаг" id="22">%(flag)s</CheckBoxField></ChildItems></Page>
   <Page name="СтраницаТовары" id="23">%(goods)s<ChildItems>
    <Table name="Товары" id="24"><DataPath>Объект.Товары</DataPath>
     <AutoCommandBar name="ТоварыКоманднаяПанель" id="25"/>
     <ChildItems><InputField name="ТоварыЦена" id="26"><DataPath>Объект.Товары.Цена</DataPath></InputField>
      <InputField name="ТоварыНомерСтроки" id="27"><DataPath>Объект.Товары.LineNumber</DataPath></InputField></ChildItems>
    </Table></ChildItems></Page>
  </ChildItems></Pages>
 </ChildItems>
 <Commands>
  <Command name="Провести" id="1">%(post)s</Command>
  <Command name="ПечатьСчета" id="2">%(invoice)s</Command>
 </Commands>
</Form>''' % {'lf': LF, 'v8': V8, 'print': title('Печать'), 'label': title('Есть &lt;b&gt;сообщения&lt;/&gt;'),
              'main': title('Основное'), 'flag': title('Не отгружать частями'), 'goods': title('Товары'),
              'post': title('Провести и закрыть'), 'invoice': title('Счет на оплату')}


class FormHtmlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        src = Path(self.tmp.name) / 'src'
        (src / 'Documents').mkdir(parents=True)
        (src / 'Documents' / 'ТестЗаказ.xml').write_text(METADATA, encoding='utf-8')
        form_dir = src / 'Documents' / 'ТестЗаказ' / 'Forms' / 'ФормаДокумента' / 'Ext'
        form_dir.mkdir(parents=True)
        self.form_path = form_dir / 'Form.xml'
        self.form_path.write_text(FORM, encoding='utf-8')
        self.src = src

    def tearDown(self):
        self.tmp.cleanup()

    def extract(self):
        return form_html.Extractor(str(self.form_path), str(self.src)).extract()

    def test_titles_come_from_form_metadata_and_commands(self):
        form = self.extract()
        self.assertEqual(form['title'], 'Тестовый заказ')
        self.assertEqual([b['title'] for b in form['command_bar']], ['Провести и закрыть', 'Печать'])
        self.assertTrue(form['command_bar'][0]['default'])
        head = form['items'][0]
        self.assertEqual(head['group'], 'Horizontal')
        self.assertEqual(head['items'][0]['title'], 'Клиент')            # attribute synonym, not the name
        self.assertFalse(head['items'][1]['visible'])
        self.assertEqual(head['items'][2]['title'], 'Есть сообщения')     # formatting stripped
        table = form['items'][1]['items'][1]['items'][0]
        self.assertEqual([c['title'] for c in table['columns']], ['Цена', 'N'])
        self.assertEqual(table['commands'][0]['title'], 'Добавить')     # autofilled table bar

    def test_render_has_tabs_hidden_and_new_items(self):
        form = self.extract()
        table = form['items'][1]['items'][1]['items'][0]
        table['columns'].insert(1, {'type': 'InputField', 'name': 'Спеццена', 'title': 'Спец цена клиента', 'new': True})
        data = {'fields': {'Клиент': 'ООО Ромашка'},
                'tables': {'Товары': [{'Цена': '250,00', 'Спец цена клиента': '240,00', 'N': 1}]}}
        page = form_html.Renderer(form, data).page()
        self.assertIn('data-tab="p1_0"', page)
        self.assertIn('>Товары</div>', page)
        self.assertIn('value="ООО Ромашка"', page)
        self.assertIn('Спец цена клиента', page)
        self.assertIn('is-new', page)
        self.assertIn('240,00', page)
        self.assertNotIn('name="Скрытое"', page)
        self.assertIn('id="showNew"', page)
        self.assertEqual(page.count('class="hidden-el'), 0)
        shown = form_html.Renderer(form, data, show_hidden=True).page()
        self.assertIn('hidden-el', shown)

    def test_cli_find_extract_render(self):
        run = lambda *a: subprocess.run([sys.executable, '-X', 'utf8', str(SCRIPT), *a], capture_output=True,
                                        text=True, encoding='utf-8')
        out = run('find', '--object', 'Документ.ТестЗаказ', '--src', str(self.src))
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertEqual(len(json.loads(out.stdout)['forms']), 1)
        js = os.path.join(self.tmp.name, 'form.json')
        page = os.path.join(self.tmp.name, 'Макет.html')
        # no profile: the script stops and gives the agent the request for a screenshot
        out = run('extract', '--form', str(self.form_path), '--src', str(self.src), '--out', js)
        self.assertEqual(out.returncode, 3, out.stdout + out.stderr)
        stop = json.loads(out.stdout)
        self.assertTrue(stop['need_screenshot'])
        self.assertIn('«Тестовый заказ»', stop['ask'])
        self.assertFalse(os.path.exists(js))
        # «без скрина»
        self.assertEqual(run('extract', '--form', str(self.form_path), '--src', str(self.src), '--out', js,
                             '--profile', 'none').returncode, 0)
        out = run('render', '--json', js, '--out', page, '--no-shell')
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertTrue(json.loads(out.stdout)['link'].startswith('file:///'))
        text = Path(page).read_text(encoding='utf-8')
        self.assertTrue(text.startswith('<!DOCTYPE html>'))
        self.assertNotIn('class="apphead"', text)
        self.assertNotIn('src=', text)           # self-contained: no external scripts or images

    def test_profile_hides_adds_and_reorders(self):
        form = self.extract()
        profile = {'nav': ['Main', 'Файлы'], 'tabs': ['Товары (1)', 'Бенефициары'],
                   'buttons': ['*Провести и закрыть', 'Отправить', 'More actions'],
                   'tables': {'Товары': ['#', '[pic]', 'Цена DDP', 'Цена']},
                   'table_buttons': {'Товары': ['Add', 'Подбор', '[icon]']}}
        report = form_html.apply_profile(form, profile)
        pages = form['items'][1]['items']
        # live order: «Товары», live-only «Бенефициары», then «Основное» (not seen live -> hidden)
        self.assertEqual([(p['title'], p.get('visible', True)) for p in pages],
                         [('Товары', True), ('Бенефициары', True), ('Основное', False)])
        table = pages[0]['items'][0]
        self.assertEqual([c['title'] for c in table['columns']], ['N', 'Цена DDP', 'Цена'])
        self.assertTrue(table['columns'][1]['from_live'])
        bar = [(b['title'], b.get('visible', True)) for b in form['command_bar']]
        self.assertEqual(bar, [('Провести и закрыть', True), ('Отправить', True), ('Печать', False)])
        self.assertEqual([c['title'] for c in table['commands']], ['Добавить', 'Подбор'])
        self.assertEqual(form['nav'], ['Основное', 'Файлы'])
        self.assertIn('колонка «Цена DDP»', report['added'])
        self.assertIn('кнопка «Печать»', report['hidden'])
        self.assertIn('class="fnav"', form_html.Renderer(form).page())

    def test_profile_table_found_by_columns_when_name_differs(self):
        form = self.extract()
        profile = {'tables': {'Страница предмет': ['N', 'Цена', 'Сумма']}}
        form_html.apply_profile(form, profile)
        table = form['items'][1]['items'][1]['items'][0]
        self.assertEqual([c['title'] for c in table['columns']], ['N', 'Цена', 'Сумма'])
        self.assertIsNone(form_html.find_table(form, 'Нет', ['Количество']))   # too little overlap

    def test_screenshot_profile_loose_titles_and_cut_table(self):
        form = self.extract()
        table = form['items'][1]['items'][1]['items'][0]
        table['columns'] += [{'type': 'InputField', 'name': 'Количество', 'title': 'Количество'},
                             {'type': 'InputField', 'name': 'Сумма', 'title': 'Сумма'}]
        profile = {'tabs': ['основное', 'Товары'], 'buttons': ['провести и закрыть'],
                   'tables': {'Товары': {'columns': ['N', 'Колич…', 'Подразделение-отп…'], 'cut': True}}}
        report = form_html.apply_profile(form, profile)
        self.assertEqual(report['added'], ['колонка «Подразделение-отп…»'])   # a cut title matches by its start only
        shown = [(c['title'], c.get('visible', True)) for c in table['columns']]
        # seen columns first in the live order; the rest may be past the cut edge -> kept
        self.assertEqual(shown, [('N', True), ('Количество', True), ('Подразделение-отп…', True),
                                 ('Цена', True), ('Сумма', True)])
        self.assertEqual([b.get('visible', True) for b in form['command_bar']], [True, False])
        form = self.extract()
        form_html.apply_profile(form, {'cut': True, 'tabs': ['Товары'], 'buttons': ['Провести и закрыть']})
        self.assertTrue(all(b.get('visible', True) for b in form['command_bar']))
        self.assertTrue(all(p.get('visible', True) for p in form['items'][1]['items']))

    def test_profile_keeps_mockup_additions(self):
        form = self.extract()
        table = form['items'][1]['items'][1]['items'][0]
        table['columns'].insert(1, {'type': 'InputField', 'name': 'Спеццена', 'title': 'Спец цена', 'new': True})
        form['command_bar'].append({'type': 'Button', 'name': 'Тест', 'title': 'Тест', 'new': True})
        form_html.apply_profile(form, {'buttons': ['Провести и закрыть'], 'tables': {'Товары': ['N', 'Цена']}})
        self.assertEqual([(c['title'], c.get('visible', True)) for c in table['columns']],
                         [('N', True), ('Цена', True), ('Спец цена', True)])   # stays right after «Цена»
        self.assertTrue(form['command_bar'][-1].get('visible', True))

    def test_outline_and_own_profile_first(self):
        form = self.extract()
        self.assertEqual(form_html.outline(form)['tables']['Товары']['columns'], ['Цена', 'N'])
        own = Path(self.tmp.name) / '.1c-form-mockup' / 'profiles'
        own.mkdir(parents=True)
        (own / form_html.profile_name(form)).write_text('{}', encoding='utf-8')
        saved = form_html.default_src
        form_html.default_src = lambda: str(self.src)
        try:
            self.assertEqual(Path(form_html.profile_path(form)).parent, own)
        finally:
            form_html.default_src = saved

    def test_profile_puts_tabs_in_live_order(self):
        form = self.extract()
        form_html.apply_profile(form, {'tabs': ['Товары', 'Основное']})
        self.assertEqual([p['title'] for p in form['items'][1]['items']], ['Товары', 'Основное'])

    def test_merge_profiles_keeps_order(self):
        a = {'source': 's1', 'tabs': ['Основное', 'Товары'], 'buttons': ['A'], 'tables': {}}
        b = {'source': 's2', 'tabs': ['Основное', 'Товары'], 'buttons': ['A', 'B'],
             'tables': {'Товары': ['N', 'Цена']}, 'table_buttons': {'Товары': ['Add']}}
        merged = form_html.merge_profiles([a, b])
        self.assertEqual(merged['buttons'], ['A', 'B'])
        self.assertEqual(merged['tables'], {'Товары': ['N', 'Цена']})
        self.assertEqual(merged['source'], 's1; s2')

    def test_opens_on_tab_with_change_and_draws_icons(self):
        form = self.extract()
        table = form['items'][1]['items'][1]['items'][0]
        table['columns'].append({'type': 'InputField', 'name': 'Спеццена', 'title': 'Спец цена', 'new': True})
        form['command_bar'].insert(1, {'type': 'Button', 'name': 'Записать', 'title': 'Записать', 'representation': 'Picture'})
        form['command_bar'].insert(2, {'type': 'Button', 'name': 'Х', 'title': 'Неизвестная', 'representation': 'Picture'})
        page = form_html.Renderer(form).page()
        self.assertIn('class="tab active" data-tab="p1_1">Товары', page)   # the tab with the new column
        self.assertIn('<svg', page)
        self.assertNotIn('□', page)
        self.assertIn('>Неизвестная</span>', page)                          # unknown picture -> its title

    def test_add_puts_items_next_to_anchor(self):
        form = self.extract()
        r = form_html.add_item(form, 'column', 'Спец цена', after='цена')          # loose match
        self.assertEqual(r['in'], 'Товары')
        table = form['items'][1]['items'][1]['items'][0]
        self.assertEqual([c['title'] for c in table['columns']], ['Цена', 'Спец цена', 'N'])
        form_html.add_item(form, 'field', 'Страна', after='Клиент', choice=True)
        head = form['items'][0]['items']
        self.assertEqual((head[1]['title'], head[1]['new'], head[1]['choice']), ('Страна', True, True))
        form_html.add_item(form, 'button', 'Пересчитать', table='Товары')
        self.assertEqual(table['commands'][-1]['title'], 'Пересчитать')
        form_html.add_item(form, 'tab', 'Резервы', after='Товары')
        self.assertEqual([p['title'] for p in form['items'][1]['items']], ['Основное', 'Товары', 'Резервы'])
        with self.assertRaises(ValueError) as err:
            form_html.add_item(form, 'field', 'Х', after='Совсем не то')
        self.assertIn('not found', str(err.exception))
        with self.assertRaises(ValueError):
            form_html.add_item(form, 'field', 'Х')                                  # a field needs --after

    def test_render_warns_when_change_is_missing(self):
        run = lambda *a: subprocess.run([sys.executable, '-X', 'utf8', str(SCRIPT), *a], capture_output=True,
                                        text=True, encoding='utf-8')
        js = os.path.join(self.tmp.name, 'f.json')
        page = os.path.join(self.tmp.name, 'f.html')
        run('extract', '--form', str(self.form_path), '--src', str(self.src), '--out', js, '--profile', 'none')
        self.assertIn('warning', json.loads(run('render', '--json', js, '--out', page).stdout))   # nothing new
        form = form_html.read_json(js)
        form['items'][0]['items'][1]['new'] = True     # new, but inside an element hidden in the XML
        Path(js).write_text(json.dumps(form, ensure_ascii=False), encoding='utf-8')
        self.assertIn('not drawn', json.loads(run('render', '--json', js, '--out', page).stdout)['warning'])
        out = run('add', '--json', js, '--kind', 'column', '--title', 'Спец цена', '--after', 'Цена')
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        form = form_html.read_json(js)
        form['items'][0]['items'][1]['new'] = False
        Path(js).write_text(json.dumps(form, ensure_ascii=False), encoding='utf-8')
        self.assertNotIn('warning', json.loads(run('render', '--json', js, '--out', page).stdout))

    def test_mark_frames_existing_element_with_note(self):
        form = self.extract()
        r = form_html.mark_item(form, 'клиент', note='только клиенты менеджера')
        self.assertEqual((r['marked'], r['visible']), ('Клиент', True))
        page = form_html.Renderer(form).page()
        self.assertIn('class="changes"', page)
        self.assertIn('<b>Клиент</b> — только клиенты менеджера', page)
        form_html.add_item(form, 'column', 'Спец цена', after='Цена')                 # no note
        self.assertIn('<b>Спец цена</b> — новая колонка в таблице «Товары»', form_html.Renderer(form).page())
        self.assertIn('id="showNew"', page)
        form_html.mark_item(form, 'Цена', table='Товары')
        self.assertTrue(form['items'][1]['items'][1]['items'][0]['columns'][0]['new'])
        with self.assertRaises(ValueError):
            form_html.mark_item(form, 'Нет такого поля')

    def add_columns(self, form, count):
        for n in range(count):
            form_html.add_item(form, 'column', 'Колонка %d' % n, after='Цена')

    def test_up_to_frame_limit_changes_are_framed_at_once(self):
        form = self.extract()
        self.add_columns(form, form_html.FRAME_LIMIT)
        renderer = form_html.Renderer(form)
        page = renderer.page()
        self.assertEqual(renderer.highlight, 'frames')
        self.assertIn('<body><!--', page)                              # frames on from the start
        self.assertIn('id="showNew" checked', page)
        self.assertEqual(page.count('<li data-goto='), form_html.FRAME_LIMIT)

    def test_many_changes_start_without_frames_and_frame_on_click(self):
        form = self.extract()
        self.add_columns(form, form_html.FRAME_LIMIT)
        form_html.mark_item(form, 'Клиент', note='только клиенты менеджера')
        renderer = form_html.Renderer(form)
        page = renderer.page()
        self.assertEqual(renderer.highlight, 'on click')
        self.assertIn('<body class="plain many">', page)
        self.assertIn('id="showNew">', page)                          # the switch is there, but off
        self.assertNotIn('id="showNew" checked', page)
        self.assertEqual(page.count('<li data-goto='), form_html.FRAME_LIMIT + 1)   # the list stays
        self.assertIn('рамки скрыты', page)
        self.assertIn('data-mark="%d"' % (form_html.FRAME_LIMIT + 1), page)
        self.assertIn('is-new', page)                                  # the switch can still show all frames
        self.assertIn("classList.add('picked')", page)                # a clicked item gets its own frame
        self.assertIn('body.plain .is-new.picked', page)

    def test_png_copy_shows_all_frames(self):
        form = self.extract()
        self.add_columns(form, form_html.FRAME_LIMIT + 1)
        snap = form_html.Renderer(form).page(snapshot=True)
        self.assertIn('<body class="many">', snap)                    # frames on, the list stays
        self.assertIn('id="showNew" checked', snap)
        self.assertIn('<body class="plain many">', form_html.Renderer(form).page())   # the HTML itself is unchanged
        saved = form_html.find_chrome
        form_html.find_chrome = lambda: None
        try:
            png = os.path.join(self.tmp.name, 'x.png')
            self.assertIn('Chrome not found', form_html.screenshot(snap, png))
            self.assertFalse(os.path.exists(png))
        finally:
            form_html.find_chrome = saved

    @unittest.skipUnless(os.environ.get('FORM_MOCKUP_UI_TESTS') == '1', 'Real browser tests require explicit opt-in')
    def test_cli_png_through_real_chrome(self):
        if not form_html.find_chrome():
            self.skipTest('no Chrome on this machine')
        run = lambda *a: subprocess.run([sys.executable, '-X', 'utf8', str(SCRIPT), *a], capture_output=True,
                                        text=True, encoding='utf-8')
        js = os.path.join(self.tmp.name, 'f.json')
        html = os.path.join(self.tmp.name, 'Макет теста.html')
        run('extract', '--form', str(self.form_path), '--src', str(self.src), '--out', js, '--profile', 'none')
        run('add', '--json', js, '--kind', 'column', '--title', 'Спец цена', '--after', 'Цена')
        run('mark', '--json', js, '--title', 'Не отгружать частями', '--note', 'по умолчанию включено')
        result = json.loads(run('render', '--json', js, '--out', html, '--png').stdout)
        self.assertNotIn('png_warning', result)
        self.assertEqual([os.path.basename(p) for p in result['png']],
                         ['Макет теста.png', 'Макет теста (Товары).png'])     # one picture per changed tab
        for png in result['png']:
            with open(png, 'rb') as fh:
                head = fh.read(24)
            self.assertEqual(head[:8], b'\x89PNG\r\n\x1a\n')
            width, height = int.from_bytes(head[16:20], 'big'), int.from_bytes(head[20:24], 'big')
            self.assertEqual((width, height), (form_html.PNG_WIDTH, form_html.PNG_HEIGHT))   # a small form: usual size

    def test_each_changed_tab_gets_its_own_picture(self):
        form = self.extract()
        renderer = form_html.Renderer(form)
        self.assertEqual(renderer.change_tabs(), [])                      # nothing changed
        form_html.add_item(form, 'column', 'Спец цена', after='Цена')
        self.assertEqual(len(renderer.change_tabs()), 1)                  # one complete path, one picture
        form_html.mark_item(form, 'Не отгружать частями')
        tabs = renderer.change_tabs()
        self.assertEqual([[(i, t) for _, i, t in view] for view in tabs], [[(0, 'Основное')], [(1, 'Товары')]])
        self.assertEqual([os.path.basename(p) for p in form_html.png_paths('/x/Макет А.html', tabs)],
                         ['Макет А.png', 'Макет А (Товары).png'])
        snap = form_html.Renderer(form)
        snap.open_tab.update((id(pages), index) for pages, index, _ in tabs[1])
        page = snap.page(snapshot=True)
        self.assertIn('class="tab active" data-tab="p1_1"', page)        # opened on «Товары»
        self.assertIn("setAttribute('data-height'", page)
        self.assertNotIn("setAttribute('data-height'", form_html.Renderer(form).page())

    def test_new_form_is_drawn_clean(self):
        form = self.extract()
        form['new_form'] = True
        self.add_columns(form, form_html.FRAME_LIMIT + 2)
        renderer = form_html.Renderer(form)
        page = renderer.page()
        self.assertEqual(renderer.highlight, 'none (new form)')
        self.assertIn('Колонка 0', page)
        markup = Markup()
        markup.feed(page)
        self.assertFalse(any('data-mark' in e or e.get('id') == 'showNew'
                             or {'is-new', 'changes'} & set(e.get('class', '').split()) for e in markup.elements))
        self.assertEqual(len(renderer.shown_new), form_html.FRAME_LIMIT + 2)   # still checked for being drawn
        run = lambda *a: subprocess.run([sys.executable, '-X', 'utf8', str(SCRIPT), *a], capture_output=True,
                                        text=True, encoding='utf-8')
        js = os.path.join(self.tmp.name, 'new.json')
        html = os.path.join(self.tmp.name, 'new.html')
        out = run('extract', '--form', str(self.form_path), '--src', str(self.src), '--out', js,
                  '--profile', 'none', '--new-form')
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertTrue(form_html.read_json(js)['new_form'])
        result = json.loads(run('render', '--json', js, '--out', html).stdout)
        self.assertNotIn('warning', result)                            # nothing framed is fine for a new form
        self.assertEqual(result['highlight'], 'none (new form)')

    def test_nested_changed_tabs_are_visible_in_the_snapshot_set(self):
        form = self.extract()
        inner = {'type': 'Pages', 'name': 'Inner', 'items': [
            {'type': 'Page', 'name': name, 'title': name, 'items': [
                {'type': 'InputField', 'name': 'Field' + name, 'title': name, 'new': True}]} for name in ('А', 'Б')]}
        form['items'][1]['items'][0]['items'].append(inner)
        views, snapshots = snapshot_markup(form)
        self.assertEqual(len(views), 2)
        self.assertEqual([len(view) for view in views], [2, 2])
        self.assertEqual([m.visible_marks for m in snapshots], [{1}, {2}])

    def test_independent_tab_sets_do_not_hide_changes_or_multiply_all_combinations(self):
        form = self.extract()
        form_html.mark_item(form, 'Не отгружать частями')
        form['items'].append({'type': 'Pages', 'name': 'Second', 'items': [
            {'type': 'Page', 'name': name, 'title': name, 'items': [
                {'type': 'InputField', 'name': 'Field' + name, 'title': name, 'new': True}]} for name in ('А', 'Б')]})
        views, snapshots = snapshot_markup(form)
        self.assertEqual(len(views), 3)
        self.assertEqual(set().union(*(m.visible_marks for m in snapshots)), {1, 2, 3})

    def test_nested_views_cover_changed_ancestor_without_a_duplicate_picture(self):
        form = self.extract()
        page = form['items'][1]['items'][0]
        page['new'] = True
        page['items'].append({'type': 'Pages', 'name': 'Inner', 'items': [
            {'type': 'Page', 'name': 'А', 'items': []},
            {'type': 'Page', 'name': 'Б', 'items': [
                {'type': 'InputField', 'name': 'FieldB', 'title': 'Б', 'new': True}]}]})
        views, snapshots = snapshot_markup(form)
        self.assertEqual(len(views), 1)
        self.assertEqual(len(views[0]), 2)
        self.assertEqual(snapshots[0].visible_marks, {1, 2})

    def test_new_form_snapshots_include_unmarked_pages(self):
        form = self.extract()
        form['new_form'] = True
        views, snapshots = snapshot_markup(form)
        self.assertEqual([[(i, title) for _, i, title in view] for view in views],
                         [[(0, 'Основное')], [(1, 'Товары')]])
        self.assertTrue(all(not m.visible_marks for m in snapshots))

    def test_snapshot_names_are_unique_after_sanitization_and_case_folding(self):
        names = form_html.png_paths('/x/Макет.html', [[], [(None, 0, 'А/Б')],
                                   [(None, 1, 'А:Б')], [(None, 2, 'аБ')]])
        self.assertEqual(len({name.casefold() for name in names}), 4)
        self.assertTrue(names[2].endswith('(АБ) (2).png'))

    def test_cli_png_uses_every_ancestor_tab_without_starting_a_browser(self):
        form = self.extract()
        form['profile_report'] = None
        form['items'][1]['items'][0]['items'].append({'type': 'Pages', 'name': 'Inner', 'items': [
            {'type': 'Page', 'name': name, 'title': name, 'items': [
                {'type': 'InputField', 'name': 'Field' + name, 'title': name, 'new': True}]} for name in ('А', 'Б')]})
        source = os.path.join(self.tmp.name, 'nested.json')
        out = os.path.join(self.tmp.name, 'nested.html')
        form_html.write(source, json.dumps(form))
        rendered = []
        def capture(page, png, size):
            markup = Markup()
            markup.feed(page)
            rendered.append(markup.visible_marks)
            Path(png).write_bytes(b'backend screenshot stub')
        with patch.object(form_html, 'screenshot', side_effect=capture), patch('sys.stdout') as stdout:
            self.assertEqual(form_html.main(['render', '--json', source, '--out', out, '--png']), 0)
        self.assertEqual(rendered, [{1}, {2}])
        self.assertNotIn('png_warning', ''.join(str(c.args[0]) for c in stdout.write.call_args_list if c.args))

    def test_nested_tabs_keep_their_ids_and_choices_reach_the_page(self):
        form = self.extract()
        main = form['items'][1]
        inner = {'type': 'Pages', 'name': 'Вложенные', 'items': [
            {'type': 'Page', 'name': 'А', 'title': 'А', 'items': []}, {'type': 'Page', 'name': 'Б', 'title': 'Б', 'items': []}]}
        main['items'][0]['items'].append(inner)                   # nested tabs inside the first page
        main['items'].append({'type': 'Page', 'name': 'Третья', 'title': 'Третья', 'items': []})
        form['items'][0]['items'][0]['choice'] = True
        page = form_html.Renderer(form, {'choices': {'Клиент': ['ООО «Альфа»', 'ООО «Бета»']}}).page()
        tabs = re.findall(r'data-tab="(p\d+_\d+)"', page)
        pages = re.findall(r'data-page="(p\d+_\d+)"', page)
        self.assertEqual(sorted(tabs), sorted(pages))             # every tab opens its own page
        self.assertIn('data-choices="[&quot;ООО «Альфа»&quot;', page)

    def test_missing_object_is_reported(self):
        self.assertEqual(form_html.find_forms(str(self.src), 'Документ.Нет'), [])

    def test_new_tab_cli_renders_without_false_warning(self):
        run = lambda *a: subprocess.run([sys.executable, '-X', 'utf8', str(SCRIPT), *a],
                                        capture_output=True, text=True, encoding='utf-8')
        spec = Path(self.tmp.name) / 'new-tab.json'
        page = Path(self.tmp.name) / 'new-tab.html'
        form = self.extract()
        spec.write_text(json.dumps(form, ensure_ascii=False), encoding='utf-8')
        added = run('add', '--json', str(spec), '--kind', 'tab', '--title', 'Резервы', '--after', 'Товары')
        self.assertEqual(added.returncode, 0, added.stdout + added.stderr)
        rendered = run('render', '--json', str(spec), '--out', str(page), '--profile', 'none')
        self.assertEqual(rendered.returncode, 0, rendered.stdout + rendered.stderr)
        self.assertNotIn('warning', json.loads(rendered.stdout))
        html = page.read_text(encoding='utf-8')
        self.assertIn('>Резервы</div>', html)
        self.assertIn('data-mark="1"', html)   # the change list has a real target

    def test_new_page_without_tab_strip_is_recorded_and_marked(self):
        form = self.extract()
        pages = form['items'][1]
        pages['tabs'] = 'None'
        form_html.add_item(form, 'tab', 'Резервы', after='Товары')
        proposed = pages['items'][-1]
        renderer = form_html.Renderer(form)
        page = renderer.page()
        self.assertIn(id(proposed), renderer.shown_new)
        self.assertRegex(page, r'data-mark="1"[^>]*class="page v active is-new"')

    def test_profile_restores_observed_elements_and_hidden_ancestors(self):
        form = self.extract()
        pages = form['items'][1]
        goods = pages['items'][1]
        table = goods['items'][0]
        price = table['columns'][0]
        popup = form['command_bar'][1]
        invoice = popup['items'][0]
        for item in (pages, goods, table, price, popup, invoice, table['commands'][0]):
            item['visible'] = False
        report = form_html.apply_profile(form, {
            'tabs': ['Товары'], 'buttons': ['Счет на оплату'],
            'tables': {'Товары': ['Цена', 'N']}, 'table_buttons': {'Товары': ['Добавить']}})
        for item in (pages, goods, table, price, popup, invoice, table['commands'][0]):
            self.assertTrue(item['visible'], item['name'])
        self.assertFalse(pages['items'][-1]['visible'])  # unobserved Основное still hidden
        self.assertEqual([c['title'] for c in form_html.Renderer(form).columns(table['columns'])], ['Цена', 'N'])
        self.assertIn('Цена', report['restored'])

    def test_profile_orders_buttons_sets_default_and_preserves_proposals_and_icons(self):
        form = self.extract()
        form_html.add_item(form, 'button', 'Проверить', after='Провести и закрыть')
        icon = {'type': 'Button', 'name': 'refresh', 'title': 'Перечитать', 'representation': 'Picture'}
        form['command_bar'].append(icon)
        form_html.apply_profile(form, {'buttons': ['*Печать', 'Провести и закрыть']})
        bar = form['command_bar']
        self.assertEqual([b['title'] for b in bar], ['Печать', 'Провести и закрыть', 'Проверить', 'Перечитать'])
        self.assertTrue(bar[0]['default'])
        self.assertFalse(bar[1]['default'])
        self.assertTrue(all(b.get('visible', True) for b in bar))
        self.assertIn('class="btn primary has-menu caret"', form_html.Renderer(form).page())

    def test_table_buttons_follow_profile_order_and_cut_keeps_unseen_commands(self):
        form = self.extract()
        table = form['items'][1]['items'][1]['items'][0]
        table['commands'].append({'type': 'Button', 'name': 'fill', 'title': 'Заполнить'})
        form_html.apply_profile(form, {'cut': True, 'tables': {'Товары': {'columns': ['Цена'], 'cut': True}},
                                      'table_buttons': {'Товары': ['*Заполнить', 'Добавить']},
                                      'buttons': ['Печать']})
        self.assertEqual([b['title'] for b in table['commands']], ['Заполнить', 'Добавить'])
        self.assertTrue(table['commands'][0]['default'])
        self.assertEqual([b['title'] for b in form['command_bar']], ['Печать', 'Провести и закрыть'])
        self.assertTrue(all(b.get('visible', True) for b in form['command_bar']))
        self.assertTrue(all(c.get('visible', True) for c in table['columns']))

    def test_profile_keeps_nested_menu_parent_when_child_is_observed(self):
        form = self.extract()
        popup = form['command_bar'][1]
        form_html.apply_profile(form, {'buttons': ['Счет на оплату', 'Провести и закрыть']})
        self.assertIs(form['command_bar'][0], popup)
        self.assertTrue(popup.get('visible', True))
        self.assertEqual(popup['items'][0]['title'], 'Счет на оплату')

    def test_inline_button_group_orders_observed_and_hides_unobserved_children(self):
        form = self.extract()
        group = {'type': 'ButtonGroup', 'name': 'inline', 'title': '', 'items': [
            {'type': 'Button', 'name': name, 'title': name} for name in ('Первая', 'Вторая', 'Третья')]}
        form['command_bar'].append(group)
        form_html.apply_profile(form, {'buttons': ['*Вторая', 'Первая']})
        self.assertIs(form['command_bar'][0], group)
        self.assertEqual([(b['title'], b.get('visible', True)) for b in group['items']],
                         [('Вторая', True), ('Первая', True), ('Третья', False)])
        self.assertTrue(group['items'][0]['default'])

    def test_configuration_profiles_never_fall_back_to_same_named_ka_profile(self):
        form = form_html.Extractor(str(self.form_path), str(self.src), 'demo-ut').extract()
        own = Path(self.tmp.name) / '.1c-form-mockup/profiles'
        own.mkdir(parents=True)
        ka = own / ('demo-ka.' + form['owner'] + '.' + form['form'] + '.json')
        ka.write_text('{}', encoding='utf-8')
        saved = form_html.default_src
        form_html.default_src = lambda: str(self.src)
        try:
            self.assertIsNone(form_html.profile_path(form))
            _, stop = form_html.resolve_profile(form, 'auto')
            self.assertIn('demo-ut', stop['ask'])
            self.assertIn('/demo-ut.', stop['profile_to_write'])
            ut = own / form_html.profile_name(form)
            ut.write_text('{}', encoding='utf-8')
            self.assertEqual(Path(form_html.profile_path(form)), ut)
        finally:
            form_html.default_src = saved

    def test_configuration_cli_rejects_mixed_dump_and_preserves_scope(self):
        run = lambda *a: subprocess.run([sys.executable, '-X', 'utf8', str(SCRIPT), *a],
                                        capture_output=True, text=True, encoding='utf-8')
        spec = Path(self.tmp.name) / 'ut.json'
        args = ['extract', '--form', str(self.form_path), '--configuration', 'demo-ut',
                '--profile', 'none', '--out', str(spec)]
        rejected = run(*args, '--src', str(self.src.parent / 'unrelated'))
        self.assertEqual(rejected.returncode, 2)
        self.assertFalse(spec.exists())
        accepted = run(*args, '--src', str(self.src))
        self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)
        form = json.loads(spec.read_text(encoding='utf-8'))
        self.assertEqual(form['configuration'], 'demo-ut')
        self.assertIn('1С:Предприятие', form_html.Renderer(form).page())


if __name__ == '__main__':
    unittest.main(verbosity=2)
