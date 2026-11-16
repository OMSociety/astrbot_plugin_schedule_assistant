<p align="center"><a href="README.md">中文</a> · <a href="README_en.md">English</a> · <strong>Русский</strong> · <a href="README_ja.md">日本語</a></p>

<div align="center">

<h1><img src="https://raw.githubusercontent.com/OMSociety/astrbot_plugin_schedule_assistant/main/logo.png" width="192" alt="Schedule Assistant Logo"><br>Schedule Assistant</h1>

**Ваш заботливый помощник по расписанию** — утренняя сводка · напоминания о привычках · управление расписанием через LLM · двусторонняя синхронизация Apple Календаря · задачи Notion

[![Version](https://img.shields.io/github/v/tag/OMSociety/astrbot_plugin_schedule_assistant?label=version&color=blue)](https://github.com/OMSociety/astrbot_plugin_schedule_assistant/releases)
[![AstrBot](https://img.shields.io/badge/AstrBot-%E2%89%A5v4-green.svg)](https://github.com/AstrBotDevs/AstrBot)
[![License](https://img.shields.io/badge/license-MIT-orange.svg)](LICENSE)
[![Stars](https://img.shields.io/github/stars/OMSociety/astrbot_plugin_schedule_assistant)](https://github.com/OMSociety/astrbot_plugin_schedule_assistant/stargazers)
[![Issues](https://img.shields.io/github/issues/OMSociety/astrbot_plugin_schedule_assistant)](https://github.com/OMSociety/astrbot_plugin_schedule_assistant/issues)

[Возможности](#возможности) • [Как это работает](#как-это-работает) • [Быстрый старт](#быстрый-старт) • [Настройки](#настройки) • [Инструменты LLM](#инструменты-llm) • [История изменений](CHANGELOG.md)

</div>

> Проект написан ИИ · Логотип с Pixiv Pid: [130776279](https://www.pixiv.net/artworks/130776279)

---

## Возможности

| Возможность | Описание |
|-------------|----------|
| **Доставка силами фреймворка** | Текст напоминания создаёт основной Agent AstrBot с учётом личности и истории целевой сессии, затем отправляет через `send_message_to_user`. Только простой текст |
| **Ежедневная утренняя сводка** | Погода + расписание на 24 часа (локальное и Apple) + задачи Notion в одном сообщении |
| **Напоминания о привычках** | Душ, сон и вода с настраиваемым временем и переключателями |
| **Напоминания о событиях** | За N минут до начала события с учётом заметки |
| **Управление расписанием через LLM** | Добавление, удаление, список и изменение на естественном языке |
| **Двусторонняя синхронизация Apple Календаря** | Чтение и запись iCloud CalDAV с дедупликацией и добавочными обновлениями |
| **Синхронизация задач Notion** | Обратный отсчёт срока в утренней сводке (осталось N дней / сегодня / просрочено) |

---

## Как это работает

Напоминания доставляет механизм проактивного Agent в AstrBot. Плагин лишь собирает данные и пояснение к задаче в нужный момент и передаёт его в `active job`. Фреймворк запускает основной Agent целевой сессии, тот пишет сообщение с учётом личности и истории этой сессии и отправляет его через `send_message_to_user`.

Поэтому тон зависит от личности, настроенной для бота; отдельной личности в плагине нет.

Все отправки — простой текст. Неудачная доставка считается потерей этого выпуска: автоматических повторов и догоняющих отправок нет.

### Утренняя сводка

Отправляется каждое утро в заданное время:

- Текущая погода и прогноз
- Локальные события и события Apple в течение 24 часов от времени сводки, объединённые и без дублей
- Задачи Notion с обратным отсчётом
- События на весь день учитываются только в день сводки

Встроенные промпты — короткие инструкции с данными; свой промпт полностью заменяет встроенный шаблон.

### Напоминания о привычках

| Привычка | Время по умолчанию | Примечание |
|----------|--------------------|------------|
| Душ | 22:00 | Настраивается |
| Сон | 23:00 | Настраивается |
| Вода | Каждые 90 минут | С 09:30 до 21:30 |
| Событие | За N минут | По умолчанию выключено |

### Двусторонняя синхронизация Apple iCloud

**Чтение (Apple → локально)**
- Периодически загружает события iCloud в локальное хранилище
- Синхронизирует добавления, изменения и удаления по данным Apple Календаря

**Запись (локально → Apple)**
- Созданные через бота события записываются в выбранный календарь
- UID события сохраняется для сопоставления и дедупликации

**Что нужно указать**
- `username` — почта Apple ID
- `app_password` — **пароль приложения** с [appleid.apple.com](https://appleid.apple.com), не пароль входа
- `calendar_id` — UUID календаря; пусто — первый доступный. Список есть в журнале в виде `имя → UUID`, либо возьмите UUID из `.../calendars/<UUID>/`
- `caldav_host` — хост CalDAV, по умолчанию `caldav.icloud.com`. Для аккаунтов материкового Китая — `caldav.icloud.com.cn`; если не подходит, укажите свой разделённый хост вида `pXX-caldav.icloud.com.cn`

### Синхронизация задач Notion

Задачи Notion попадают в утреннюю сводку с обратным отсчётом срока. Доступ идёт через Maton Gateway.

---

## Быстрый старт

### 1. Установка

AstrBot WebUI → Магазин плагинов → найти `schedule_assistant`

> **Подсказка:** зависимости объявлены в `requirements.txt` (`aiohttp`, `python-dateutil`). AstrBot проверяет и устанавливает недостающие при загрузке плагина.

### 2. Список сессий

Отправьте `/sid` в сессии (личный чат или группа), которая должна получать напоминания и может использовать инструменты расписания, и запомните UMO. Затем в настройках плагина → **Основные настройки** → `user_umos` добавьте по одной строке на сессию:

```
qq:FriendMessage:123456789
qq:GroupMessage:987654321
```

Формат `platform:message_type:session` (UMO). Некорректные строки пропускаются с одним предупреждением при запуске.

`user_umos` также определяет, какие сессии могут пользоваться инструментами расписания: в сессиях из списка можно создавать, просматривать, изменять и удалять события; вызовы из других сессий возвращают сообщение о том, что инструмент не включён, и ничего не записывают.

Группа считается отдельным пользователем: участники делят один список событий, и утренняя сводка, напоминания о ванне, сне и воде тоже приходят в группу. Напоминания и инструменты действуют на всю группу, если она указана в `user_umos`; убедитесь, что участники об этом знают.

### 3. Необязательно: Notion

1. Подключите Notion через [Maton](https://www.maton.ai/) (OAuth2) и создайте **Maton API Key**
2. Укажите `maton_api_key` в **Внешние сервисы** и перечислите базы в `notion_db_ids` (например, `Tasks:xxx`, `Reading:yyy`)

> **Внимание:** данные Notion идут через сторонний шлюз `gateway.maton.ai`, а не через официальный API Notion. `maton_api_key` передаётся этому шлюзу, который читает заголовок, статус и срок в указанных вами базах.

---

## Настройки

### Основные

| Параметр | Тип | По умолчанию | Описание |
|----------|-----|--------------|----------|
| `user_umos` | list | `[]` | UMO сессий для рассылки и использования инструментов расписания: по одному `platform:message_type:session` в строке |

### Напоминания о событиях

| Параметр | Тип | По умолчанию | Описание |
|----------|-----|--------------|----------|
| `enable_schedule_reminder` | bool | `false` | Включить напоминания |
| `schedule_reminder_minutes` | int | `10` | За сколько минут; события на весь день пропускаются |

### Напоминания о привычках

| Параметр | Тип | По умолчанию | Описание |
|----------|-----|--------------|----------|
| `enable_morning_report` | bool | `true` | Утренняя сводка |
| `morning_report_time` | string | `09:00` | Время сводки (HH:MM) |
| `enable_bath_reminder` | bool | `true` | Напоминание о душе |
| `bath_time` | string | `22:00` | Время душа |
| `enable_sleep_reminder` | bool | `true` | Напоминание о сне |
| `sleep_time` | string | `23:00` | Время сна |
| `enable_water_reminder` | bool | `true` | Напоминание о воде |
| `water_interval` | int | `90` | Интервал, минут |
| `water_start_time` | string | `09:30` | Начало |
| `water_end_time` | string | `21:30` | Конец |

### Синхронизация календаря

| Параметр | Тип | По умолчанию | Описание |
|----------|-----|--------------|----------|
| `enable_apple_calendar_sync` | bool | `false` | Двусторонняя синхронизация |
| `apple_calendar_sync_interval` | int | `30` | Интервал, минут |
| `apple_calendar.username` | string | - | Почта Apple ID |
| `apple_calendar.app_password` | string | - | Пароль приложения |
| `apple_calendar.caldav_host` | string | - | Хост CalDAV |
| `apple_calendar.calendar_id` | string | - | UUID календаря |
| `webcal_urls` | list | `[]` | Ссылки WebCal |

> **Безопасность WebCal:** `webcal_urls` принимает только публичные `https://` ( `webcal://` преобразуется). `localhost`, частные сети и метаданные облака (`169.254.169.254`) отклоняются для защиты от SSRF.

### Внешние сервисы

| Параметр | Тип | По умолчанию | Описание |
|----------|-----|--------------|----------|
| `maton_api_key` | string | `""` | Maton API Key (нужен для Notion) |
| `notion_db_ids` | list | `[]` | В виде `Task:xxx`, `Reading:yyy` |
| `weather_api_key` | string | `""` | Ключ Seniverse |
| `weather_city` | string | `Beijing` | Город для погоды |

### Промпты напоминаний

| Параметр | Тип | По умолчанию | Описание |
|----------|-----|--------------|----------|
| `prompt_morning` | string | `""` | Плейсхолдеры: `{date} {weekday} {weather_current} {weather_forecast} {agenda} {notion_todos}` |
| `prompt_bath` | string | `""` | `{current_time}` |
| `prompt_sleep` | string | `""` | `{current_time}` |
| `prompt_water` | string | `""` | `{current_time}` |
| `prompt_schedule` | string | `""` | `{item_title} {time_label} {ahead_label} {item_context}` |

> Пустое значение — встроенный промпт (данные, требования к тексту и выводу). Непустое заменяет его целиком: плагин не добавляет своих требований. Отправка идёт простым текстом, поэтому правила вроде «только текст, не упоминай систему» пишите сами.

### Пример конфигурации

```json
{
  "basic_settings": {
    "user_umos": ["qq:FriendMessage:123456789", "qq:GroupMessage:987654321"]
  },
  "schedule_reminder_settings": {
    "enable_schedule_reminder": false,
    "schedule_reminder_minutes": 10
  },
  "habit_reminder_settings": {
    "enable_morning_report": true,
    "morning_report_time": "09:00",
    "enable_bath_reminder": true,
    "bath_time": "22:00",
    "enable_sleep_reminder": true,
    "sleep_time": "23:00",
    "enable_water_reminder": true,
    "water_interval": 90,
    "water_start_time": "09:30",
    "water_end_time": "21:30"
  },
  "calendar_sync_settings": {
    "enable_apple_calendar_sync": false,
    "apple_calendar_sync_interval": 30,
    "apple_calendar": {
      "username": "",
      "app_password": "",
      "caldav_host": "",
      "calendar_id": ""
    },
    "webcal_urls": []
  },
  "external_services_settings": {
    "maton_api_key": "",
    "notion_db_ids": [],
    "weather_api_key": "",
    "weather_city": "Beijing"
  },
  "prompt_settings": {
    "prompt_morning": "",
    "prompt_bath": "",
    "prompt_sleep": "",
    "prompt_water": "",
    "prompt_schedule": ""
  }
}
```

---

## Инструменты LLM

Плагин регистрирует четыре инструмента LLM. Модель сама решает, когда их вызвать; достаточно говорить обычным языком.

> **Форматы времени:** ISO 8601. Со временем — `2026-09-10 14:30`; на весь день — `2026-09-10` и `all_day=true`. Начало не может быть в прошлом, год — позже 2100.
>
> **Область действия:** инструменты доступны только в сессиях, указанных в `user_umos`; вызовы из других сессий возвращают сообщение о том, что инструмент не включён, и ничего не записывают.

```
Пользователь: добавь встречу завтра в 9
-> create_schedule(title="встреча", start="2026-09-11 09:00")
   Создано «встреча», время: 09-11 09:00 ✅

Пользователь: встреча завтра с 9 до 11
-> create_schedule(title="встреча", start="2026-09-11 09:00", end="2026-09-11 11:00")
   Создано «встреча», время: 09-11 09:00-11:00 ✅

Пользователь: послезавтра выездной день
-> create_schedule(title="выезд", start="2026-09-12", all_day=true)
   Создано «выезд», время: 09-12 весь день ✅

Пользователь: перенеси встречу с 15 на 16
-> update_schedule(title_keyword="встреча", new_start="2026-09-11 16:00")
   Событие изменено: время — 09-11 16:00 ✅

Пользователь: что на этой неделе
-> list_schedules(days=7)
   📋 События на 7 дней (3):

   ━━━ 08-17 Пн ━━━
     ⏰ 09:00 │ встреча

Пользователь: удали завтрашний книжный клуб
-> delete_schedule(title_keyword="книжный клуб")
   Удалено «книжный клуб» ✅
```

### create_schedule

| Параметр | Тип | Описание |
|----------|-----|----------|
| `title` | string | **Обязательно**, название |
| `start` | string | **Обязательно**, начало в ISO 8601 (`2026-09-10 14:30`); для всего дня — дата `2026-09-10` |
| `end` | string? | Конец в ISO 8601; без него — одна точка (Apple получит час) |
| `all_day` | bool? | Событие на весь день |
| `description` | string? | Заметка |

### delete_schedule

| Параметр | Тип | Описание |
|----------|-----|----------|
| `schedule_id` | string? | Точный ID |
| `title_keyword` | string? | Ключевое слово в названии |

### list_schedules

| Параметр | Тип | Описание |
|----------|-----|----------|
| `days` | int? | Сколько дней вперёд, по умолчанию 7 |

### update_schedule

| Параметр | Тип | Описание |
|----------|-----|----------|
| `schedule_id` | string? | Точный ID |
| `title_keyword` | string? | Ключевое слово в названии |
| `new_title` | string? | Новое название |
| `new_start` | string? | Новое начало (ISO 8601) |
| `new_end` | string? | Новый конец (ISO 8601), вместе с `new_start` |
| `new_all_day` | bool? | Сделать событием на весь день |
| `new_description` | string? | Новая заметка |

## История изменений

> **[Полная история →](CHANGELOG.md)**

## Поддержка

Если плагин полезен, поставьте Star. Issues и pull requests приветствуются.

- [AstrBot](https://github.com/AstrBotDevs/AstrBot)
- Логотип с Pixiv Pid: [130776279](https://www.pixiv.net/artworks/130776279)

## Лицензия

MIT License.

[@OMSociety](https://github.com/OMSociety)
