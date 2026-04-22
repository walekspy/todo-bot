# Google Sheets Watch — Design Spec

## Goal

Поддержка наблюдения за Google Sheets с множеством вкладок. Для каждого листа — свой `reminder_lead_days`, настраиваемый пользователем.

## Модель данных

### Новая таблица `watched_sheets`

```sql
CREATE TABLE IF NOT EXISTS watched_sheets (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES watched_sources(id) ON DELETE CASCADE,
    sheet_name TEXT NOT NULL,
    reminder_lead_days INTEGER NOT NULL DEFAULT 3,
    enabled INTEGER NOT NULL DEFAULT 1
);
```

### Изменения в `WatchedSource`

`source_type` теперь может быть `"google_sheet"` (кроме `"google_doc"`).

## Флоу при `/watch`

1. Пользователь: `/watch` → бот просит ссылку
2. Бот определяет тип: `/document/d/` → google_doc (как раньше), `/spreadsheets/d/` → google_sheet
3. Для google_sheet:
   - Читает список листов через Google Sheets API (service account)
   - Отправляет названия листов в LLM → получает предложенные `reminder_lead_days`
   - Показывает список с кнопками ✏️ для каждого листа + кнопка ✅ Сохранить
   - По ✏️ — FSM спрашивает новое значение
   - По ✅ — сохраняет WatchedSource + WatchedSheet для каждого листа

## `/sources` — управление

Для google_sheet показывается дополнительная кнопка ⚙️ Настройки:
```
📄 google_sheet: https://docs.google.com/...
[ 🔍 Проверить ] [ ⚙️ Настройки ] [ 🗑 Удалить ]
```

По кнопке ⚙️ — список листов с текущими `reminder_lead_days` и кнопкой ✏️.

## Проверка документа (`doc_check_job`)

Для `google_sheet`:
1. Для каждого `enabled` листа → читает данные через Sheets API
2. Отправляет содержимое листа в LLM → получает события
3. Использует `reminder_lead_days` из настроек листа (игнорирует значение от LLM)
4. Если событие в пределах `reminder_lead_days` → алерт
5. В отчёте (ручная проверка) — группировка по листам

## Google Sheets API

Используется service account (`GDRIVE_SERVICE_ACCOUNT_JSON`). Документ должен быть расшарен на email service account.

Ключевые вызовы:
- `spreadsheets.get(spreadsheetId)` → список листов (properties.title)
- `spreadsheets.values.get(spreadsheetId, range=sheet_name)` → данные листа

## Файлы

- `bot/db/models.py` — добавить `WatchedSheet` dataclass
- `bot/db/database.py` — создать таблицу `watched_sheets`
- `bot/db/repository.py` — добавить `WatchedSheetRepo`
- `bot/adapters/google_sheet.py` — новый: чтение листов через Sheets API
- `bot/handlers/snooze_fsm.py` — FSM для настройки листов
- `bot/handlers/callbacks.py` — обработчики кнопок настройки
- `bot/handlers/commands.py` — обновить `/watch` для определения типа
- `bot/scheduler/jobs.py` — обновить `doc_check_job` для sheets
- `bot/config.py` — без изменений (service account уже есть)
