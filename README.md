# 1C Layout Generator

Создаёт **интерактивные HTML-макеты управляемых форм1С** в стиле «Такси».
Можно показать новую колонку, кнопку, вкладку или предложить новую форму.
Готовый HTML работает локально, без сервера1С и внешних библиотек.

**Нужен только Python3.9+.** Для необязательных PNG — Chrome/Chromium/Edge.
Это визуальные предложения: бизнес-код1С не выполняется, конфигурация базы не меняется.

## Хочу просто пользоваться

**[Скачать переносимый пакет 1.1.0](https://github.com/KORUS-Consulting-GK-LLC/1CLayoutGenerator/raw/refs/heads/main/downloads/1c-form-mockup-1.1.0.zip)**
· [Инструкция для агента](skills/1c-form-mockup/AGENT-INSTALL.md)
· [Команды и примеры](skills/1c-form-mockup/references/usage.md)

Архив содержит весь skill, тесты, пример и проверку SHA256. Можно передать его
агенту вместе с таким сообщением:

> Установи `1c-form-mockup` из приложенного архива. Прочитай `AGENT-INSTALL.md`,
> сохрани мои настройки и проверь пример без открытия браузера и PNG.
> Сообщи путь установки и способ вызова.

В среде без загрузчика skills агент читает SKILL.md и использует обычный Python CLI.
MCP, ключи моделей и зависимости от конкретного проекта не нужны.

## Попробовать без установки

```text
git clone https://github.com/KORUS-Consulting-GK-LLC/1CLayoutGenerator.git
cd 1CLayoutGenerator
python layout.py demo
```

Откройте `mockups/example.html` вручную. В Windows вместо `python` при необходимости
используйте `py -3`. Браузер сам не открывается.

## Макет по своей форме

Нужна управляемая `Form.xml` в XML-выгрузке Конфигуратора. Путь к выгрузке —
пример; замените его своим. Не сохраняйте результат внутрь исходного dump.

```text
python layout.py find --src "D:/my-project/src" --object "Документ.ЗаказКлиента"
python layout.py extract --src "D:/my-project/src" --configuration my-project --form "D:/my-project/src/Documents/ЗаказКлиента/Forms/ФормаДокумента/Ext/Form.xml" --profile none --out mockups/order.json
python layout.py add --json mockups/order.json --kind column --table Товары --title "Скидка, %" --after Цена
python layout.py render --json mockups/order.json --out mockups/order.html
```

`--profile none` — предложение по XML. Для сходства с работающей базой используйте
профиль видимости из скриншотов: XML не знает функциональные опции и настройки
пользователя. Имена конфигураций разделяют профили, одинаковые формы не смешиваются.

Дополнительно: `--new-form`, `mark`, данные-примеры, `--no-shell`, `--png`, `--open`.
Необязательный PNG требует браузера; ошибки возвращаются как `png_warning`,
HTML при этом может быть готов. Изображение не заменяется при сбое браузера.

## Установить skill из клона

```text
python tools/install_skill.py --skills-dir "D:/my-project/.zcode/skills"
```

Для другой среды укажите её каталог skills. Например, пользовательский Codex
обычно использует `~/.codex/skills`; смотрите фактические настройки среды.
Установщик проверяет SHA и не перезаписывает отличающуюся/изменённую установку.
Само копирование не означает автоматическую загрузку: см. [инструкцию](skills/1c-form-mockup/AGENT-INSTALL.md).

## Проверки и сборка

```text
python skills/1c-form-mockup/scripts/verify_package.py skills/1c-form-mockup
python -m unittest discover -s skills/1c-form-mockup/tests -v
python -m unittest discover -s tests -v
python tools/build_package.py
```

Backend-тесты не открывают браузер. Тест настоящего Chrome включается только
отдельным выбором `FORM_MOCKUP_UI_TESTS=1`. В CI он выключен. ZIP и SHA появятся
в `dist/`. При разработке обновляйте manifest после ревью:
`python tools/build_package.py --refresh-manifest --out downloads`.

## Границы

- Поддержаны managed Form.xml и JSON-макеты; не EDT `.mdo`, обычные формы или
  произвольные печатные HTML-макеты.
- Макет не доказывает, что форма реализована, согласована или работает в базе.
- Шрифты, темы и версии клиента отличаются; точное пиксельное совпадение не обещается.
- Word/СППР и публикация документов подключаются отдельно.
- Операции PNG проверены через подмену процесса браузера; визуальная приёмка
  и реальные PNG этим не подтверждены.

[Итог повторного ревью](docs/REVIEW.md) · [Изменения версии](CHANGELOG.md)
· [Происхождение и авторство](skills/1c-form-mockup/NOTICE.md).
