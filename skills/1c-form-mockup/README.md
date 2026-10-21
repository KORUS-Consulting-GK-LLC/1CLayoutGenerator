# 1C Form Mockup — переносимый пакет 1.1.0

Интерактивные HTML-макеты управляемых форм1С в стиле «Такси». Выделен из ЛУИС;
профилей заказчика, выгрузки КА, доступов и обязательных проектных команд нет.

## Подключение

**Для установки силами агента:** передайте ему архив и
[AGENT-INSTALL.md](AGENT-INSTALL.md). В конце инструкции есть готовое поручение,
которое можно скопировать в чат другой среды.

Распакуйте каталог `1c-form-mockup` целиком, сохраняя структуру.

| Среда | Размещение |
|---|---|
| Codex | `~/.codex/skills/1c-form-mockup` |
| ZCode | `<проект>/.zcode/skills/1c-form-mockup` |
| Другой harness со SKILL.md | Его каталог skills; путь к skill определяет сама среда |
| Без загрузчика skills | Передать агенту SKILL.md и путь к scripts/form_html.py; CLI независим от harness |

Не заменяйте существующий skill с локальными правками вслепую. Переписывать код
под пути другой среды не нужно. `agents/openai.yaml` — необязательные для других
сред UI-метаданные, а не зависимость движка.

## Требования

- HTML: Python3.9+ и стандартная библиотека; pip-пакетов, Node.js, MCP и сервера1С не нужно.
- PNG: дополнительно локальный Chrome/Chromium/Edge, при необходимости `CHROME_PATH`.
- Просмотр интерактивного HTML: браузер с JavaScript.
- Входной XML — формат выгрузки Конфигуратора; EDT/обычные/печатные формы не поддержаны.

Backend локально проверен на Windows/Python3.13. Статус проверок Linux/macOS
смотрите в Actions репозитория. На macOS браузер при необходимости указывается
через CHROME_PATH. Настоящий браузер, PNG и визуальная приёмка автоматически
не проверялись.

## Быстрый запуск

Из своей рабочей папки; `<skill-dir>` — фактический путь к распакованному skill:

```text
python <skill-dir>/scripts/verify_package.py <skill-dir>
python <skill-dir>/scripts/form_html.py render --json <skill-dir>/assets/example.form.json --data <skill-dir>/assets/example.data.json --out mockups/example.html
python -m unittest discover -s <skill-dir>/tests -v
```

Команды проверяют SHA256, создают автономный HTML без открытия окна и запускают
backend-тесты. Настоящий браузер в тестах пропущен по умолчанию; opt-in только
через `FORM_MOCKUP_UI_TESTS=1`. `--open` и `--png` — отдельный выбор.

Использование: [SKILL.md](SKILL.md), [usage.md](references/usage.md).
Источник/отличия: [NOTICE.md](NOTICE.md), [ORIGIN.json](ORIGIN.json).
Состав: [MANIFEST.json](MANIFEST.json).
