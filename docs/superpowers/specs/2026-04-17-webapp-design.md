# Telegram WebApp — Design Spec

## Goal

Веб-интерфейс для просмотра и управления задачами как дополнение к боту. Бот остаётся основным каналом напоминаний. WebApp открывается кнопкой прямо из Telegram.

## Контекст

- Текущий стек: Python, aiogram, aiosqlite, APScheduler, SQLite
- Целевые пользователи: сначала один пользователь, архитектура рассчитана на семейную группу
- Управление: полноценное (просмотр, добавление, редактирование, удаление, назначение)
- Аутентификация: Telegram WebApp `initData` (HMAC-SHA256 через BOT_TOKEN)
- Фронтенд: чистый HTML/JS, без фреймворков

---

## Архитектура

```
VPS
├── nginx (80/443)
│   ├── /api/  → FastAPI :8000
│   └── /      → статика WebApp (HTML/JS)
├── bot.service      — aiogram бот (polling)
└── webapp.service   — FastAPI сервер
         │
         └── читает тот же data/bot.db (SQLite, read-write)
```

FastAPI импортирует существующие `TaskRepo`, `UserRepo`, `Config` напрямую — код не дублируется.

Кнопка в боте: команда `/webapp` или инлайн-кнопка открывает `https://yourdomain.com` как Telegram WebApp.

---

## Структура файлов

```
webapp/
├── main.py          — FastAPI app, CORS, маршруты
├── auth.py          — проверка initData от Telegram
├── routers/
│   ├── tasks.py     — CRUD задач
│   └── users.py     — список пользователей (для назначения)
└── static/
    ├── index.html
    ├── app.js
    └── style.css
```

---

## API

Все endpoints требуют заголовок `X-Telegram-Init-Data` с валидным `initData`.

```
GET    /api/tasks          — список задач (фильтры: status, date)
POST   /api/tasks          — создать задачу
PATCH  /api/tasks/{id}     — обновить (статус, время, исполнитель)
DELETE /api/tasks/{id}     — удалить задачу
GET    /api/users          — список пользователей (для назначения)
```

Пример ответа `GET /api/tasks`:
```json
[
  {
    "id": "uuid",
    "title": "Купить молоко",
    "priority": "medium",
    "status": "pending",
    "remind_at": "2026-04-18T12:50:00+10:00",
    "assignee_id": 123456789,
    "is_family": false
  }
]
```

`PATCH` принимает только изменённые поля (частичное обновление).

---

## Фронтенд

Один HTML-файл, три вкладки: **Все задачи / Сегодня / Семейные**

```
[ Все задачи ]  [ Сегодня ]  [ Семейные ]

🔴 Купить молоко          18.04 12:50   [✅] [✏️] [🗑]
🟡 Позвонить врачу        19.04 09:00   [✅] [✏️] [🗑]

                              [+ Добавить задачу]
```

- `fetch` к `/api/tasks`, рендер списка
- Кнопки вызывают `PATCH`/`DELETE`
- Форма добавления — попап: название, дата/время, приоритет
- `telegram-web-app.js` подхватывает тему (тёмная/светлая) автоматически

---

## Локальная разработка

**DEV_MODE** (`DEV_MODE=true` в `.env`) — FastAPI пропускает проверку `initData`, использует фиксированный `user_id`. Тестируется в браузере как обычный сайт.

**ngrok** — для теста именно как Telegram WebApp:
```bash
ngrok http 8000
# даёт https://abc123.ngrok.io → Telegram открывает как WebApp
```

### Порядок разработки
1. Разрабатываем/тестируем локально через браузер (DEV_MODE)
2. Проверяем в Telegram через ngrok
3. Деплоим на VPS

---

## Деплой на VPS

_Будет уточнено позже._

- nginx как реверс-прокси (HTTP → HTTPS, Let's Encrypt)
- Два systemd-сервиса: `bot.service` и `webapp.service`
- Оба работают с одним файлом `data/bot.db`
