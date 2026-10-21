# Managed form XML → HTML: element map

How `scripts/form_html.py` reads `src/<Kind>/<Object>/Forms/<Form>/Ext/Form.xml` and draws
each element. The implementation covers the element families listed below.
Behaviour (events, code) is not modelled — only a visual proposal.

## Titles

1. `Title` of the element (Russian `v8:content`), formatting tags such as
   `<font …>`/`<b>` stripped.
2. Otherwise from `DataPath`:
   - `Объект.<Реквизит>` → synonym of the owner's attribute (`src/<Kind>/<Object>.xml`);
   - `Объект.<ТЧ>.<Реквизит>` → synonym inside the tabular section;
   - deeper paths follow the attribute type (`cfg:CatalogRef.Номенклатура` →
     `src/Catalogs/Номенклатура.xml`);
   - standard attributes: Number «Номер», Date «Дата», Code «Код», Description
     «Наименование», LineNumber «N», Posted «Проведен», Owner, Parent, Ref …;
   - a form attribute (`<Attributes>`) → its `Title`; a dynamic list (`Список.…`)
     resolves against its `MainTable`.
3. Buttons: `CommandName` → `Form.Command.X` title from `<Commands>`,
   `Form.StandardCommand.X` from the standard list (Записать, Провести и закрыть …),
   `CommonCommand.X` → synonym in `src/CommonCommands/X.xml`.
4. Last resort: the identifier split into words.

## Visibility

`<Visible>false</Visible>` → not drawn (`--show-hidden` draws it dashed), unless
the element is explicitly observed in a profile: that restores its visibility
and the necessary containers. The XML does not
know run-time hiding by functional options, user settings or code, and the live base can
be ahead of the `src/` dump. Profiles close the gap. The agent writes one from the
screenshot into `<profiles-dir>/<configuration>.<Folder>.<Object>.<Form>.json`.
By default the folder is `.1c-form-mockup/profiles/` beside the selected dump;
`extract/build --profiles-dir` overrides it. The configuration scope is always
part of the name, including `default`. This package ships no customer profiles.
An optional web-client capture helper is `scripts/capture_profile.js`; a user
may run it in their authorized browser session. The generator never connects
to the base. Profiles are applied at `extract`; items marked `"new"` are never
hidden or moved by them.

| Profile key | Effect |
|---|---|
| `nav` | navigation row above the form (Основное, Файлы, Задачи …) |
| `tabs` | pages of the main `Pages` put in the live order; not listed → hidden; listed but missing → added with a note |
| `buttons` | form command bar in profile order: observed buttons restored, unlisted hidden (icon-only ones kept), missing ones added; a `*` prefix sets the default button; proposals stay after their previous neighbour |
| `tables.<name>` | columns put in the live order; unlisted hidden, missing added; `[pic]` columns skipped. A table is found by name/title, else by the most shared column titles. `{"columns": [...], "cut": true}` — the screenshot cuts the table at the right edge: no column is hidden, unseen ones follow in XML order |
| `table_buttons.<name>` | the same for the table's command bar |
| `labels` | reference only |
| `cut` (top level) | the screenshot shows only part of the tab strip / command bars: tabs and buttons are added and matched but never hidden |

Titles match loosely: case, ё, punctuation, a cut header ending in «…», a close spelling
(«Срок поставки (раб. дни)» = «Срок поставки (дни)»). English words of the web client UI (`Main`, `Add`, `Generate`, `#`, `Number`, `Save and close` …)
map to the 1C titles. A profile can describe visible elements absent from an
older dump, but these are visual observations, not newly implemented metadata.

## Elements

| XML element | Properties used | HTML |
|---|---|---|
| `InputField` | `TitleLocation` (default Left; None, Top, Right), `ChoiceButton`/`DropListButton` or a reference type → pick button, `MultiLine`/`Height` → textarea, `Width` (chars) → px, `HorizontalStretch` | label + bordered box |
| `UsualGroup` | `Group` (Vertical default, Horizontal, AlwaysHorizontal, HorizontalIfPossible), `ShowTitle` (default true), `Representation` NormalSeparation → top rule, `Behavior` Collapsible → click to fold | flex column / row; title in bold |
| `Button` | `Type` (CommandBarButton, UsualButton, Hyperlink, CommandBarHyperlink), `DefaultButton` → yellow primary, `Representation` Picture → icon (standard ones: Записать, Провести, Создать на основании, Найти, Удалить, Печать …), unknown picture → its title | button or link; click shows «макет» toast |
| `LabelField` | `TitleLocation`, `Hyperlink` | label + value text / link |
| `ButtonGroup` | children | buttons inline |
| `AutoCommandBar` | `Autofill` (default true → standard commands of the object kind, minus `CommandSet/ExcludedCommand`), children | toolbar |
| `Page` | `Title`, `Group` | tab content |
| `CheckBoxField` | `TitleLocation` (default Right) | checkbox + text |
| `Popup` | `Title`, `Representation`, children (also nested groups) | button ▾ with a drop-down list |
| `LabelDecoration` | `Title` (formatted), `Hyperlink` | text / link |
| `Table` | columns from `ChildItems`, `Header`, `Representation` Tree, inner `AutoCommandBar` (Autofill → «Добавить»), `SearchStringAddition` → search box | toolbar + `<table>`; first row selected; sample rows from data |
| `ColumnGroup` | `Group` InCell → one column titled by the group; Horizontal/Vertical → its columns side by side | header cells |
| `Pages` | `PagesRepresentation` (TabsOnTop default; None → no tab strip, first page shown) | tab strip + pages |
| `PictureDecoration`, `PictureField` | — | small grey square |
| `CommandBar` | children | toolbar |
| `RadioButtonField` | choice list presentations | radio buttons |
| `SpreadSheetDocumentField`, `TextDocumentField`, `HTMLDocumentField`, `FormattedDocumentField`, `ChartField`, others | `Title` | dashed placeholder box with the title |
| `ContextMenu`, `ExtendedTooltip`, `SearchControlAddition`, `ViewStatusAddition` | — | not drawn |

## Form frame

Title: form `Title` or the owner's synonym. The page shows the 1C application frame
(yellow header, sections on the left, the open-form tab) like the web client; `--no-shell`
leaves only the form. The form command bar comes first, then `ChildItems` top to bottom.

## Style («Такси»)

Measured with computed styles in the 1C web client, platform 8.3.27
(15.10.2026 in the original implementation). These values approximate the
«Такси» look; theme, platform version, installed fonts and client can differ.

| Part | Value |
|---|---|
| Text | Almarai, Arial 13.33px; text `#4b4b4b`, labels `#4d4d4d`, values `#333` |
| Caption bar, sections panel | `#fbed9e`; active section white; caption 31px high, panel 173px wide |
| Open-form tabs | bar `#f2f2f2`, 31px; active white with a 2px green top line `#009646` |
| Command button | 27px high, padding 0 6px, radius 2px, white→`#f2f2f2`, border `rgba(0,0,0,.3)` (bottom .4), shadow `0 1px 0 rgba(0,0,0,.2)` |
| Default button | background `#ffe100`, bold, text `#333` |
| Input field | 25px high, white, radius 3px, `inset 0 0 0 1px #a0a0a0`; choice button 22px attached on the right |
| Hyperlink | `#1c55ae`, underlined |
| Page tabs | 28px, radius 3px 3px 0 0, border 1px `#b3b3b3`; inactive `#e6e6e6`, active white; strip line `#b3b3b3` |
| Table | header `#f2f2f2` 31px, cell lines `#ccc`; rows 29px, even rows `#fafafa`; selected row `#fef2c6` (`#facc1f` under 75% white); hover `#e6e6e6` |
| Focus, menu selection | `#facc1f` |
| Checkbox | border `#a0a0a0`, radius 2px; radio mark green `#009646` |

## Mockup changes

Items with `"new": true` get an orange frame (added ones via `form_html.py add`, existing
ones whose behaviour changes via `form_html.py mark`); their `"note"` lines form the
«Что меняется» list above the form; the page opens on the tab holding the
first change and scrolls tables to the first new column; a «Изменения» switch in the title bar
turns the frames off for a clean look.

How much is framed depends on the count (`FRAME_LIMIT` = 5 in `form_html.py`, team rule of
20.10.2026; `render` reports it as `highlight`):

| Case | Frames | «Что меняется» | «Изменения» switch |
|---|---|---|---|
| up to 5 changes (`frames`) | shown | shown | on |
| more than 5 (`on click`) | hidden (`body.plain many`); a clicked list item gets its own frame (`.picked`) and blinks | shown, always | off; turning it on shows all frames |
| new form, `"new_form": true` from `extract --new-form` (`none (new form)`) | none (`is-new` is not drawn) | none | none |

`render --png` saves pictures from a separate copy of the page (`Renderer.page(snapshot=True)`):
frames always on, «Изменения» checked, the change list shown; a new form stays clean. Changes
on several tabs (`Renderer.change_tabs()`) give one picture per changed tab path,
with every ancestor opened (`open_tab`); independent tab sets need no Cartesian product.
New forms include all visible page paths even without individual change marks.
Names are `<out>.png`, then `<out> (<tab path>).png` (`png_paths()`); duplicate sanitized
names get a numeric suffix. Use the exact names returned by render. The pictures
come from headless Chrome (`find_chrome()`: `CHROME_PATH`, the usual Chrome/Edge folders,
`PATH`) with a private temporary profile: a `--dump-dom` run reads the form height the snapshot
page writes into `body[data-height]`, then the screenshot is `PNG_WIDTH` × `PNG_HEIGHT`
(1400×1000), taller (up to 8000) when the form does not fit; `--png-size W,H` fixes the size instead.

Typical edits in the JSON:

```json
{"type": "InputField", "name": "ТоварыСпеццена", "title": "Спец цена клиента", "path": "Объект.Товары.Спеццена", "new": true}
{"type": "Button", "name": "Тест", "title": "Тест", "button_type": "CommandBarButton", "new": true}
{"type": "Page", "name": "СтраницаРезервы", "title": "Резервы", "group": "Vertical", "new": true, "items": []}
```
