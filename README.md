# Todo Bot — Telegram-бот для управления задачами с ИИ

Умный Telegram-бот для создания задач, напоминаний и синхронизации с Google Tasks.
Распознаёт задачи из свободного текста через LLM, поддерживает голосовой ввод
и работает в личных чатах и группах.

## Возможности

- **Свободный ввод** — пиши как думаешь: «купить молоко завтра в 10», «напомни через час позвонить врачу»
- **Голосовые сообщения** — надиктуй задачу, бот распознает через faster-whisper
- **Inline-кнопки** — подтверждение, откладывание, отметка выполнения без лишнего текста
- **Напоминания** — в указанное время с кнопками [Отложить] [В работу] [Готово]
- **Эскалация** — если задача отложена N раз, бот предлагает удалить
- **Google Tasks** — двусторонняя синхронизация
- **Google Docs** — слежение за документами, авто-извлечение задач
- **Семейные группы** — назначение задач на @username участников группы
- **Бэкапы** — авто-бэкап БД в Telegram или Google Drive
- **Per-user сессии** — у каждого пользователя свой контекст в группах

## LLM-провайдеры

| Провайдер | Переменная | По умолчанию | Примечание |
|-----------|-----------|-------------|------------|
| `hermes` | `LLM_API_KEY` | локальный Hermes Agent | через API Server `127.0.0.1:8642/v1` |
| `groq` | `LLM_API_KEY` | `llama-3.3-70b-versatile` | бесплатный tier |
| `anthropic` | `LLM_API_KEY` | `claude-haiku-4-5` | платный |
| `ollama` | `LLM_API_KEY` | `llama3` | локально |

При использовании `hermes` можно задать `LLM_FALLBACK_KEY` (ключ Groq) —
если Hermes недоступен, бот автоматически переключится на fallback.

## Быстрый старт

```bash
# 1. Клонировать
git clone https://github.com/walekspy/todo-bot.git
cd todo-bot

# 2. Установить зависимости
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Для голосового ввода (опционально)
pip install faster-whisper
# если ошибка NumPy на старых CPU:
pip install 'numpy<2.0' --force-reinstall

# 4. Настроить .env
cp .env.example .env
# отредактировать BOT_TOKEN и LLM_API_KEY

# 5. Запустить
python -m bot.main
```

## Настройка .env

```bash
# Токен Telegram-бота (получить у @BotFather)
BOT_TOKEN=123456:ABCdef...

# LLM-провайдер: hermes | groq | anthropic | ollama
LLM_PROVIDER=groq

# Ключ API для провайдера
LLM_API_KEY=gsk_your_key_here

# Fallback-ключ (если LLM_PROVIDER=hermes)
LLM_FALLBACK_KEY=gsk_groq_fallback_key

# Модель (пусто = дефолт провайдера)
LLM_MODEL=

# Часовой пояс (IANA)
TIMEZONE=Asia/Vladivostok

# Путь к SQLite БД
DATABASE_PATH=data/bot.db

# Google Drive (опционально)
GDRIVE_SERVICE_ACCOUNT_JSON=credentials/service_account.json
GDRIVE_BACKUP_FOLDER_ID=

# Бэкап в Telegram-чат
BACKUP_CHAT_ID=

# Настройки откладывания
SNOOZE_EVENING_HOUR=19
SNOOZE_MORNING_HOUR=9
ESCALATION_SNOOZE_COUNT=3
```

## Интеграция с Hermes Agent

Бот может использовать [Hermes Agent](https://github.com/NousResearch/hermes-agent) как LLM-бэкенд
через встроенный OpenAI-compatible API Server:

```bash
# В Hermes .env:
API_SERVER_ENABLED=true
API_SERVER_KEY=your_key_here
API_SERVER_PORT=8642
API_SERVER_HOST=127.0.0.1

# В todo-bot .env:
LLM_PROVIDER=hermes
LLM_API_KEY=your_key_here   # должен совпадать с API_SERVER_KEY
LLM_FALLBACK_KEY=gsk_...     # Groq fallback при недоступности Hermes
```

**Архитектура:**
```
Telegram → todo-bot (aiogram)
              ├─ faster-whisper (голос → текст)
              └─ LLMClient
                   ├─ Hermes API Server (127.0.0.1:8642/v1)
                   └─ Groq (fallback)
```

**Особенности интеграции:**
- Hermes в том же чате должен иметь `TELEGRAM_REQUIRE_MENTION=true` чтобы не дублировать обработку
- Todo-бот использует Hermes для извлечения задач, а не как замену UI
- System prompt заточен под строгий JSON-вывод (парсер, а не ассистент)
- При сбое JSON-парсинга — умный fallback: `dateparser.search_dates` извлекает время из сырого текста

## Команды бота

| Команда | Описание |
|---------|----------|
| `/start` | Регистрация и приветствие |
| `/add` | Добавить задачу вручную |
| `/list` | Список активных задач |
| `/today` | Задачи на сегодня |
| `/done` | Отметить задачу выполненной |
| `/sync` | Синхронизировать с Google Tasks |
| `/watch <url>` | Следить за Google Doc |
| `/sources` | Наблюдаемые документы |
| `/family` | Задачи семейной группы |
| `/backup` | Бэкап БД в Telegram |
| `/chatid` | ID текущего чата |
| `/set_notify <id>` | Направить напоминания в другой чат |
| `/unset_notify` | Отменить маршрутизацию |
| `/notify_status` | Куда уходят напоминания |

## Создание задачи голосом

1. Отправь голосовое сообщение боту
2. Бот скачивает OGG → конвертирует в WAV 16kHz mono через ffmpeg
3. faster-whisper (base, CPU, int8) распознаёт русскую речь
4. Текст передаётся в LLM для извлечения задачи
5. Показывается карточка подтверждения с inline-кнопками

## Жизненный цикл задачи

```
PENDING → напоминание в指定时间 → [Отложить|В работу|Готово]
   ↑         ↓
   └─── отложено (новое время)
                ↓
           ACTIVE → check-in через 30 мин
                ↓
           не выполнено → reset → PENDING
                ↓
           выполнено → DONE
```

## Запуск через systemd

```ini
# /etc/systemd/system/todo-bot.service
[Unit]
Description=Todo Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/todo-bot
EnvironmentFile=/opt/todo-bot/.env
ExecStart=/opt/todo-bot/venv/bin/python -m bot.main
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable --now todo-bot
```

## Тестирование

```bash
source venv/bin/activate
python -m pytest tests/ -v
```

## Структура проекта

```
todo-bot/
├── bot/
│   ├── main.py              # точка входа
│   ├── config.py            # загрузка конфига из .env
│   ├── adapters/            # источники задач (ручной ввод, Google Doc, .md)
│   ├── llm/
│   │   ├── client.py        # LLM-клиент (hermes/groq/anthropic/ollama)
│   │   └── extractor.py     # извлечение задач из текста
│   ├── handlers/
│   │   ├── messages.py      # текст, голос, документы
│   │   ├── commands.py      # /команды
│   │   ├── callbacks.py     # inline-кнопки
│   │   └── snooze_fsm.py    # FSM откладывания
│   ├── keyboards/           # клавиатуры (подтверждение, напоминание, список)
│   ├── db/                  # SQLite: модели, репозиторий
│   ├── scheduler/           # APScheduler: напоминания, проверки документов
│   ├── sync/                # синхронизация с Google Tasks
│   ├── backup/              # бэкап в Google Drive / Telegram
│   └── notifications/       # отправка уведомлений
├── tests/
├── docs/
├── requirements.txt
├── .env.example
└── README.md
```

## Лицензия

MIT
