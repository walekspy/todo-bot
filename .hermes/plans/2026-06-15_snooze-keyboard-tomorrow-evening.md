# Изменение кнопок «Завтра» и «Позже» в клавиатуре откладывания

> **Для Hermes:** TDD с тестом перед каждым изменением. Коммит после каждой задачи.

**Цель:** Добавить кнопку «Завтра» (9:00) и изменить «Позже» на сегодня/завтра 22:00.

**Файлы которые меняем:**
- `bot/keyboards/snooze.py` — новая кнопка «Завтра»
- `bot/handlers/callbacks.py` — логика обработки `snooze:tomorrow` и изменённый `snooze:later`
- `bot/config.py` — НЕ меняем (snooze_morning_hour=9 уже есть)
- `tests/test_snooze.py` (создать) — тесты

**Что НЕ меняем:**
- Приоритеты (high/medium/low) для кнопок +15м/+30м/+1ч остаются без изменений
- Функция `_skip_night` не меняется
- Клавиатура `reminder_keyboard` остаётся без изменений (она просто открывает snooze_keyboard)

---

## Как работает сейчас

Ряд 1: `+15 мин` `+30 мин` `+1 час`
Ряд 2: `Позже` `✏️ Своё время`

«Позже» сейчас:
- high → +3 часа (с пропуском ночи)
- medium → завтра в 9:00
- low → +24 часа

## Как должно стать

Ряд 1: `+15 мин` `+30 мин` `+1 час`
Ряд 2: `Позже` `Завтра` `✏️ Своё время`

«Позже» (новое поведение):
- Сегодня в 22:00
- Если сейчас ≥ 22:00 → завтра в 22:00
- Не зависит от приоритета

«Завтра» (новая кнопка):
- Завтра в 9:00 (config.snooze_morning_hour)
- Не зависит от приоритета

---

### Задача 1: Написать тесты для нового поведения

**Файл:** `tests/test_snooze.py` (создать)

```python
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from bot.handlers.callbacks import handle_snooze_choice  # рефакторим для тестируемости

def test_later_before_22_sets_today_22():
    """Если сейчас < 22:00, 'Позже' ставит сегодня в 22:00"""
    ...

def test_later_after_22_sets_tomorrow_22():
    """Если сейчас >= 22:00, 'Позже' ставит завтра в 22:00"""
    ...

def test_tomorrow_sets_next_day_9am():
    """Кнопка 'Завтра' всегда ставит завтра в 9:00"""
    ...
```

### Задача 2: Изменить snooze_keyboard — добавить кнопку «Завтра»

**Файл:** `bot/keyboards/snooze.py`

Меняем второй ряд:
```python
builder.row(
    InlineKeyboardButton(text="Позже",        callback_data=f"snooze:later:{task_id}"),
    InlineKeyboardButton(text="Завтра",       callback_data=f"snooze:tomorrow:{task_id}"),
    InlineKeyboardButton(text="✏️ Своё время", callback_data=f"snooze:custom:{task_id}"),
)
```

### Задача 3: Изменить логику snooze:later на «сегодня/завтра 22:00»

**Файл:** `bot/handlers/callbacks.py`, в функции `on_snooze_choice`

Заменяем блок `elif option == "later":` (строки 223-241):

```python
elif option == "later":
    # Сегодня в 22:00, если уже позже 22:00 — завтра в 22:00
    candidate = now_local.replace(hour=22, minute=0, second=0, microsecond=0)
    if now_local >= candidate:
        candidate += timedelta(days=1)
    until = candidate
```

### Задача 4: Добавить обработку snooze:tomorrow

**Файл:** `bot/handlers/callbacks.py`, в функции `on_snooze_choice`

Добавляем после блока `elif option == "later":`:

```python
elif option == "tomorrow":
    tomorrow = (now_local + timedelta(days=1)).replace(
        hour=config.snooze_morning_hour, minute=0, second=0, microsecond=0
    )
    until = tomorrow
```

### Задача 5: Проверить — ручной тест

Отправить боту команду `/add тест` → дождаться напоминания → нажать «⏱ Отложить» → проверить что:
- «Позже» ставит на сегодня/завтра 22:00
- «Завтра» ставит на завтра 9:00
- Остальные кнопки работают как раньше

---

## Что может сломаться

| Риск | Защита |
|---|---|
| Старый код «Позже» использовал приоритет (high/medium/low) | Убираем — новая логика проще и не зависит от приоритета |
| `_skip_night` больше не нужен для `later` | Не вызываем, функция остаётся для других кнопок |
| Пользователи привыкли к старому «Позже» | Кнопка «Завтра» даёт exactly то что раньше делал «Позже» для medium-задач |
