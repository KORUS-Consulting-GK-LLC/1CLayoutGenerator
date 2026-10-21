# -*- coding: utf-8 -*-
"""1C managed form XML (configuration dump) -> editable JSON -> clickable HTML mockup.

    python form_html.py find    --object "Документ.ЗаказКлиента"
    python form_html.py extract --form src/Documents/ЗаказКлиента/Forms/ФормаДокумента/Ext/Form.xml --out form.json
    python form_html.py render  --json form.json [--data data.json] --out form.html
    python form_html.py build   --form <Form.xml> --out form.html [--data data.json]

The JSON is the place for mockup changes: add an item with "new": true (a column,
a field, a button, a tab) and render again; new items are highlighted in the HTML.
Rules for each element type: references/form-elements.md.
"""
import argparse
import difflib
import html
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import webbrowser
import xml.etree.ElementTree as ET

F = '{http://v8.1c.ru/8.3/xcf/logform}'
V8 = '{http://v8.1c.ru/8.1/data/core}'
MD = '{http://v8.1c.ru/8.3/MDClasses}'

KIND_FOLDERS = {
    'Документ': 'Documents', 'Справочник': 'Catalogs', 'Отчет': 'Reports', 'Обработка': 'DataProcessors',
    'РегистрСведений': 'InformationRegisters', 'РегистрНакопления': 'AccumulationRegisters',
    'ПланВидовХарактеристик': 'ChartsOfCharacteristicTypes', 'БизнесПроцесс': 'BusinessProcesses',
    'Задача': 'Tasks', 'ПланОбмена': 'ExchangePlans', 'ОбщаяФорма': 'CommonForms', 'ЖурналДокументов': 'DocumentJournals',
    'Document': 'Documents', 'Catalog': 'Catalogs', 'Report': 'Reports', 'DataProcessor': 'DataProcessors',
    'InformationRegister': 'InformationRegisters', 'AccumulationRegister': 'AccumulationRegisters',
    'ChartOfCharacteristicTypes': 'ChartsOfCharacteristicTypes', 'BusinessProcess': 'BusinessProcesses',
    'Task': 'Tasks', 'ExchangePlan': 'ExchangePlans', 'CommonForm': 'CommonForms', 'DocumentJournal': 'DocumentJournals',
}
REF_FOLDERS = {'CatalogRef': 'Catalogs', 'DocumentRef': 'Documents', 'ChartOfCharacteristicTypesRef':
               'ChartsOfCharacteristicTypes', 'BusinessProcessRef': 'BusinessProcesses', 'TaskRef': 'Tasks',
               'ExchangePlanRef': 'ExchangePlans', 'CatalogObject': 'Catalogs', 'DocumentObject': 'Documents',
               'DataProcessorObject': 'DataProcessors', 'ReportObject': 'Reports'}
STANDARD_ATTRIBUTES = {
    'Number': 'Номер', 'Date': 'Дата', 'Code': 'Код', 'Description': 'Наименование', 'Ref': 'Ссылка',
    'DeletionMark': 'Пометка удаления', 'Posted': 'Проведен', 'Owner': 'Владелец', 'Parent': 'Родитель',
    'LineNumber': 'N', 'Predefined': 'Предопределенный', 'Period': 'Период', 'Recorder': 'Регистратор',
}
STANDARD_COMMANDS = {
    'Write': 'Записать', 'WriteAndClose': 'Записать и закрыть', 'Post': 'Провести',
    'PostAndClose': 'Провести и закрыть', 'UndoPosting': 'Отмена проведения', 'Reread': 'Перечитать',
    'Close': 'Закрыть', 'Help': 'Справка', 'CustomizeForm': 'Изменить форму', 'Create': 'Создать',
    'Copy': 'Скопировать', 'Change': 'Изменить', 'Delete': 'Удалить', 'SetDeletionMark': 'Пометить на удаление',
    'Add': 'Добавить', 'MoveUp': 'Переместить вверх', 'MoveDown': 'Переместить вниз', 'Find': 'Найти',
    'CancelSearch': 'Отменить поиск', 'Refresh': 'Обновить', 'OutputList': 'Вывести список',
    'CreateFolder': 'Создать группу', 'Choose': 'Выбрать', 'SortListAsc': 'Сортировать по возрастанию',
    'SortListDesc': 'Сортировать по убыванию', 'ListSettings': 'Настроить список', 'Generate': 'Сформировать',
    'Settings': 'Настройки', 'OK': 'OK', 'Cancel': 'Отмена', 'CopyToClipboard': 'Копировать',
    'SelectAll': 'Выделить все', 'EndEdit': 'Закончить редактирование', 'ShowMultipleSelection': 'Выделение',
}
SKIP = {'ContextMenu', 'ExtendedTooltip', 'SearchStringAddition', 'SearchControlAddition', 'ViewStatusAddition',
        'Events', 'Attributes', 'Commands', 'Parameters', 'CommandInterface', 'CommandSet'}
DOC_FIELDS = {'SpreadSheetDocumentField': 'Табличный документ', 'TextDocumentField': 'Текстовый документ',
              'HTMLDocumentField': 'HTML-документ', 'FormattedDocumentField': 'Форматированный документ',
              'ChartField': 'Диаграмма', 'GanttChartField': 'Диаграмма Ганта', 'PlannerField': 'Планировщик',
              'DendrogramField': 'Дендрограмма', 'GraphicalSchemaField': 'Графическая схема',
              'GeographicalSchemaField': 'Географическая схема', 'CalendarField': 'Календарь',
              'PeriodField': 'Период', 'ProgressBarField': 'Индикатор', 'TrackBarField': 'Ползунок'}


def text(el, tag):
    """Russian (or first) content of a multilingual property such as Title/Synonym."""
    node = el.find(tag) if el is not None else None
    if node is None:
        return ''
    first = ''
    for item in node.iter(V8 + 'item'):
        lang, content = item.find(V8 + 'lang'), item.find(V8 + 'content')
        value = content.text if content is not None and content.text else ''
        if lang is not None and lang.text == 'ru' and value:
            return value
        first = first or value
    return first


def plain(title):
    """Formatted strings (<font ...>, <b>…</>) carry markup; the mockup needs the words."""
    return re.sub(r'\s+', ' ', re.sub(r'<[^<>]*>', '', title or '')).strip()


def prop(el, name, default=None):
    node = el.find(F + name)
    return node.text if node is not None and node.text is not None else default


def split_words(name):
    """Fallback title from an identifier: «НадписьНесколькоСкладов» -> «Надпись нескольких складов»-ish."""
    words = re.findall(r'[А-ЯЁA-Z][а-яёa-z0-9]*|[а-яёa-z0-9]+', name or '')
    return ' '.join([words[0]] + [w.lower() for w in words[1:]]) if words else (name or '')


# ---------------------------------------------------------------- metadata

class Metadata:
    """Synonyms of objects, attributes and tabular sections from the XML dump (src/)."""

    def __init__(self, src_root):
        self.src = src_root
        self.cache = {}

    def load(self, folder, name):
        key = (folder, name)
        if key in self.cache:
            return self.cache[key]
        info = None
        path = os.path.join(self.src, folder, name + '.xml')
        if not inside_path(path, self.src):
            raise ValueError('Metadata reference is outside the selected dump')
        if os.path.isfile(path):
            obj = ET.parse(path).getroot()[0]
            props = obj.find(MD + 'Properties')
            info = {'synonym': text(props, MD + 'Synonym') or name, 'attributes': {}, 'tabular': {},
                    'kind': obj.tag.split('}')[-1]}
            children = obj.find(MD + 'ChildObjects')
            for child in (children if children is not None else []):
                tag = child.tag.split('}')[-1]
                cprops = child.find(MD + 'Properties')
                cname = cprops.find(MD + 'Name').text if cprops is not None and cprops.find(MD + 'Name') is not None else ''
                if tag in ('Attribute', 'Dimension', 'Resource'):
                    info['attributes'][cname] = (text(cprops, MD + 'Synonym') or cname, self.type_of(cprops))
                elif tag == 'TabularSection':
                    attrs = {}
                    sub = child.find(MD + 'ChildObjects')
                    for a in (sub if sub is not None else []):
                        aprops = a.find(MD + 'Properties')
                        aname = aprops.find(MD + 'Name').text
                        attrs[aname] = (text(aprops, MD + 'Synonym') or aname, self.type_of(aprops))
                    info['tabular'][cname] = (text(cprops, MD + 'Synonym') or cname, attrs)
        self.cache[key] = info
        return info

    @staticmethod
    def type_of(props):
        node = props.find(MD + 'Type') if props is not None else None
        types = [t.text for t in node.iter(V8 + 'Type')] if node is not None else []
        return types[0] if len(types) == 1 else (types[0] if types else '')

    def by_type(self, type_name):
        """'cfg:CatalogRef.Номенклатура' -> metadata of the catalog."""
        m = re.match(r'(?:cfg:)?(\w+)\.(.+)$', type_name or '')
        if m and m.group(1) in REF_FOLDERS:
            return self.load(REF_FOLDERS[m.group(1)], m.group(2))
        return None

    def title_of(self, path, owner, form_attrs):
        """Synonym for a DataPath such as Объект.Товары.Номенклатура.Code."""
        parts = path.split('.')
        head = parts[0]
        if head in form_attrs:
            title, type_name, main_table = form_attrs[head]
            if len(parts) == 1:
                return title
            node = self.load(*main_table) if main_table else self.by_type(type_name)
            if node is None and head in ('Объект', 'Object'):
                node = owner
            parts = parts[1:]
        else:
            node = owner
            if head in ('Объект', 'Object'):     # main attribute not declared in the form
                parts = parts[1:]
        tabular = None
        title = ''
        for i, part in enumerate(parts):
            if part in STANDARD_ATTRIBUTES:
                return STANDARD_ATTRIBUTES[part]
            if tabular is not None and part in tabular:
                title, type_name = tabular[part]
                tabular, node = None, self.by_type(type_name)
            elif node and part in node['tabular']:
                title, tabular = node['tabular'][part]
            elif node and part in node['attributes']:
                title, type_name = node['attributes'][part]
                node = self.by_type(type_name)
            else:
                return split_words(part) if i == len(parts) - 1 else ''
        return title


def owner_of(form_path):
    """(src root, owner folder, owner name, form name) from …/src/<Folder>/<Name>/Forms/<Form>/Ext/Form.xml."""
    parts = os.path.normpath(os.path.abspath(form_path)).split(os.sep)
    if 'Forms' in parts:
        i = len(parts) - 1 - parts[::-1].index('Forms')
        return os.sep.join(parts[:i - 2]), parts[i - 2], parts[i - 1], parts[i + 1]
    if 'CommonForms' in parts:
        i = parts.index('CommonForms')
        return os.sep.join(parts[:i]), 'CommonForms', parts[i + 1], parts[i + 1]
    return os.path.dirname(form_path), None, None, os.path.basename(form_path)


# ---------------------------------------------------------------- XML -> JSON

class Extractor:
    def __init__(self, form_path, src_root=None, configuration='default', profiles_dir=None):
        self.configuration = configuration_id(configuration)
        self.profiles_dir = os.path.abspath(profiles_dir) if profiles_dir else None
        if src_root and not inside_path(form_path, src_root):
            raise ValueError('The form must belong to the explicitly selected --src dump')
        self.form_path = form_path
        root, folder, name, form_name = owner_of(form_path)
        self.meta = Metadata(src_root or root)
        self.owner = self.meta.load(folder, name) if folder and folder != 'CommonForms' else None
        self.owner_ref = '%s.%s' % (folder, name) if folder else ''
        self.form_name = form_name
        self.xml = ET.parse(form_path).getroot()
        if self.xml.tag != F + 'Form':
            raise ValueError('Expected a managed Form.xml in Designer XML format')
        self.form_attrs = self.read_attributes()
        self.commands = {c.get('name'): plain(text(c, F + 'Title')) for c in self.xml.iter(F + 'Command')}

    def read_attributes(self):
        attrs = {}
        node = self.xml.find(F + 'Attributes')
        for a in (node if node is not None else []):
            name = a.get('name')
            types = [t.text for t in a.iter(V8 + 'Type')]
            type_name = types[0] if types else ''
            main = None
            mt = a.find('.//' + F + 'MainTable')
            if mt is not None and mt.text and '.' in mt.text:
                kind, obj = mt.text.split('.', 1)
                main = (KIND_FOLDERS.get(kind, kind + 's'), obj)
            attrs[name] = (plain(text(a, F + 'Title')) or split_words(name), type_name, main)
        return attrs

    def title(self, el):
        explicit = plain(text(el, F + 'Title'))
        if explicit:
            return explicit
        path = prop(el, 'DataPath')
        if path:
            return self.meta.title_of(path, self.owner, self.form_attrs) or split_words(path.split('.')[-1])
        command = prop(el, 'CommandName')
        if command:
            return self.command_title(command)
        return ''

    def command_title(self, command):
        kind, _, name = command.rpartition('.')
        if 'StandardCommand' in kind:
            return STANDARD_COMMANDS.get(name, split_words(name))
        if kind.endswith('Form.Command'):
            return self.commands.get(name) or split_words(name)
        if kind.startswith('CommonCommand'):
            info = self.meta.load('CommonCommands', name)
            return info['synonym'] if info else split_words(name)
        return split_words(name)

    def node(self, el):
        tag = el.tag.split('}')[-1]
        if tag in SKIP:
            return None
        item = {'type': tag, 'name': el.get('name', ''), 'title': self.title(el)}
        if prop(el, 'Visible') == 'false':
            item['visible'] = False
        path = prop(el, 'DataPath')
        if path:
            item['path'] = path
        if tag in ('InputField', 'LabelField', 'CheckBoxField', 'RadioButtonField', 'PictureField'):
            default_loc = 'Right' if tag == 'CheckBoxField' else 'Left'
            item['title_location'] = prop(el, 'TitleLocation', default_loc)
            if tag == 'InputField':
                if prop(el, 'ChoiceButton') == 'true' or prop(el, 'DropListButton') == 'true' or \
                        (path and self.is_reference(path)) and prop(el, 'ChoiceButton') != 'false':
                    item['choice'] = True
                if prop(el, 'MultiLine') == 'true' or int(prop(el, 'Height', '1') or 1) > 1:
                    item['multiline'] = True
                if prop(el, 'Width'):
                    item['width'] = int(prop(el, 'Width'))
                if prop(el, 'HorizontalStretch') == 'true':
                    item['stretch'] = True
            if prop(el, 'Hyperlink') == 'true':
                item['hyperlink'] = True
            if tag == 'RadioButtonField':
                item['options'] = [plain(text(v, F + 'Presentation')) or plain(v.findtext('.//' + V8 + 'content') or '')
                                   for v in el.iter(F + 'ChoiceListItem')] or [item['title']]
        elif tag == 'LabelDecoration':
            item['hyperlink'] = prop(el, 'Hyperlink') == 'true'
        elif tag == 'Button':
            item['command'] = prop(el, 'CommandName', '')
            item['button_type'] = prop(el, 'Type', 'UsualButton')
            item['representation'] = prop(el, 'Representation', 'Auto')
            if prop(el, 'DefaultButton') == 'true':
                item['default'] = True
        elif tag == 'Popup':
            item['representation'] = prop(el, 'Representation', 'Auto')
        elif tag in ('UsualGroup', 'Page', 'ColumnGroup'):
            item['group'] = prop(el, 'Group', 'Vertical')
            if tag == 'UsualGroup':
                item['show_title'] = prop(el, 'ShowTitle', 'true') == 'true'
                item['collapsible'] = prop(el, 'Behavior') == 'Collapsible'
                item['representation'] = prop(el, 'Representation', 'Auto')
            if tag == 'ColumnGroup':
                item['show_title'] = prop(el, 'ShowTitle', 'true') == 'true'
        elif tag == 'Pages':
            item['tabs'] = prop(el, 'PagesRepresentation', 'TabsOnTop')
        elif tag == 'Table':
            item['tree'] = prop(el, 'Representation') == 'Tree'
            item['header'] = prop(el, 'Header', 'true') == 'true'
            bar = el.find(F + 'AutoCommandBar')
            item['commands'] = self.bar(bar, standard=('Добавить',)) if bar is not None else []
            search = el.find(F + 'SearchStringAddition')
            if search is not None and prop(search, 'Visible') != 'false':
                item['search'] = True
        elif tag in DOC_FIELDS:
            item['title'] = item['title'] or DOC_FIELDS[tag]
        children = el.find(F + 'ChildItems')
        if children is not None:
            kids = [k for k in (self.node(c) for c in children) if k]
            if kids:
                item['columns' if tag == 'Table' else 'items'] = kids
        return item

    def is_reference(self, path):
        parts = path.split('.')
        if parts[0] in ('Объект', 'Object') and self.owner and len(parts) == 2:
            attr = self.owner['attributes'].get(parts[1])
            return bool(attr and re.search(r'Ref\.', attr[1] or ''))
        return False

    def bar(self, bar, standard=()):
        items = []
        children = bar.find(F + 'ChildItems')
        for c in (children if children is not None else []):
            n = self.node(c)
            if n:
                items.append(n)
        if prop(bar, 'Autofill', 'true') == 'true':
            items = [{'type': 'Button', 'name': 'auto' + s, 'title': s, 'button_type': 'CommandBarButton',
                      'auto': True} for s in standard] + items
        return items

    def standard_form_commands(self):
        excluded = {e.text for e in self.xml.iter(F + 'ExcludedCommand')}
        kind = (self.owner or {}).get('kind')
        list_form = any(main for _, _, main in self.form_attrs.values()) or 'Список' in self.form_name
        if list_form:
            spec = [('Create', True)]
        elif kind == 'Document':
            spec = [('PostAndClose', True), ('Write', False), ('Post', False)]
        elif kind in ('Catalog', 'ChartOfCharacteristicTypes', 'ExchangePlan', 'BusinessProcess', 'Task'):
            spec = [('WriteAndClose', True), ('Write', False)]
        elif kind == 'Report':
            spec = [('Generate', True)]
        else:
            spec = []
        return [{'type': 'Button', 'name': 'std' + c, 'title': STANDARD_COMMANDS[c], 'button_type': 'CommandBarButton',
                 'default': d, 'auto': True} for c, d in spec if c not in excluded]

    def extract(self):
        bar = self.xml.find(F + 'AutoCommandBar')
        commands = self.bar(bar) if bar is not None else []
        if bar is None or prop(bar, 'Autofill', 'true') == 'true':
            commands = self.standard_form_commands() + [c for c in commands if not c.get('auto')]
        children = self.xml.find(F + 'ChildItems')
        items = [k for k in (self.node(c) for c in (children if children is not None else [])) if k]
        owner_title = (self.owner or {}).get('synonym', '')
        title = plain(text(self.xml, F + 'Title')) or owner_title or split_words(self.form_name)
        return {'format': '1c-form-mockup-1', 'configuration': self.configuration,
                'source_root': os.path.abspath(self.meta.src), 'profiles_dir': self.profiles_dir,
                'source': self.form_path.replace('\\', '/'),
                'owner': self.owner_ref, 'form': self.form_name, 'title': title,
                'command_bar': commands, 'items': items}


# ---------------------------------------------------------------- JSON -> HTML

CSS = r"""
/* Values measured in the 1C web client, platform 8.3.27 «Такси» (trade.demo.1c.ru, 15.10.2026). */
:root{--panel:#fbed9e;--line:#ccc;--tabline:#b3b3b3;--ink:#4b4b4b;--label:#4d4d4d;--value:#333;--link:#1c55ae;
--field:#a0a0a0;--head:#f2f2f2;--even:#fafafa;--sel:#fef2c6;--focus:#facc1f;--default:#ffe100;--green:#009646;--new:#e8590c}
*{box-sizing:border-box}html,body{height:100%}
body{margin:0;font:13.33px Almarai,Arial,sans-serif;color:var(--ink);background:#fff}
button,input,textarea,select{font:inherit;color:inherit}
.apphead{height:31px;background:var(--panel);display:flex;align-items:center;gap:10px;padding:0 12px;font-size:13.33px;color:#333}
.logo{font:bold 18px Arial;color:#d02d22;letter-spacing:-2px}
.shell{display:grid;grid-template-columns:173px minmax(0,1fr);height:calc(100% - 31px)}
.side{background:var(--panel);padding:6px 0;overflow:auto}
.side div{padding:8px 14px;color:#333}.side div.active{background:#fff}
.work{display:flex;flex-direction:column;min-width:0;overflow:hidden}
.wtabs{display:flex;height:31px;background:var(--head);align-items:stretch}
.wtabs span{padding:0 10px;display:flex;align-items:center;color:#333;position:relative}
.wtabs span.active{background:#fff}.wtabs span.active:before{content:"";position:absolute;left:0;right:0;top:0;height:2px;background:var(--green)}
.form{padding:10px 14px 24px;overflow:auto;flex:1}
.ftitle{display:flex;align-items:center;gap:6px;margin:0 0 8px}.ftitle h1{font-size:18px;font-weight:normal;margin:0 0 0 4px;color:#333}
.nav{width:27px;height:27px;display:inline-grid;place-items:center;color:#4b4b4b;border-radius:2px;
background:linear-gradient(#fff,#f2f2f2);border:1px solid rgba(0,0,0,.3);border-bottom-color:rgba(0,0,0,.4);box-shadow:0 1px 0 rgba(0,0,0,.2)}
.bar{display:flex;flex-wrap:wrap;align-items:center;gap:4px;margin:4px 0 10px}
.btn{height:27px;padding:0 6px;display:inline-flex;align-items:center;gap:5px;white-space:nowrap;cursor:pointer;position:relative;
color:var(--ink);border-radius:2px;background:linear-gradient(#fff,#f2f2f2);border:1px solid rgba(0,0,0,.3);
border-bottom-color:rgba(0,0,0,.4);box-shadow:0 1px 0 rgba(0,0,0,.2)}
.btn:hover{box-shadow:0 1px 0 rgba(0,0,0,.2),inset 0 0 0 1px rgba(0,0,0,.08)}.btn:active{box-shadow:inset 0 2px 0 rgba(0,0,0,.2)}
.btn.primary{background:var(--default);color:#333;font-weight:bold}
.btn.link,.link{color:var(--link);background:none;border:0;box-shadow:none;padding:0;text-decoration:underline;cursor:pointer;height:auto}
.btn.pic{width:27px;justify-content:center;padding:0}.btn.pic.caret{width:auto;padding:0 4px}.caret:after{content:"▾";font-size:10px;margin-left:2px}
.menu{display:none;position:absolute;top:100%;left:0;z-index:5;background:#fff;border:1px solid var(--tabline);box-shadow:0 3px 9px rgba(0,0,0,.15);
min-width:190px;padding:3px 0;text-align:left;font-weight:normal;color:#333}.menu div{padding:5px 14px}.menu div:hover{background:var(--focus)}
.btn.open .menu{display:block}
.v{display:flex;flex-direction:column;gap:6px;min-width:0}.h{display:flex;flex-wrap:wrap;gap:6px 16px;align-items:flex-start;min-width:0}
.h.always{flex-wrap:nowrap}.grp{min-width:0}.grp>.gt{font-weight:bold;color:#333;margin:6px 0 4px;cursor:default}
.grp.sep{border-top:1px solid var(--line);padding-top:6px}.grp.collapsible>.gt{cursor:pointer}.grp.collapsible>.gt:before{content:"▾ "}
.grp.collapsed>.gt:before{content:"▸ "}.grp.collapsed>.body{display:none}
.fld{display:flex;align-items:center;gap:6px;min-width:0}.fld.top{flex-direction:column;align-items:flex-start;gap:2px}
.fld label{color:var(--label);white-space:nowrap}
.box{display:flex;align-items:stretch;height:25px;min-width:60px;background:#fff;border-radius:3px;box-shadow:inset 0 0 0 1px var(--field)}
.box input{border:0;outline:none;padding:0 6px;width:100%;background:none;color:var(--value)}
.box textarea{border:0;outline:none;padding:4px 6px;width:100%;resize:vertical;background:none;color:var(--value)}
.box.multi{height:auto;min-height:48px}.box:focus-within{box-shadow:inset 0 0 0 1px var(--focus),0 0 0 1px var(--focus)}
.box .pick{width:22px;flex:0 0 22px;display:grid;place-items:center;color:#6b6b6b;cursor:pointer;font-size:10px;
border-radius:0 3px 3px 0;background:linear-gradient(#fff,#f2f2f2);box-shadow:inset 0 0 0 1px var(--field)}
.box .pick.list:after{content:"▾"}.box .pick.dots:after{content:"…"}
.stretch{flex:1}.stretch .box{flex:1}.value{color:var(--value)}
.chk{display:inline-flex;align-items:center;gap:6px;cursor:pointer;color:var(--ink)}
.chk input{width:14px;height:14px;margin:0;accent-color:var(--green)}
.radio{display:inline-flex;gap:12px}.pic{width:16px;height:16px;border:1px solid #c9c9c9;border-radius:2px;background:#f4f4f4;display:inline-block}
.tabs{display:flex;gap:2px;margin:6px 0 8px;box-shadow:inset 0 -1px 0 var(--tabline)}
.tab{height:28px;padding:0 12px;display:flex;align-items:center;border:1px solid var(--tabline);border-radius:3px 3px 0 0;
background:#e6e6e6;color:#333;cursor:pointer}
.tab.active{background:#fff;border-bottom-color:#fff}.page{display:none}.page.active{display:flex}
.tblwrap{overflow:auto;max-width:100%;box-shadow:inset 0 0 0 1px var(--line)}table.t{border-collapse:collapse;min-width:100%}
table.t th{background:var(--head);font-weight:normal;color:#333;text-align:left;height:31px;padding:0 8px;
border-right:1px solid var(--line);border-bottom:1px solid var(--line);white-space:nowrap}
table.t td{height:29px;padding:0 8px;border-right:1px solid #e6e6e6;white-space:nowrap;color:var(--value)}
table.t tbody tr:nth-child(even) td{background:var(--even)}table.t td.num{text-align:right}
table.t tr.sel td{background:var(--sel)!important}table.t tbody tr{cursor:pointer}table.t tbody tr:hover td{background:#e6e6e6}
.doc{border:1px dashed #bbb;color:#999;padding:24px;text-align:center;min-width:300px}
.is-new{outline:2px solid var(--new);outline-offset:2px;position:relative}
th.is-new,td.is-new{outline:0;box-shadow:inset 0 0 0 2px var(--new)}
.legend{margin-left:auto;font-size:12px;color:#888;display:flex;align-items:center;gap:6px}
.legend i{display:inline-block;width:12px;height:12px;border:2px solid var(--new)}
body.plain .is-new{outline:0}body.plain th.is-new,body.plain td.is-new{box-shadow:none}
body.plain .is-new.picked{outline:2px solid var(--new)}body.plain th.is-new.picked,body.plain td.is-new.picked{box-shadow:inset 0 0 0 2px var(--new)}
.toast{position:fixed;right:16px;bottom:16px;background:#ffffe9;color:#4b4b4b;border:1px solid var(--tabline);padding:8px 12px;
border-radius:2px;box-shadow:0 2px 8px rgba(0,0,0,.15);opacity:0;transition:opacity .2s}
.fnav{display:flex;flex-wrap:wrap;gap:4px 18px;align-items:center;margin:0 0 6px}
.fnav span{padding:4px 0}.fnav span.active{background:var(--head);color:#333;padding:4px 10px}
.changes{border:1px solid var(--new);background:#fff8f2;color:#333;padding:6px 10px;margin:0 0 8px;font-size:12.5px}
.changes ol{margin:4px 0 0 18px;padding:0}body.plain:not(.many) .changes{display:none}
.changes li{cursor:pointer}.changes li:hover b{text-decoration:underline}.changes .hint{color:#888;font-weight:normal}
.dd{position:absolute;z-index:20;background:#fff;border:1px solid var(--tabline);box-shadow:0 3px 9px rgba(0,0,0,.18);padding:3px 0;min-width:180px}
.dd div{padding:5px 12px;cursor:pointer;color:#333}.dd div:hover{background:var(--focus)}.dd div.all{color:var(--link);border-top:1px solid #eee}
.dlgwrap{position:fixed;inset:0;background:rgba(0,0,0,.18);display:flex;align-items:center;justify-content:center;z-index:30}
.dlg{background:#fff;border:1px solid var(--tabline);box-shadow:0 6px 24px rgba(0,0,0,.28);min-width:440px;max-width:90vw}
.dlg .dh{padding:10px 14px 4px;font-size:18px;color:#333}.dlg .db{padding:6px 14px}.dlg .df{padding:10px 14px;display:flex;gap:6px}
.dlg table.t{width:100%}td.empty{color:#999;text-align:center;height:60px}
.fsec{display:none}.form.sec .fmain{display:none}.form.sec .fsec{display:block}.fnav span{cursor:pointer}.side div{cursor:pointer}
td[contenteditable=true]{outline:2px solid var(--focus);background:#fff!important}
@keyframes flash{0%,100%{box-shadow:0 0 0 0 transparent}50%{box-shadow:0 0 0 5px var(--new)}}.flash{animation:flash .6s 3}
@keyframes cellflash{50%{background:#ffd8bf}}table.t th.flash,table.t td.flash{animation:cellflash .6s 3}
.toast.show{opacity:1}.hidden-el{opacity:.45;outline:1px dashed #aaa}
"""

JS = r"""
function toast(s){var t=document.querySelector('.toast');t.textContent=s;t.classList.add('show');clearTimeout(t._h);t._h=setTimeout(function(){t.classList.remove('show')},1800)}
function closeDD(){document.querySelectorAll('.dd').forEach(function(x){x.remove()})}
function showTab(tab){var p=tab.closest('.pages');
 p.querySelectorAll(':scope>.tabs>.tab').forEach(function(x){x.classList.toggle('active',x===tab)});
 p.querySelectorAll(':scope>.page').forEach(function(x){x.classList.toggle('active',x.dataset.page===tab.dataset.tab)})}
function reveal(el){ // open every tab and group around el, then point at it
 for(var x=el.closest('.page');x;x=x.parentElement.closest('.page')){var t=document.querySelector('[data-tab="'+x.dataset.page+'"]');if(t)showTab(t)}
 for(var g=el.closest('.grp.collapsed');g;g=g.parentElement.closest('.grp.collapsed'))g.classList.remove('collapsed');
 document.querySelector('.form').classList.remove('sec');
 var cells=[el];
 if(el.tagName==='TH'){var w=el.closest('.tblwrap');w.scrollLeft=Math.max(0,el.offsetLeft-w.clientWidth/3);
  // a table cell's shadow is hidden by its neighbours: flash the whole column instead
  var i=el.cellIndex;el.closest('table').querySelectorAll('tr').forEach(function(r){if(r.cells[i])cells.push(r.cells[i])})}
 el.scrollIntoView({block:'center',inline:'nearest'});
 // with the frames off (many changes) only the picked element gets its frame back
 document.querySelectorAll('.picked').forEach(function(c){c.classList.remove('picked')});
 cells.forEach(function(c){if(c.classList.contains('is-new'))c.classList.add('picked');
  c.classList.remove('flash');void c.offsetWidth;c.classList.add('flash')})}
function labelOf(box){var f=box.closest('.fld');var l=f&&f.querySelector('label');return l?l.textContent.replace(/:$/,''):'Значение'}
function choicesOf(pick){var title=labelOf(pick.closest('.box'));
 try{if(pick.dataset.choices)return JSON.parse(pick.dataset.choices)}catch(e){}
 var cur=pick.parentNode.querySelector('input').value;var a=[title+' 1',title+' 2',title+' 3'];if(cur)a.unshift(cur);return a}
function setValue(box,v){box.querySelector('input').value=v;toast('Выбрано: '+v)}
function choiceDialog(box){closeDD();var title=labelOf(box),list=choicesOf(box.querySelector('.pick'));
 var w=document.createElement('div');w.className='dlgwrap';
 w.innerHTML='<div class="dlg"><div class="dh"></div><div class="db"><div class="bar"><span class="btn primary" data-act="pick">Выбрать</span>'+
  '<span class="btn" data-act="new">Создать</span><span class="box" style="margin-left:auto;width:200px"><input placeholder="Поиск (Ctrl+F)"></span></div>'+
  '<div class="tblwrap"><table class="t"><thead><tr><th>Наименование</th></tr></thead><tbody></tbody></table></div></div>'+
  '<div class="df"><span class="btn" data-act="close">Закрыть</span></div></div>';
 w.querySelector('.dh').textContent=title;var tb=w.querySelector('tbody');
 list.forEach(function(v,i){var tr=document.createElement('tr');if(!i)tr.className='sel';var td=document.createElement('td');td.textContent=v;tr.appendChild(td);tb.appendChild(tr)});
 w._box=box;document.body.appendChild(w)}
document.addEventListener('click',function(e){
 var dlg=e.target.closest('.dlgwrap');
 if(dlg){var act=e.target.closest('[data-act]'),row=e.target.closest('tbody tr');
  if(row){dlg.querySelectorAll('tbody tr').forEach(function(x){x.classList.toggle('sel',x===row)})}
  if(act&&act.dataset.act==='close'||e.target===dlg){dlg.remove()}
  else if(act&&act.dataset.act==='pick'){var s=dlg.querySelector('tr.sel td');if(s)setValue(dlg._box,s.textContent);dlg.remove()}
  else if(act){toast('Команда «'+act.textContent+'» — макет, действие не выполняется')}
  return}
 var dd=e.target.closest('.dd');
 if(dd){var it=e.target.closest('div[data-v]');if(it){it.classList.contains('all')?choiceDialog(dd._box):setValue(dd._box,it.dataset.v)}closeDD();return}
 closeDD();
 var pick=e.target.closest('.box .pick');
 if(pick){var box=pick.closest('.box'),r=box.getBoundingClientRect(),d=document.createElement('div');d.className='dd';d._box=box;
  choicesOf(pick).forEach(function(v){var x=document.createElement('div');x.textContent=v;x.dataset.v=v;d.appendChild(x)});
  var all=document.createElement('div');all.className='all';all.dataset.v='';all.textContent='Показать все';d.appendChild(all);
  d.style.left=(r.left+window.scrollX)+'px';d.style.top=(r.bottom+window.scrollY+1)+'px';d.style.minWidth=r.width+'px';document.body.appendChild(d);return}
 var goto=e.target.closest('[data-goto]');if(goto){var el=document.querySelector('[data-mark="'+goto.dataset.goto+'"]');if(el)reveal(el);return}
 var t=e.target.closest('[data-tab]');if(t){showTab(t);return}
 var nav=e.target.closest('.fnav span');
 if(nav){var f=document.querySelector('.form');nav.parentNode.querySelectorAll('span').forEach(function(x){x.className=x===nav?'active':'link'});
  var first=nav===nav.parentNode.firstElementChild;f.classList.toggle('sec',!first);f.querySelector('.sname').textContent=nav.textContent;return}
 var side=e.target.closest('.side div');if(side){toast('Раздел «'+side.textContent+'» — вне макета');return}
 var g=e.target.closest('.grp.collapsible>.gt');if(g){g.parentNode.classList.toggle('collapsed');return}
 var r=e.target.closest('table.t tbody tr');if(r){r.parentNode.querySelectorAll('tr').forEach(function(x){x.classList.toggle('sel',x===r)})}
 var m=e.target.closest('.btn.has-menu');document.querySelectorAll('.btn.open').forEach(function(x){if(x!==m)x.classList.remove('open')});
 if(m){if(e.target.closest('.menu div')){toast('Команда «'+e.target.textContent.trim()+'» — макет, действие не выполняется');m.classList.remove('open')}
  else m.classList.toggle('open');return}
 var b=e.target.closest('.btn,.link');if(!b||b.closest('.menu'))return;
 var name=(b.dataset.title||b.textContent).trim(),tbl=b.closest('.v.stretch');
 var body=tbl&&tbl.querySelector('table.t tbody');
 if(body&&/^(Добавить|Создать)$/.test(name)){var last=body.lastElementChild,tr=last.cloneNode(true);
  tr.querySelectorAll('td').forEach(function(td,i){if(td.querySelector('input[type=checkbox]'))td.querySelector('input').checked=false;else td.textContent=i?'':body.children.length+1});
  body.appendChild(tr);body.querySelectorAll('tr').forEach(function(x){x.classList.toggle('sel',x===tr)});tr.scrollIntoView({block:'nearest'});
  toast('Добавлена строка — двойной щелчок по ячейке, чтобы ввести значение');return}
 if(body&&/^(Удалить|Пометить на удаление)/.test(name)){var s=body.querySelector('tr.sel');if(s&&body.children.length>1){s.remove();toast('Строка удалена')}return}
 if(/^Записать$/.test(name)){toast('Записано (макет)');return}
 if(/^Провести/.test(name)){toast('Документ проведен (макет)');return}
 toast('Команда «'+name+'» — макет, действие не выполняется')});
document.addEventListener('dblclick',function(e){var td=e.target.closest('table.t td');if(!td||td.closest('.dlg')){
  var row=e.target.closest('.dlg tbody tr');if(row){var w=row.closest('.dlgwrap');setValue(w._box,row.textContent);w.remove()}return}
 if(td.querySelector('input'))return;td.contentEditable='true';td.focus()});
document.addEventListener('focusout',function(e){if(e.target.matches&&e.target.matches('td[contenteditable=true]'))e.target.contentEditable='false'});
document.addEventListener('keydown',function(e){if(e.key==='Escape'){closeDD();document.querySelectorAll('.dlgwrap').forEach(function(x){x.remove()})}
 if(e.key==='Enter'&&e.target.matches&&e.target.matches('td[contenteditable=true]')){e.preventDefault();e.target.blur()}});
document.addEventListener('input',function(e){var i=e.target;if(!i.matches('.bar .box input'))return;var q=i.value.toLowerCase();
 var scope=i.closest('.dlg')||i.closest('.v.stretch')||i.closest('.fsec');var tb=scope&&scope.querySelector('table.t tbody');
 if(tb)tb.querySelectorAll('tr').forEach(function(r){r.style.display=!q||r.textContent.toLowerCase().indexOf(q)>=0?'':'none'})});
document.getElementById('showNew')&&document.getElementById('showNew').addEventListener('change',function(e){document.body.classList.toggle('plain',!e.target.checked)});
// show the change at once: scroll each table to its first new column, the page to the first new item
document.querySelectorAll('.tblwrap').forEach(function(w){var th=w.querySelector('th.is-new');
 if(th){w.scrollLeft=Math.max(0,th.offsetLeft-w.clientWidth/3)}});
(function(){var n=document.querySelector('.page.active .is-new:not(th):not(td), .bar .is-new');if(n&&n.scrollIntoView){n.scrollIntoView({block:'center'})}})();
"""

SECTIONS = ['Главное', 'Продажи', 'Закупки', 'Склад и доставка', 'Производство', 'Казначейство',
            'Финансовый результат и контроллинг', 'НСИ и администрирование']


def esc(value):
    return html.escape(str(value if value is not None else ''), quote=True)


_DOC = '<path d="M3.5 1.5h6l3 3v10h-9z" fill="#fff" stroke="#8a8a8a"/>'
ICONS = [  # (words in the title, 16px SVG body) — the usual «Такси» pictures of standard commands
    (('провести',), _DOC + '<path d="M5.5 9l2 2 3.5-4" stroke="#2c9a3e" stroke-width="1.8" fill="none"/>'),
    (('создать на основании',), _DOC + '<path d="M5 10h5m-2-2.5L10.5 10 8 12.5" stroke="#2c9a3e" stroke-width="1.6" fill="none"/>'),
    (('записать',), '<rect x="2" y="2" width="12" height="12" rx="1" fill="#4a7bc4"/><rect x="4.5" y="2" width="7" height="4" fill="#fff"/>'
                    '<rect x="5" y="9" width="6" height="5" fill="#dfe8f5"/>'),
    (('пометить на удаление', 'удалить'), '<path d="M4 4l8 8M12 4l-8 8" stroke="#d0342c" stroke-width="2"/>'),
    (('перечитать', 'обновить'), '<path d="M12.5 8A4.5 4.5 0 1 1 11 4.6" stroke="#2c9a3e" stroke-width="1.8" fill="none"/>'
                                 '<path d="M9.5 2.5h3.5v3.5z" fill="#2c9a3e"/>'),
    (('найти', 'поиск'), '<circle cx="7" cy="7" r="4" stroke="#6b6b6b" stroke-width="1.6" fill="none"/>'
                         '<path d="M10 10l4 4" stroke="#6b6b6b" stroke-width="2"/>'),
    (('скопировать', 'копировать'), '<rect x="2.5" y="2.5" width="8" height="9" fill="#fff" stroke="#8a8a8a"/>'
                                    '<rect x="5.5" y="5.5" width="8" height="9" fill="#fff" stroke="#8a8a8a"/>'),
    (('добавить', 'создать'), '<path d="M8 3v10M3 8h10" stroke="#2c9a3e" stroke-width="2.4"/>'),
    (('печать',), '<rect x="4" y="2" width="8" height="4" fill="#fff" stroke="#6b6b6b"/><rect x="2" y="6" width="12" height="6" rx="1" fill="#8a8a8a"/>'
                  '<rect x="4" y="10" width="8" height="4" fill="#fff" stroke="#6b6b6b"/>'),
    (('изменить',), '<path d="M3 13l1-3 7-7 2 2-7 7z" fill="#f2c94c" stroke="#8a6d1d"/>'),
    (('заполнить',), '<path d="M3 4h10M3 8h6M3 12h6" stroke="#8a8a8a" stroke-width="1.5"/><path d="M12 7v6m-2-2l2 2 2-2" stroke="#2c9a3e" stroke-width="1.5" fill="none"/>'),
    (('вверх',), '<path d="M8 3l5 6H3z" fill="#2c9a3e"/><rect x="6.5" y="9" width="3" height="4" fill="#2c9a3e"/>'),
    (('вниз',), '<path d="M8 13l5-6H3z" fill="#2c9a3e"/><rect x="6.5" y="3" width="3" height="4" fill="#2c9a3e"/>'),
]


def icon(title):
    """SVG for a picture-only button, or None when its picture is unknown (then the title is shown)."""
    t = (title or '').lower()
    for words, body in ICONS:
        if any(w in t for w in words):
            return '<svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">%s</svg>' % body
    return None


FRAME_LIMIT = 5   # more changes than this: frames start hidden, a «Что меняется» item shows its own frame


class Renderer:
    def __init__(self, form, data=None, show_hidden=False):
        self.form = form
        self.data = data or {}
        self.show_hidden = show_hidden
        self.counter = 0
        self.frames = not form.get('new_form')   # a new form is drawn clean: everything on it is new
        self.highlight = None    # set by page(): 'frames', 'on click' or 'none (new form)'
        self.shown_new = set()   # id() of "new" items drawn on the page
        self.marks = {}          # id() of framed items -> number in «Что меняется»
        self.notes = {}          # id() of framed items -> its line there
        self.open_tab = {}       # id() of a Pages item -> index of the tab to open (one picture per changed tab)

    def visible(self, item):
        return item.get('visible', True) or self.show_hidden

    def change_tabs(self):
        """Tab paths for the pictures: each [(Pages, index, title), ...] opens every ancestor.
        Independent tab sets need no Cartesian product; one path per changed branch suffices.
        A new form includes every visible page even when its fields have no individual marks.
        """
        paths, seen = [], set()
        for item, parents in walk_items(self.form.get('command_bar', []) + self.form.get('items', [])):
            if not (item.get('new') or self.form.get('new_form') and item['type'] == 'Page'):
                continue
            if not all(self.visible(x) for x in parents + (item,)):
                continue
            path = []
            for parent, child in zip(parents, parents[1:] + (item,)):
                if parent['type'] == 'Pages':
                    shown = [p for p in parent.get('items', []) if self.visible(p)]
                    index = next(i for i, p in enumerate(shown) if p is child)
                    path.append((parent, index, child.get('title') or child.get('name')))
            key = tuple((id(pages), index) for pages, index, _ in path)
            if key and key not in seen:
                seen.add(key)
                paths.append(path)
        # A deeper view already shows changes on its ancestor page.
        keys = [tuple((id(pages), index) for pages, index, _ in path) for path in paths]
        return [path for path, key in zip(paths, keys)
                if not any(len(other) > len(key) and other[:len(key)] == key for other in keys)]

    def cls(self, item, *extra):
        names = [c for c in extra if c]
        if item.get('new'):
            if self.frames:
                names.append('is-new')
            self.shown_new.add(id(item))
        if not item.get('visible', True):
            names.append('hidden-el')
        return ' '.join(names)

    def value_for(self, item):
        values = self.data.get('fields', {})
        for key in (item.get('name'), item.get('title'), item.get('path')):
            if key and key in values:
                return values[key]
        return item.get('value', '')

    # -- elements
    def render(self, item):
        if not self.visible(item):
            return ''
        method = getattr(self, 'r_' + item['type'], None)
        out = method(item) if method else self.r_unknown(item)
        return self.with_mark(item, out)

    def with_mark(self, item, out):
        if id(item) in self.marks:
            out = out.replace('class="', 'data-mark="%d" title="%s" class="' % (
                self.marks[id(item)], esc(self.notes.get(id(item)))), 1)
        return out

    def children(self, item):
        return ''.join(self.render(c) for c in item.get('items', []))

    def layout(self, group):
        g = group.get('group', 'Vertical')
        if g in ('Horizontal', 'AlwaysHorizontal', 'HorizontalIfPossible'):
            return 'h always' if g == 'AlwaysHorizontal' else 'h'
        return 'v'

    def r_UsualGroup(self, item):
        title = item.get('title') if item.get('show_title') else ''
        classes = self.cls(item, 'grp', 'sep' if item.get('representation') in ('NormalSeparation', 'StrongSeparation') else '',
                           'collapsible' if item.get('collapsible') else '')
        head = '<div class="gt">%s</div>' % esc(title) if title else ''
        return '<div class="%s">%s<div class="body %s">%s</div></div>' % (classes, head, self.layout(item), self.children(item))

    r_ColumnGroup = r_UsualGroup

    def r_Pages(self, item):
        pages = [p for p in item.get('items', []) if self.visible(p)]
        if not pages:
            return ''
        self.counter += 1
        n = self.counter   # nested Pages move self.counter while this one's pages are drawn
        # the mockup opens on the tab with the change, else on the first one
        first = self.open_tab.get(id(item))
        if first is None:
            first = next((i for i, p in enumerate(pages) if any(x.get('new') for x, _ in walk_items([p]))), 0)
        tabs = ''
        if item.get('tabs') != 'None':
            tabs = '<div class="tabs">%s</div>' % ''.join(
                self.with_mark(p, '<div class="%s" data-tab="p%d_%d">%s</div>' % (
                    self.cls(p, 'tab', 'active' if i == first else ''), n, i, esc(p.get('title') or p.get('name'))))
                for i, p in enumerate(pages))
        bodies = []
        for i, p in enumerate(pages):
            # Without a tab strip the page itself is the framed/jump target.
            classes = self.cls(p, 'page', self.layout(p), 'active' if i == first else '') if not tabs else \
                'page %s%s' % (self.layout(p), ' active' if i == first else '')
            body = '<div class="%s" data-page="p%d_%d">%s</div>' % (classes, n, i, self.children(p))
            bodies.append(self.with_mark(p, body) if not tabs else body)
        body = ''.join(bodies)
        return '<div class="%s">%s%s</div>' % (self.cls(item, 'pages'), tabs, body)

    def r_Page(self, item):
        return '<div class="%s">%s</div>' % (self.layout(item), self.children(item))

    def label(self, item):
        loc = item.get('title_location', 'Left')
        if loc == 'None' or not item.get('title'):
            return '', ''
        return '<label>%s%s</label>' % (esc(item['title']), ':' if loc in ('Left', 'Auto') else ''), \
            ('top' if loc == 'Top' else '')

    def r_InputField(self, item):
        label, pos = self.label(item)
        width = item.get('width')
        style = ' style="width:%dpx"' % max(60, min(520, width * 8 + 14)) if width and not item.get('stretch') else ''
        value = esc(self.value_for(item))
        if item.get('multiline'):
            inner = '<textarea rows="2">%s</textarea>' % value
        else:
            inner = '<input value="%s">' % value
        choices = next((self.data.get('choices', {})[k] for k in (item.get('name'), item.get('title'), item.get('path'))
                        if k and k in self.data.get('choices', {})), None)
        pick = ('<span class="pick list"%s></span>' % (' data-choices="%s"' % esc(json.dumps(choices, ensure_ascii=False))
                                                        if choices else '')) if item.get('choice') else ''
        box = '<div class="box%s"%s>%s%s</div>' % (' multi' if item.get('multiline') else '', style, inner, pick)
        right = item.get('title_location') == 'Right'
        return '<div class="%s">%s</div>' % (self.cls(item, 'fld', pos, 'stretch' if item.get('stretch') else ''),
                                             (box + label) if right else (label + box))

    def r_LabelField(self, item):
        label, pos = self.label(item)
        value = self.value_for(item)
        value = '<span class="%s">%s</span>' % ('link' if item.get('hyperlink') else 'value', esc(value or ('…' if item.get('hyperlink') else '')))
        return '<div class="%s">%s%s</div>' % (self.cls(item, 'fld', pos), label, value)

    def r_CheckBoxField(self, item):
        checked = ' checked' if self.value_for(item) in (True, 'true', 'Да', 'да', 1) else ''
        title = esc(item.get('title')) if item.get('title_location') != 'None' else ''
        box = '<input type="checkbox"%s>' % checked
        inner = (title + box) if item.get('title_location') == 'Left' else (box + title)
        return '<label class="%s">%s</label>' % (self.cls(item, 'chk'), inner)

    def r_RadioButtonField(self, item):
        self.counter += 1
        label, pos = self.label(item)
        opts = ''.join('<label class="chk"><input type="radio" name="r%d"%s>%s</label>' % (
            self.counter, ' checked' if i == 0 else '', esc(o)) for i, o in enumerate(item.get('options') or []))
        return '<div class="%s">%s<span class="radio">%s</span></div>' % (self.cls(item, 'fld', pos), label, opts)

    def r_LabelDecoration(self, item):
        return '<span class="%s">%s</span>' % (self.cls(item, 'link' if item.get('hyperlink') else 'value'), esc(item.get('title')))

    def r_PictureDecoration(self, item):
        return '<span class="%s" title="%s"></span>' % (self.cls(item, 'pic'), esc(item.get('title')))

    r_PictureField = r_PictureDecoration

    def button(self, item, in_bar=False):
        title = item.get('title') or item.get('name')
        rep = item.get('representation')
        kind = item.get('button_type', '')
        if kind in ('Hyperlink', 'CommandBarHyperlink'):
            return '<span class="%s" data-title="%s">%s</span>' % (self.cls(item, 'link'), esc(title), esc(title))
        pic = icon(title) if rep == 'Picture' else None
        classes = self.cls(item, 'btn', 'primary' if item.get('default') else '', 'pic' if pic else '')
        label = pic or esc(title)
        return '<span class="%s" title="%s" data-title="%s">%s</span>' % (classes, esc(title), esc(title), label)

    def r_Button(self, item):
        return self.button(item)

    def r_Popup(self, item):
        entries = []

        def collect(nodes):
            for n in nodes:
                if not self.visible(n):
                    continue
                if n['type'] in ('ButtonGroup', 'Popup') and n.get('items'):
                    collect(n['items'])
                elif n.get('title'):
                    entries.append('<div class="%s">%s</div>' % (self.cls(n), esc(n['title'])))
        collect(item.get('items', []))
        menu = '<div class="menu">%s</div>' % (''.join(entries) or '<div>…</div>')
        pic = icon(item.get('title')) if item.get('representation') == 'Picture' else None
        label = pic or esc(item.get('title'))
        return '<span class="%s" title="%s">%s%s</span>' % (self.cls(item, 'btn', 'primary' if item.get('default') else '',
                                                           'has-menu', 'caret', 'pic' if pic else ''),
                                                           esc(item.get('title')), label, menu)

    def r_ButtonGroup(self, item):
        return self.children(item)

    def r_CommandBar(self, item):
        return '<div class="%s">%s</div>' % (self.cls(item, 'bar'), self.children(item))

    r_AutoCommandBar = r_CommandBar

    def columns(self, cols, group=None):
        flat = []
        for c in cols:
            if not self.visible(c):
                continue
            if c['type'] == 'ColumnGroup':
                inner = self.columns(c.get('items', []), c)
                if c.get('group') == 'InCell' and inner:
                    # several fields in one cell: one column titled by the group
                    first = dict(inner[0])
                    first['title'] = c.get('title') or ' / '.join(i['title'] for i in inner if i.get('title'))
                    first['new'] = first.get('new') or c.get('new')
                    flat.append(first)
                else:
                    flat.extend(inner)
            else:
                flat.append(c)
        return flat

    def r_Table(self, item):
        cols = self.columns(item.get('columns', []))
        rows = self.table_rows(item, cols)
        bar = ''
        commands = [c for c in item.get('commands', []) if self.visible(c)]
        if commands or item.get('search'):
            search = '<span class="box" style="margin-left:auto;width:200px"><input placeholder="Поиск (Ctrl+F)"></span>' \
                if item.get('search') else ''
            bar = '<div class="bar">%s%s</div>' % (''.join(self.render(c) for c in commands), search)
        head = ''
        if item.get('header', True):
            head = '<thead><tr>%s</tr></thead>' % ''.join(
                self.with_mark(c, '<th class="%s">%s</th>' % (
                    self.cls(c), esc(c.get('title') if c.get('title_location') != 'None' or c.get('title') else '')))
                for c in cols)
        body = ''.join('<tr%s>%s</tr>' % (' class="sel"' if i == 0 else '', ''.join(
            '<td class="%s">%s</td>' % (self.cls(c, 'num' if is_num(v) else ''), self.cell(c, v)) for c, v in zip(cols, row)))
            for i, row in enumerate(rows))
        return '<div class="%s">%s<div class="tblwrap"><table class="t">%s<tbody>%s</tbody></table></div></div>' % (
            self.cls(item, 'v', 'stretch'), bar, head, body)

    def cell(self, col, value):
        if col['type'] == 'CheckBoxField':
            return '<input type="checkbox"%s>' % (' checked' if value in (True, 'true', 'Да', 1) else '')
        return esc(value)

    def table_rows(self, item, cols):
        tables = self.data.get('tables', {})
        rows = None
        for key in (item.get('name'), item.get('title'), item.get('path')):
            if key and key in tables:
                rows = tables[key]
                break
        if rows is None:
            rows = item.get('rows')
        if not rows:
            return [[''] * len(cols) for _ in range(3)]
        out = []
        for row in rows:
            if isinstance(row, dict):
                out.append([next((row[k] for k in (c.get('name'), c.get('title'), c.get('path')) if k and k in row), '')
                            for c in cols])
            else:
                out.append(list(row) + [''] * (len(cols) - len(row)))
        return out

    def r_unknown(self, item):
        return '<div class="%s">%s</div>' % (self.cls(item, 'doc'), esc(item.get('title') or item['type']))

    def page(self, shell=True, snapshot=False):
        """The mockup page; snapshot=True is the copy for the PNG picture: all frames on whatever their count."""
        f = self.form
        # every framed element is listed; without a note it gets a plain description of what it is
        noted = [(i, i.get('note') or default_note(i, par))
                 for i, par in walk_items(f.get('command_bar', []) + f.get('items', [])) if i.get('new')] if self.frames else []
        many = len(noted) > FRAME_LIMIT
        self.highlight = 'none (new form)' if not self.frames else 'on click' if many else 'frames'
        self.marks = {id(i): k for k, (i, _) in enumerate(noted, 1)}
        self.notes = {id(i): n for i, n in noted}
        legend = ('<label class="legend"><input type="checkbox" id="showNew"%s><i></i>Изменения</label>'
                  % ('' if many and not snapshot else ' checked')) if noted else ''
        hint = 'рамки скрыты: нажмите пункт — покажу на форме' if many else 'нажмите пункт — покажу на форме'
        changes = ('<div class="changes"><b>Что меняется</b> <span class="hint">(%s)</span><ol>%s</ol></div>'
                   % (hint, ''.join('<li data-goto="%d"><b>%s</b> — %s</li>' % (k, esc(i.get('title') or i.get('name')), esc(n))
                                    for k, (i, n) in enumerate(noted, 1)))) if noted else ''
        bar = ''.join(self.render(c) for c in f.get('command_bar', []))
        body = '<div class="v">%s</div>' % ''.join(self.render(i) for i in f.get('items', []))
        nav = ''
        if f.get('nav'):
            nav = '<div class="fnav">%s</div>' % ''.join(
                '<span class="%s">%s</span>' % ('active' if i == 0 else 'link', esc(n)) for i, n in enumerate(f['nav']))
        form_html = ('<div class="form"><div class="ftitle"><span class="nav">←</span><span class="nav">→</span>'
                     '<span style="color:#bbb">☆</span><h1>%s</h1>%s</div>%s%s<div class="fmain"><div class="bar">%s</div>%s</div>'
                     '<div class="fsec"><div class="bar"><span class="btn" data-title="Создать">Создать</span>'
                     '<span class="box" style="margin-left:auto;width:200px"><input placeholder="Поиск (Ctrl+F)"></span></div>'
                     '<div class="tblwrap"><table class="t"><thead><tr><th>Наименование</th><th>Дата</th><th>Автор</th></tr></thead>'
                     '<tbody><tr><td colspan="3" class="empty">Связанный список «<span class="sname"></span>» — в макете не детализирован'
                     '</td></tr></tbody></table></div></div></div>') % (
            esc(f.get('title')), legend, changes, nav, bar, body)
        if shell:
            section = f.get('section') or 'Главное'
            side = ''.join('<div class="%s">%s</div>' % ('active' if s == section else '', esc(s)) for s in (f.get('sections') or [section]))
            form_html = ('<header class="apphead"><span class="logo">1С</span><span class="product">%s</span></header>'
                         '<div class="shell"><nav class="side">%s</nav><main class="work"><div class="wtabs">'
                         '<span>Начальная страница</span><span class="active">%s</span></div>%s</main></div>') % (
                esc(f.get('product') or '1С:Предприятие'),
                side, esc(f.get('title')), form_html)
        note = esc('Макет-предложение, не согласован. Источник: %s' % f.get('source', ''))
        script = JS
        if snapshot:   # the whole form must fit the picture: headless Chrome reads this height first (screenshot())
            script += ("var f=document.querySelector('.form');document.body.setAttribute('data-height',"
                       "Math.ceil(f.getBoundingClientRect().top+window.scrollY+f.scrollHeight));")
        return ('<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" '
                'content="width=device-width,initial-scale=1"><title>%s — макет</title><style>%s</style></head>'
                '<body%s><!-- %s -->%s<div class="toast"></div><script>%s</script></body></html>') % (
            esc(f.get('title')), CSS, (' class="many"' if snapshot else ' class="plain many"') if many else '',
            note, form_html, script)


# ---------------------------------------------------------------- visibility profiles

PROFILE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'references', 'profiles')


def clean_title(title):
    """«Товары (1)» -> «Товары», «Статус:» -> «Статус»; English UI words of the web client map to 1C ones."""
    t = re.sub(r'\s*\(\d+\)$', '', (title or '').strip()).rstrip(':').strip()
    return {'#': 'N', 'Number': 'Номер', 'Date': 'Дата', 'Add': 'Добавить', 'Generate': 'Создать на основании',
            'Main': 'Основное', 'More actions': 'Еще', 'Save': 'Записать', 'Save and close': 'Записать и закрыть',
            'Post': 'Провести', 'Post and close': 'Провести и закрыть'}.get(t, t)


def configuration_id(value):
    """Portable scope key, not a product name or a preset of a customer."""
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', value):
        raise ValueError('configuration must be a 1..64 character identifier (letters, digits, _ or -)')
    return value.casefold()


def profile_name(form):
    """Every profile belongs to a configuration, including the default scope."""
    scope = configuration_id(form.get('configuration', 'default'))
    owner, name = form.get('owner') or 'Form', form.get('form') or 'Form'
    for part in (owner, name):
        if any(c in part for c in '/\\\x00<>:"|?*') or part in ('.', '..'):
            raise ValueError('Invalid form/profile identity')
    return '%s.%s.%s.json' % (scope, owner, name)


def profiles_root(form):
    """Workspace-local by default; independent of the skill installation directory."""
    if form.get('profiles_dir'):
        return os.path.abspath(form['profiles_dir'])
    src = form.get('source_root') or default_src()
    return os.path.join(os.path.dirname(os.path.abspath(src)), '.1c-form-mockup', 'profiles')


def profile_path(form):
    name = profile_name(form)
    for folder in (profiles_root(form), PROFILE_DIR):
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            return path
    return None


def walk_items(items, parents=()):
    for item in items:
        yield item, parents
        for key in ('items', 'columns', 'commands'):
            yield from walk_items(item.get(key, []), parents + (item,))


def flat_columns(table):
    cols = []
    for col in table.get('columns', []):
        cols.extend(col.get('items', []) if col['type'] == 'ColumnGroup' and col.get('group') != 'InCell' else [col])
    return cols


def norm_title(title):
    return re.sub(r'\s+', ' ', re.sub(r'[^\w\s%]', ' ', (title or '').lower().replace('ё', 'е'))).strip()


def match_title(seen, titles):
    """The XML title a title read from the live form (or a screenshot) stands for: exact,
    then ignoring case/punctuation/ё, then a cut header («Номенкл…»), then a close spelling."""
    titles = [t for t in titles if t]
    if seen in titles:
        return seen
    cut = seen.rstrip().endswith(('…', '...'))
    n = norm_title(seen)
    if not n:
        return None
    normed = {norm_title(t): t for t in titles}
    if n in normed:
        return normed[n]
    if cut:   # the rest of a cut header is unknown: only its start can be compared
        return next((t for k, t in normed.items() if k.startswith(n)), None)
    close = difflib.get_close_matches(n, list(normed), n=1, cutoff=0.85)
    return normed[close[0]] if close else None


def table_entry(value):
    """A profile table is a list of column titles, or {"columns": [...], "cut": true} when the
    screenshot cuts the table at the right edge: columns not seen may be further right, so
    none is hidden."""
    if isinstance(value, dict):
        return list(value.get('columns', [])), bool(value.get('cut'))
    return list(value), False


def find_table(form, name, live_cols=()):
    """Table by name or title; else the one sharing most column titles with the live table
    (the name in a profile is often the tab title, not the XML table name)."""
    tables = [i for i, _ in walk_items(form['items']) if i['type'] == 'Table']
    exact = next((t for t in tables if name in (t.get('name'), t.get('title'))), None)
    if exact is not None:
        return exact
    want = [clean_title(c) for c in live_cols if not c.startswith('[')]
    score = lambda t: sum(1 for c in want if match_title(c, [x.get('title') for x in flat_columns(t)]))
    best = max(tables, key=score, default=None)
    return best if best is not None and score(best) >= max(1, min(3, len(flat_columns(best)))) else None


def outline(form):
    """What the XML form has, by title: for comparing with a screenshot before writing a profile."""
    out = {'form': '%s.%s' % (form.get('owner'), form.get('form')), 'title': form.get('title'), 'tabs': [],
           'buttons': [i.get('title') for i, _ in walk_items(form.get('command_bar', [])) if i.get('title')],
           'tables': {}}
    for item, _ in walk_items(form['items']):
        if item['type'] == 'Pages':
            out['tabs'].append([p.get('title') for p in item.get('items', [])])
        elif item['type'] == 'Table':
            out['tables'][item.get('name')] = {
                'columns': [c.get('title') for c in flat_columns(item)],
                'buttons': [c.get('title') for c, _ in walk_items(item.get('commands', [])) if c.get('title')]}
    return out


def reveal_profile_item(form, item, report):
    """An observed element overrides XML visibility, including hidden containers."""
    for node, parents in walk_items(form.get('command_bar', []) + form['items']):
        if node is item:
            for ancestor in parents + (node,):
                if not ancestor.get('visible', True):
                    ancestor['visible'] = True
                    report.setdefault('restored', []).append(ancestor.get('title') or ancestor.get('name'))
            break


def order_profile_items(original, observed):
    """Observed order, then unseen XML items; proposals stay after their old neighbour."""
    seen = {id(i) for i in observed}
    ordered = [i for i in observed if not i.get('new')]
    ordered.extend(i for i in original if id(i) not in seen and not i.get('new'))
    for index, item in enumerate(original):
        if item.get('new'):
            previous = next((p for p in reversed(original[:index]) if any(p is x for x in ordered)), None)
            at = next((j + 1 for j, x in enumerate(ordered) if x is previous), 0)
            ordered.insert(at, item)
    return ordered


def apply_button_profile(form, commands, live, report, hide, label, other_titles=()):
    """Match nested commands without flattening menus, restore visibility and order the bar."""
    specs = [(clean_title(b.lstrip('*')), b.startswith('*')) for b in live if not b.startswith('[')]
    specs = [(title, default) for title, default in specs if title != 'Еще']
    if not specs:
        return commands
    original = list(commands)
    candidates = list(walk_items(commands))
    observed, matched = [], set()
    has_default = any(default for _, default in specs)
    if has_default:
        for node, _ in candidates:
            node['default'] = False
    for title, default in specs:
        found = match_title(title, [i.get('title') for i, _ in candidates if id(i) not in matched])
        if found is not None:
            node, parents = next((i, p) for i, p in candidates if i.get('title') == found and id(i) not in matched)
            matched.add(id(node))
            reveal_profile_item(form, node, report)
            if has_default:
                node['default'] = default
            top = parents[0] if parents else node
        elif match_title(title, other_titles) is not None:
            continue
        else:
            top = {'type': 'Button', 'name': 'live_' + title, 'title': title,
                   'button_type': 'CommandBarButton', 'from_live': True, 'default': default}
            commands.append(top)
            original.append(top)
            report['added'].append('%s «%s»' % (label, title))
        if not any(top is item for item in observed):
            observed.append(top)
    for item in commands:
        protected = any(node.get('new') or node.get('representation') == 'Picture'
                        for node, _ in walk_items([item]))
        if (hide and (item.get('title') or item['type'] == 'ButtonGroup') and not any(item is node for node in observed)
                and item.get('visible', True) and not protected):
            item['visible'] = False
            report['hidden'].append('%s «%s»' % (label, item.get('title') or item.get('name')))
        # ButtonGroup draws inline, unlike a Popup whose menu entries were not captured.
        # Apply the observed order/hiding inside it too, keeping the group structure.
        if item['type'] == 'ButtonGroup':
            titles = [node.get('title') for node, _ in walk_items(item.get('items', []))]
            group_live = [b for b in live if match_title(clean_title(b.lstrip('*')), titles) is not None]
            if group_live:
                item['items'] = apply_button_profile(form, item['items'], group_live, report, hide, label)
    return order_profile_items(original, observed)


def apply_profile(form, profile):
    """Make the XML form look like the live one: what 1C shows at run time and what newer
    releases/extensions added. A profile lists the titles seen in the web client or on a
    screenshot; titles are matched loosely (see match_title).

    Returns a report of what was hidden and added, for the agent's answer.
    """
    report = {'hidden': [], 'added': []}
    # "cut": true — a screenshot shows only part of the tab strip / command bars: nothing there is hidden
    hide = not profile.get('cut')
    # tabs: the Pages item whose pages overlap the profile most
    tabs = [clean_title(t) for t in profile.get('tabs', [])]
    pages_items = [i for i, _ in walk_items(form['items']) if i['type'] == 'Pages']
    page_titles = lambda p: [x.get('title') for x in p.get('items', [])]
    hits = lambda p: sum(1 for t in tabs if match_title(t, page_titles(p)))
    main_pages = max(pages_items, key=hits, default=None)
    if main_pages is not None and tabs and hits(main_pages):
        titles = page_titles(main_pages)
        matched = {match_title(t, titles) for t in tabs}
        for page in main_pages['items']:
            if page.get('title') in matched:
                reveal_profile_item(form, page, report)
            elif hide and page.get('visible', True) and not page.get('new'):
                page['visible'] = False
                report['hidden'].append('вкладка «%s»' % page.get('title'))
        for t in tabs:
            if match_title(t, titles) is None:
                main_pages['items'].append({'type': 'Page', 'name': 'live_' + t, 'title': t, 'group': 'Vertical',
                                            'from_live': True, 'items': [{'type': 'LabelDecoration', 'name': 'live_note',
                                            'title': 'Вкладка есть в базе, но её нет в выгрузке XML (src/).'}]})
                report['added'].append('вкладка «%s»' % t)
        # live order: seen tabs as on the screen, the rest after them as in the XML
        rank = {match_title(t, page_titles(main_pages)): i for i, t in enumerate(tabs)}
        main_pages['items'].sort(key=lambda p: rank.get(p.get('title'), len(rank)))
    # table columns: live order; XML columns not seen are hidden, live-only ones added
    for name, value in profile.get('tables', {}).items():
        live_cols, cut = table_entry(value)
        table = find_table(form, name, live_cols)
        if table is None:
            continue
        reveal_profile_item(form, table, report)
        all_cols = flat_columns(table)
        xml_cols = [c for c in all_cols if not c.get('new')]   # mockup additions keep their place
        free = list(xml_cols)
        ordered = []
        for t in (clean_title(c) for c in live_cols if not c.startswith('[')):
            title = match_title(t, [c.get('title') for c in free])
            if title is not None:
                col = next(c for c in free if c.get('title') == title)
                reveal_profile_item(form, col, report)
                free.remove(col)
                ordered.append(col)
            else:
                ordered.append({'type': 'InputField', 'name': 'live_' + t, 'title': t, 'from_live': True})
                report['added'].append('колонка «%s»' % t)
        for col in free:
            if col.get('visible', True) and not cut:
                col['visible'] = False
                report['hidden'].append('колонка «%s»' % col.get('title'))
            ordered.append(col)
        for i, col in enumerate(all_cols):
            if col.get('new'):
                ordered.insert(ordered.index(all_cols[i - 1]) + 1 if i else 0, col)
        table['columns'] = ordered
    # command bar buttons
    body_titles = [i.get('title') for i, _ in walk_items(form['items']) if i['type'] in ('Button', 'Popup')]
    form['command_bar'] = apply_button_profile(form, form.setdefault('command_bar', []),
        profile.get('buttons', []), report, hide, 'кнопка', body_titles)
    # table command bars: same idea, per table
    for name, live in profile.get('table_buttons', {}).items():
        table = find_table(form, name, table_entry(profile.get('tables', {}).get(name, []))[0])
        if table is None:
            continue
        table['commands'] = apply_button_profile(form, table.setdefault('commands', []),
            live, report, hide, 'кнопка таблицы')
    if profile.get('nav'):
        form['nav'] = [clean_title(n) for n in profile['nav']]
    form['profile_report'] = report
    return report


def locate(items, pred, parents=()):
    """(list holding the item, index, item, parents) for every item matching pred."""
    for i, item in enumerate(items):
        if pred(item):
            yield items, i, item, parents
        for key in ('items', 'columns', 'commands'):
            yield from locate(item.get(key, []), pred, parents + (item,))


def shown(item, parents):
    return all(x.get('visible', True) for x in parents + (item,))


NEW_TYPES = {'column': 'InputField', 'field': 'InputField', 'checkbox': 'CheckBoxField',
             'button': 'Button', 'tab': 'Page'}


def add_item(form, kind, title, after=None, table=None, choice=False, note=None):
    """Put a new mockup element next to an existing one; returns where it went (for the answer).
    Raises ValueError (with close titles) when the anchor or the table is not found."""
    item = {'type': NEW_TYPES[kind], 'name': 'new_' + re.sub(r'\W', '', title), 'title': title, 'new': True}
    if choice:
        item['choice'] = True   # a reference or list field: the ▾ pick button
    if note:
        item['note'] = note
    if kind == 'checkbox':
        item['title_location'] = 'Right'
    elif kind == 'button':
        item['button_type'] = 'CommandBarButton'
    elif kind == 'tab':
        item.update(group='Vertical', items=[])
    target = None
    if kind == 'column' or (kind == 'button' and table):
        tables = [(t, par) for t, par in walk_items(form['items']) if t['type'] == 'Table']
        if table:
            target = find_table(form, table)
            if target is None:
                raise ValueError('table «%s» not found; tables: %s' % (table, ', '.join(t.get('name') for t, _ in tables)))
        else:
            visible = [t for t, par in tables if shown(t, par)]
            if len(visible) != 1:
                raise ValueError('pass --table, the form has tables: ' + ', '.join(t.get('name') for t in visible))
            target = visible[0]
    if kind == 'column':
        scope, types = target['columns'], ('InputField', 'LabelField', 'CheckBoxField', 'PictureField', 'ColumnGroup')
    elif kind == 'button':
        scope = target.setdefault('commands', []) if target else form.setdefault('command_bar', [])
        types = ('Button', 'Popup')
    elif kind == 'tab':
        pages = [p for p, par in walk_items(form['items']) if p['type'] == 'Pages' and shown(p, par)]
        if not pages:
            raise ValueError('the form has no tabs')
        scope, types = pages[0]['items'], ('Page',)
    else:
        if not after:
            raise ValueError('--after is required for a field or checkbox: the title of the element it goes after')
        scope, types = form['items'], ('InputField', 'LabelField', 'CheckBoxField', 'RadioButtonField',
                                       'LabelDecoration', 'Button', 'Table')
    if not after:
        scope.append(item)
        return {'added': title, 'in': (target or {}).get('title') or ('вкладки' if kind == 'tab' else 'командная панель')}
    hits = list(locate(scope, lambda x: x['type'] in types and x.get('title')
                       and match_title(after, [x['title']]) is not None))
    if not hits:
        titles = sorted({x.get('title') for x, _ in walk_items(scope) if x.get('title')})
        near = difflib.get_close_matches(after, titles, n=5, cutoff=0.5)
        raise ValueError('«%s» not found%s' % (after, '; close titles: ' + ', '.join(near) if near else ''))
    holder, i, anchor, parents = sorted(hits, key=lambda h: not shown(h[2], h[3]))[0]   # a visible one first
    holder.insert(i + 1, item)
    # what the user sees around it: tabs and titled groups (not internal group names)
    where = [x.get('title') for x in parents if x.get('title') and (x['type'] == 'Page' or x.get('show_title'))]
    if target is not None:
        where.append(target.get('title') or target.get('name'))
    return {'added': title, 'after': anchor.get('title'), 'in': ' / '.join(dict.fromkeys(where))}


def mark_item(form, title, note=None, table=None):
    """Frame an existing element whose behaviour changes (a restriction, autofill, a check) and
    attach the note shown in the «Что меняется» list. Returns where it is."""
    if table:
        target = find_table(form, table)
        if target is None:
            raise ValueError('table «%s» not found' % table)
        scope = target.get('columns', []) + target.get('commands', [])
    else:
        target = None
        scope = form.get('command_bar', []) + form['items']
    hits = list(locate(scope, lambda x: x['type'] not in ('Pages', 'ContextMenu') and x.get('title')
                       and match_title(title, [x['title']]) is not None))
    if not hits:
        titles = sorted({x.get('title') for x, _ in walk_items(scope) if x.get('title')})
        near = difflib.get_close_matches(title, titles, n=5, cutoff=0.5)
        raise ValueError('«%s» not found%s' % (title, '; close titles: ' + ', '.join(near) if near else ''))
    _, _, item, parents = sorted(hits, key=lambda h: not shown(h[2], h[3]))[0]
    item['new'] = True
    item['changed'] = True   # an existing element: «поведение меняется» unless a note says more
    if note:
        item['note'] = note
    where = [x.get('title') for x in parents if x.get('title') and (x['type'] == 'Page' or x.get('show_title'))]
    if target is not None:
        where.append(target.get('title') or target.get('name'))
    return {'marked': item.get('title'), 'in': ' / '.join(dict.fromkeys(where)), 'visible': shown(item, parents)}


def default_note(item, parents):
    """«Что меняется» line for a framed element the agent gave no note."""
    if item.get('changed'):
        return 'поведение меняется'
    table = next((p for p in reversed(parents) if p['type'] == 'Table'), None)
    where = ' в таблице «%s»' % (table.get('title') or table.get('name')) if table else ''
    kind = {'CheckBoxField': 'новый флажок', 'Button': 'новая кнопка', 'Popup': 'новое меню', 'Page': 'новая вкладка',
            'Table': 'новая таблица', 'UsualGroup': 'новая группа'}.get(item['type'])
    if kind is None:
        kind = 'новая колонка' if table and item['type'] != 'Button' else 'новое поле'
    if item['type'] == 'Button' and table:
        kind = 'новая кнопка'
    return kind + where


def merge_profiles(profiles):
    """Join captures of several tabs of one form: lists keep the first-seen order."""
    out = {'source': '; '.join(dict.fromkeys(p.get('source', '') for p in profiles if p.get('source')))}
    for key in ('nav', 'tabs', 'buttons', 'labels'):
        out[key] = list(dict.fromkeys(x for p in profiles for x in p.get(key, [])))
    out['tables'], out['table_buttons'] = {}, {}
    for p in profiles:
        for name, value in p.get('tables', {}).items():
            cols, cut = table_entry(value)
            old, old_cut = table_entry(out['tables'].get(name, []))
            merged = list(dict.fromkeys(old + cols))
            out['tables'][name] = {'columns': merged, 'cut': True} if (cut and (old_cut or not old)) else merged
        for name, values in p.get('table_buttons', {}).items():
            out['table_buttons'][name] = list(dict.fromkeys(out['table_buttons'].get(name, []) + list(values)))
    return out


def is_num(value):
    return isinstance(value, (int, float)) or bool(re.fullmatch(r'-?[\d\s ]+([.,]\d+)?', str(value or '').strip()))


# ---------------------------------------------------------------- CLI

def find_forms(src, obj, form=None):
    kind, _, name = obj.partition('.')
    folder = KIND_FOLDERS.get(kind, kind)
    base = os.path.join(src, folder, name, 'Forms') if folder != 'CommonForms' else os.path.join(src, 'CommonForms')
    if folder == 'CommonForms':
        path = os.path.join(src, 'CommonForms', name, 'Ext', 'Form.xml')
        return [path] if os.path.isfile(path) else []
    if not os.path.isdir(base):
        return []
    names = [form] if form else sorted(n for n in os.listdir(base) if os.path.isdir(os.path.join(base, n)))
    return [p for p in (os.path.join(base, n, 'Ext', 'Form.xml') for n in names) if os.path.isfile(p)]


def default_src():
    """Legacy find default is relative to the invoking workspace, never the harness."""
    return os.path.join(os.getcwd(), 'src')


ASK_SCREENSHOT = ('Для сходства с действующей формой «{title}» конфигурации {configuration} '
                  'нужен её скриншот или профиль видимости. Для широкой таблицы полезны несколько снимков. '
                  'Если нужен макет по XML без сверки с работающей базой, выберите --profile none; '
                  'такой результат может отличаться от действующей формы.')


def own_profile_path(form):
    return os.path.join(profiles_root(form), profile_name(form))


def resolve_profile(form, mode):
    """(path or None, stop answer or None). With auto and no profile the agent must ask first."""
    if mode == 'none':
        return None, None
    if mode != 'auto':
        return mode, None
    path = profile_path(form)
    if path:
        return path, None
    return None, {'need_screenshot': True, 'form': '%s.%s' % (form.get('owner'), form.get('form')),
                  'ask': ASK_SCREENSHOT.format(title=form.get('title') or form.get('form'),
                      configuration=form.get('configuration', 'default')),
                  'profile_to_write': own_profile_path(form).replace(os.sep, '/'),
                  'next': 'Use a profile for this configuration/form, or choose --profile none for an explicitly XML-based proposal.'}


def open_in_browser(path):
    try:
        if hasattr(os, 'startfile'):
            os.startfile(path)
            return True
        return webbrowser.open(file_link(path))
    except Exception:  # no desktop session: the link in the answer is enough
        return False


def find_chrome():
    """chrome.exe (or Chromium / Edge) for the PNG picture, or None. CHROME_PATH wins when set."""
    names = [os.environ.get('CHROME_PATH')]
    for base in (os.environ.get('PROGRAMFILES'), os.environ.get('PROGRAMFILES(X86)'), os.environ.get('LOCALAPPDATA')):
        if base:
            names += [os.path.join(base, 'Google', 'Chrome', 'Application', 'chrome.exe'),
                      os.path.join(base, 'Microsoft', 'Edge', 'Application', 'msedge.exe')]
    names += [shutil.which(n) for n in ('chrome', 'google-chrome', 'chromium', 'chromium-browser', 'msedge')]
    return next((n for n in names if n and os.path.isfile(n)), None)


PNG_WIDTH, PNG_HEIGHT = 1400, 1000


def screenshot(page, png, size=None, timeout=90):
    """Save a PNG of the HTML text page (a snapshot=True page) through headless Chrome; returns None or
    why it failed. Without size the picture is PNG_WIDTH wide and PNG_HEIGHT tall, taller when the form
    does not fit: a first run reads the height the page reports, so the whole form is always in.
    A private profile folder keeps a running Chrome of the user out."""
    chrome = find_chrome()
    if not chrome:
        return 'Chrome not found (set CHROME_PATH to chrome.exe)'
    os.makedirs(os.path.dirname(os.path.abspath(png)), exist_ok=True)
    with tempfile.TemporaryDirectory(dir=os.path.dirname(os.path.abspath(png))) as tmp:
        snap = os.path.join(tmp, 'snapshot.html')
        write(snap, page)
        candidate = os.path.join(tmp, 'candidate.png')
        base = [chrome, '--headless=new', '--disable-gpu', '--hide-scrollbars', '--no-first-run',
                '--no-default-browser-check', '--user-data-dir=' + os.path.join(tmp, 'profile'), '--virtual-time-budget=3000']
        try:
            if not size:
                dom = subprocess.run(base + ['--window-size=%d,1000' % PNG_WIDTH, '--dump-dom', file_link(snap)],
                                     capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
                if dom.returncode:
                    return 'Chrome height measurement failed (exit %s)' % dom.returncode
                height = re.search(r'data-height="(\d+)"', dom.stdout or '')
                if not height:
                    return 'Chrome did not report form height; choose --png-size explicitly'
                needed = max(int(height.group(1)) + 8, PNG_HEIGHT)
                if needed > 8000:
                    return 'Form exceeds the automatic 8000px height limit; choose --png-size explicitly'
                size = '%d,%d' % (PNG_WIDTH, needed)
            if not re.fullmatch(r'[1-9]\d{0,4},[1-9]\d{0,4}', size):
                return 'Invalid --png-size: expected positive width,height'
            run = subprocess.run(base + ['--window-size=' + size, '--screenshot=' + candidate, file_link(snap)],
                                 capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
            if run.returncode:
                return 'Chrome screenshot failed (exit %s): %s' % (run.returncode, (run.stderr or '')[-300:])
            if not os.path.isfile(candidate) or not Path(candidate).read_bytes().startswith(b'\x89PNG\r\n\x1a\n'):
                return 'Chrome did not produce a valid PNG file'
            os.replace(candidate, png)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return 'Chrome failed: %s' % exc
    return None


def png_paths(out, tabs):
    """One file per tab path; keep names unique after Windows sanitization, including case."""
    base = os.path.splitext(out)[0]
    names = [base + '.png']
    used = {names[0].casefold()}
    for path in tabs[1:]:
        title = ' — '.join(title or 'вкладка' for _, _, title in path)
        stem = '%s (%s)' % (base, re.sub(r'[\\/:*?"<>|]', '', clean_title(title)).strip() or 'вкладка')
        name, number = stem + '.png', 2
        while name.casefold() in used:
            name = '%s (%d).png' % (stem, number)
            number += 1
        used.add(name.casefold())
        names.append(name)
    return names


def file_link(path):
    return Path(path).resolve().as_uri()


def read_json(path):
    with open(path, encoding='utf-8-sig') as stream:
        return json.load(stream)


def inside_path(path, root):
    path, root = (os.path.normcase(os.path.realpath(p)) for p in (path, root))
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:
        return False


def check_output(path, form, inputs=()):
    output = os.path.normcase(os.path.realpath(path))
    if any(output == os.path.normcase(os.path.realpath(p)) for p in inputs if p):
        raise ValueError('Output must not overwrite an input file')
    if form.get('source_root') and inside_path(path, form['source_root']):
        raise ValueError('Write mockups outside the source XML dump')


def read_object(path, label):
    value = read_json(path)
    if not isinstance(value, dict):
        raise ValueError('%s must be a JSON object' % label)
    return value


def validate_form(form):
    if not isinstance(form, dict) or not isinstance(form.get('items'), list):
        raise ValueError('Form JSON must be an object with an items array')
    def visit(items, depth=0):
        if depth > 100 or not isinstance(items, list):
            raise ValueError('Form items must be arrays with nesting at most 100')
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get('type'), str) or not item['type']:
                raise ValueError('Every form item must have a nonempty string type')
            for key in ('items', 'columns', 'commands'):
                if key in item:
                    visit(item[key], depth + 1)
    visit(form['items'])
    visit(form.get('command_bar', []))
    return form


def write(path, content):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(content)
    return os.path.abspath(path)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('find', help='list Form.xml files of a metadata object')
    s.add_argument('--object', required=True, help='Документ.ЗаказКлиента, Справочник.Номенклатура, Document.X …')
    s.add_argument('--form')
    s.add_argument('--src', default=None)
    s = sub.add_parser('extract', help='Form.xml -> editable JSON')
    s.add_argument('--form', required=True)
    s.add_argument('--src', default=None, help='configuration dump root (otherwise inferred from the form path)')
    s.add_argument('--configuration', type=configuration_id, default='default', help='configuration scope identifier, e.g. demo-erp')
    s.add_argument('--out', required=True)
    s.add_argument('--profiles-dir', help='workspace profile folder (never inferred from the harness)')
    s.add_argument('--product', help='application title in the mockup shell')
    s.add_argument('--profile', default='auto', help='as for render; applied here so the JSON already has the live layout')
    s.add_argument('--new-form', action='store_true',
                   help='the form does not exist yet (this one is only its base): draw it clean, no frames and no change list')
    s = sub.add_parser('add', help='add a new (framed) column, field, checkbox, button or tab to the extracted JSON')
    s.add_argument('--json', required=True)
    s.add_argument('--kind', required=True, choices=sorted(NEW_TYPES))
    s.add_argument('--title', required=True, help='what the user will see')
    s.add_argument('--after', help='title of the existing element it goes after (required for field/checkbox)')
    s.add_argument('--table', help='table name or title, for a column or a table button')
    s.add_argument('--choice', action='store_true', help='a reference / list value (catalog, enum): draw the pick button')
    s.add_argument('--note', help='one line on what it does, shown in the «Что меняется» list')
    s = sub.add_parser('mark', help='frame an existing element whose behaviour changes, with a note')
    s.add_argument('--json', required=True)
    s.add_argument('--title', required=True, help='title of the existing element, as the user sees it')
    s.add_argument('--note', help='what changes, e.g. «список складов ограничен складами организации»')
    s.add_argument('--table', help='table name or title, to mark one of its columns or buttons')
    s = sub.add_parser('outline', help='titles of tabs, buttons and table columns in the XML (to compare with a screenshot)')
    s.add_argument('--form', required=True)
    s.add_argument('--src', default=None)
    s = sub.add_parser('merge-profile', help='join console captures (capture_profile.js) of several tabs into one profile')
    s.add_argument('inputs', nargs='+')
    s.add_argument('--out', required=True, help='<profiles-dir>/<configuration>.<Folder>.<Object>.<Form>.json')
    for name in ('render', 'build'):
        s = sub.add_parser(name)
        if name == 'render':
            s.add_argument('--json', required=True)
        else:
            s.add_argument('--form', required=True)
            s.add_argument('--src', default=None)
            s.add_argument('--configuration', type=configuration_id, default='default', help='configuration scope identifier, e.g. demo-erp')
            s.add_argument('--profiles-dir', help='workspace profile folder')
            s.add_argument('--product', help='application title in the mockup shell')
            s.add_argument('--json-out', help='also save the extracted JSON here')
            s.add_argument('--new-form', action='store_true', help='as for extract')
        s.add_argument('--data', help='JSON with sample values: {"fields": {...}, "tables": {"Товары": [...]}}')
        s.add_argument('--out', required=True)
        s.add_argument('--no-shell', action='store_true', help='form only, without the 1C application frame')
        s.add_argument('--show-hidden', action='store_true', help='also draw elements hidden in the XML (dashed)')
        s.add_argument('--profile', default='auto',
                       help='visibility profile JSON from the live base; auto = .1c-form-mockup/profiles/ or references/profiles/, '
                            'none = only the XML (when an XML-only proposal is intended)')
        s.add_argument('--open', action='store_true', help='open the result in the default browser')
        s.add_argument('--png', action='store_true',
                       help='also save pictures next to the HTML (<out>.png, one more per other tab with changes; '
                            'all frames on) through headless Chrome')
        s.add_argument('--png-size', help='width,height of the pictures in pixels (default: 1400x1000, taller when the form does not fit)')
    args = p.parse_args(argv)
    try:
        if args.cmd == 'find':
            forms = find_forms(args.src or default_src(), args.object, args.form)
            print(json.dumps({'forms': [f.replace('\\', '/') for f in forms]}, ensure_ascii=False, indent=1))
            return 0 if forms else 2
        if args.cmd == 'add':
            form = validate_form(read_json(args.json))
            check_output(args.json, form)
            result = add_item(form, args.kind, args.title, args.after, args.table, args.choice, args.note)
            write(args.json, json.dumps(form, ensure_ascii=False, indent=1))
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.cmd == 'mark':
            form = validate_form(read_json(args.json))
            check_output(args.json, form)
            result = mark_item(form, args.title, args.note, args.table)
            write(args.json, json.dumps(form, ensure_ascii=False, indent=1))
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.cmd == 'outline':
            print(json.dumps(outline(Extractor(args.form, args.src or None).extract()), ensure_ascii=False, indent=1))
            return 0
        if args.cmd == 'merge-profile':
            merged = merge_profiles([read_object(f, 'Profile') for f in args.inputs])
            print(json.dumps({'profile': write(args.out, json.dumps(merged, ensure_ascii=False, indent=1))}, ensure_ascii=False))
            return 0
        report = path = None
        if args.cmd in ('extract', 'build'):
            form = Extractor(args.form, args.src or None, args.configuration, args.profiles_dir).extract()
            check_output(args.out, form, [args.form])
            if args.product:
                form['product'] = args.product
            path, stop = resolve_profile(form, args.profile)
            if stop:
                print(json.dumps(stop, ensure_ascii=False, indent=1))
                return 3
            if path:
                report = apply_profile(form, read_object(path, 'Profile'))
                form['layout'] = 'profile ' + os.path.basename(path)
            else:
                form['profile_report'] = None   # «без скрина»: render must not apply one later
                form['layout'] = 'XML only (--profile none)'
            if args.new_form:
                form['new_form'] = True
            if args.cmd == 'extract':
                result = {'json': write(args.out, json.dumps(form, ensure_ascii=False, indent=1))}
                if path:
                    result.update(profile=os.path.basename(path), profile_report=report)
                print(json.dumps(result, ensure_ascii=False))
                return 0
            if args.json_out:
                check_output(args.json_out, form, [args.form, args.out])
                write(args.json_out, json.dumps(form, ensure_ascii=False, indent=1))
        else:
            form = validate_form(read_json(args.json))
            check_output(args.out, form, [args.json, args.data])
            if args.profile not in ('none', 'auto') or 'profile_report' not in form and args.profile != 'none':
                path = profile_path(form) if args.profile == 'auto' else args.profile
                if path:
                    report = apply_profile(form, read_object(path, 'Profile'))
                    form['layout'] = 'profile ' + os.path.basename(path)
        data = read_object(args.data, 'Sample data') if args.data else None
        if data and any(not isinstance(data.get(key, {}), dict) for key in ('fields', 'choices', 'tables')):
            raise ValueError('Sample fields, choices and tables must be JSON objects')
        renderer = Renderer(form, data, args.show_hidden)
        page = renderer.page(not args.no_shell)
        out = write(args.out, page)
        result = {'html': out, 'link': file_link(out),
                  'layout': form.get('layout') or 'XML only (extracted by an older version)',
                  'highlight': renderer.highlight}
        new = [i for i, _ in walk_items(form.get('command_bar', []) + form['items']) if i.get('new')]
        lost = [i.get('title') or i.get('name') for i in new if id(i) not in renderer.shown_new]
        if not new and not form.get('new_form'):   # a new form is entirely new: nothing has to be framed
            result['warning'] = 'no element with "new": true in the JSON - the requested change is not in the mockup'
        elif lost:
            result['warning'] = 'new elements not drawn (inside a hidden group or tab, or a wrong place): ' + ', '.join(lost)
        if report:
            result.update(profile=os.path.basename(path), profile_report=report)
        if args.png:   # one picture per tab with changes, each opened on its tab, all frames on
            tabs = renderer.change_tabs() or [[]]
            pngs = png_paths(out, tabs)
            for tab_path, png in zip(tabs, pngs):
                snap = Renderer(form, data, args.show_hidden)
                for pages, index, _ in tab_path:
                    snap.open_tab[id(pages)] = index
                failed = screenshot(snap.page(not args.no_shell, snapshot=True), png, args.png_size)
                if failed:   # the HTML mockup is done anyway; the document just goes without pictures
                    result['png_warning'] = failed
                    break
            else:
                result['png'] = pngs
        if args.open:
            result['opened'] = open_in_browser(out)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ET.ParseError, ValueError, KeyError, TypeError, AttributeError, IndexError) as exc:
        print(json.dumps({'error': '%s: %s' % (type(exc).__name__, exc)}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    sys.exit(main())
