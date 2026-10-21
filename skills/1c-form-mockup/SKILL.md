---
name: 1c-form-mockup
description: Create interactive HTML mockups of 1C managed forms from a Designer XML dump or editable form JSON. Use for proposed fields, columns, buttons, tabs and new form layouts in the Taxi style. Produces visual proposals, not executable 1C forms or metadata changes.
metadata:
  version: "1.1.0"
---

# 1C Form Mockup

`<skill-dir>` is the directory containing this file, wherever the harness loads
it. Execute `scripts/form_html.py` using Python 3; the engine uses the standard
library. Resolve paths from the supplied dump/workspace, never the installation
directory. No MCP, 1C installation, network service or particular model is needed.

## Inputs and boundaries

Choose the configuration before locating a form. Use `--src <dump>` and a scope
identifier such as `--configuration demo-erp` when multiple configurations are
available. Never substitute a same-named form from a different configuration.
Scope identifiers are case-insensitive ASCII letters, digits, `_` and `-`, up to
64 characters; product captions and metadata names may be Russian.

Input is **managed Form.xml in Designer XML format**, not EDT `.mdo`, ordinary
forms or print forms. Descriptors from the same dump supply field synonyms and
reference types. For a new form use a verified similar form or the synthetic JSON
example. Never apply mockup JSON to a live base or rewrite source XML. Put outputs
in the user's working directory.

## Workflow

1. Find/inspect the form with `find` and `outline` when its path is not known.
2. Extract editable JSON. For resemblance to a running form use a visibility
   profile derived from screenshots. Missing `--profile auto` returns exit3,
   `need_screenshot` and `profile_to_write`. Obtain a profile or choose
   `--profile none` for an explicitly XML-based proposal; runtime hiding and
   application code are not reproduced.
3. Add columns/fields/checkboxes/buttons/tabs with `add`. For behavior changes,
   `mark` existing elements with an explanatory `--note`. Complex rearrangements
   can edit JSON while preserving `new: true` on changed elements. Sample data
   illustrates behavior; it does not implement business logic.
4. Render HTML. `--open` and `--png` are optional; use them only within the user's
   request and the harness's permissions, not as implicit prerequisites.
5. Read the JSON result. A `warning` about absent/hidden changes needs correction
   or an explicit limitation. Return paths, changes, invented values, and whether
   the layout came from XML or an observed profile.

```text
python <skill-dir>/scripts/form_html.py find --src <dump> --object "Документ.ЗаказКлиента"
python <skill-dir>/scripts/form_html.py extract --src <dump> --configuration demo-erp --form <Form.xml> --profile none --out mockups/form.json
python <skill-dir>/scripts/form_html.py add --json mockups/form.json --kind column --table Товары --title "Скидка, %" --after Цена
python <skill-dir>/scripts/form_html.py render --json mockups/form.json --out mockups/form.html
```

For a new form use `extract --new-form` or `new_form: true` in synthetic JSON.
It is drawn clean, without change frames. Existing forms show up to five changes
with frames; for more changes frames appear on selection from the change list.
These are presentation modes, not approval states.

## Optional details

- Commands, sample data, profiles and exit codes: [references/usage.md](references/usage.md).
- XML elements and styling: [references/form-elements.md](references/form-elements.md).
- `--png` uses local Chrome/Chromium/Edge; `CHROME_PATH` selects the executable.
  It covers nested changed tab paths. Use the exact returned `png` paths.
  `png_warning` means HTML may be ready while images are not. No auto-install.
- `scripts/capture_profile.js` is a manual optional helper for an already
  authorized 1C web-client session, not part of HTML generation.
- Word/SPPR and publication commands belong to the consuming project. Deliver
  HTML/images to its adapter; this skill assumes none of those integrations.

Independent example: `assets/example.form.json` and `assets/example.data.json`.
Installation and verification: [README.md](README.md).
For agent-led installation in another harness: [AGENT-INSTALL.md](AGENT-INSTALL.md).
