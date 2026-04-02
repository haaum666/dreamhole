# DreamHole — Техническая документация

Исчерпывающее описание проекта для разработчика.

---

## Содержание

1. [Схема БД](#1-схема-бд)
2. [API Endpoints](#2-api-endpoints)
3. [Функции database.py](#3-функции-databasepy)
4. [Логика краулера](#4-логика-краулера)
5. [Функции popup.js](#5-функции-popupjs)
6. [Алгоритмы хэширования](#6-алгоритмы-хэширования)
7. [Content.js — инжекция на страницу](#7-contentjs--инжекция-на-страницу)
8. [Конфигурация и переменные окружения](#8-конфигурация-и-переменные-окружения)
9. [Деплой](#9-деплой)
10. [Нюансы и особенности](#10-нюансы-и-особенности)

---

## 1. Схема БД

### 1.1 `companies`
```
id              BIGINT PRIMARY KEY
name            TEXT NOT NULL
site_url        TEXT (nullable)
area            TEXT (nullable)
trusted         BOOLEAN DEFAULT FALSE
updated_at      TIMESTAMPTZ DEFAULT NOW()
```

### 1.2 `vacancies`
```
id                  BIGINT PRIMARY KEY
title               TEXT NOT NULL
company_id          BIGINT REFERENCES companies(id) (nullable)
company_name        TEXT (nullable)
salary_from         INTEGER (nullable)
salary_to           INTEGER (nullable)
salary_currency     TEXT (nullable)
experience_id       TEXT (nullable)
employment_id       TEXT (nullable)
schedule_id         TEXT (nullable)
is_remote           BOOLEAN DEFAULT FALSE
area                TEXT (nullable)
professional_roles  TEXT[] (nullable)
published_at        TIMESTAMPTZ (nullable)
initial_created_at  TIMESTAMPTZ (nullable)
first_seen_at       TIMESTAMPTZ DEFAULT NOW()
last_seen_at        TIMESTAMPTZ DEFAULT NOW()
archived_at         TIMESTAMPTZ (nullable)
is_active           BOOLEAN DEFAULT TRUE
```

**Индексы:**
- `idx_vacancies_company` ON company_id
- `idx_vacancies_published` ON published_at
- `idx_vacancies_active` ON is_active
- `idx_vacancies_area` ON area
- `idx_vacancies_experience` ON experience_id
- `idx_vacancies_initial` ON initial_created_at

**Важно:**
- `professional_roles` — массив, используется с оператором `&&` (пересечение)
- `initial_created_at` **не обновляется** при UPSERT
- `is_remote` определяется по `schedule_id` или `work_format` от hh.ru
- `published_at` используется для детектирования переподъёма (boost)

### 1.3 `vacancy_daily`
```
vacancy_id  BIGINT REFERENCES vacancies(id)
seen_date   DATE DEFAULT CURRENT_DATE
is_active   BOOLEAN DEFAULT TRUE
PRIMARY KEY (vacancy_id, seen_date)
```
Заполняется при каждом UPSERT вакансии.

### 1.4 `vacancy_changes`
```
id          BIGSERIAL PRIMARY KEY
vacancy_id  BIGINT REFERENCES vacancies(id)
changed_at  TIMESTAMPTZ DEFAULT NOW()
field       TEXT NOT NULL
old_value   TEXT (nullable)
new_value   TEXT (nullable)
```

**Индекс:** `idx_vacancy_changes_vacancy` ON vacancy_id

**Отслеживаемые поля:**

| field | формат | пример |
|-------|--------|--------|
| salary | "from/to" | "50000/60000" → "100000/150000" |
| boost | дата | "2026-03-15" → "2026-03-20" |
| title | строка | "Senior Python" → "Lead Python" |
| experience | experience_id | "between1And3" → "between3And6" |
| format | "employment_id/schedule_id" | "full/remote" → "full/hybrid" |
| roles | sorted, через запятую | "96,156" → "96,156,160" |

### 1.5 `crawler_runs`
```
id                  BIGSERIAL PRIMARY KEY
started_at          TIMESTAMPTZ DEFAULT NOW()
finished_at         TIMESTAMPTZ (nullable)
vacancies_processed INTEGER DEFAULT 0
```

### 1.6 `interview_reviews`
```
id                BIGSERIAL PRIMARY KEY
company_id        BIGINT NOT NULL
company_name      TEXT NOT NULL
role_category     TEXT (nullable)
stages            TEXT[] (nullable)
test_task_status  TEXT (nullable)
process_status    TEXT NOT NULL
stopped_at_stage  TEXT (nullable)
difficulty        SMALLINT 1-5 (nullable)
hr_rating         SMALLINT 1-5 (nullable)
duration_range    TEXT (nullable)
comment           TEXT (nullable)
questions         TEXT (nullable)
user_hash         TEXT NOT NULL
likes             INTEGER DEFAULT 0
dislikes          INTEGER DEFAULT 0
fire              INTEGER DEFAULT 0
poop              INTEGER DEFAULT 0
clown             INTEGER DEFAULT 0
is_flagged        BOOLEAN DEFAULT FALSE
flag_count        INTEGER DEFAULT 0
submitted_at      TIMESTAMPTZ DEFAULT NOW()
```

**Индексы:**
- `idx_reviews_user_company` UNIQUE ON (user_hash, company_id) — 1 отзыв на пользователя на компанию
- `idx_reviews_company` ON company_id

**process_status значения:**
`offer_accepted`, `offer_declined`, `offer_revoked`, `rejected`, `ghosted`, `frozen`, `withdrew`, `waiting`, `ongoing`

### 1.7 `review_votes`
```
user_hash  TEXT NOT NULL
review_id  BIGINT REFERENCES interview_reviews(id) ON DELETE CASCADE
vote       TEXT NOT NULL
voted_at   TIMESTAMPTZ DEFAULT NOW()
PRIMARY KEY (user_hash, review_id)
```

**vote значения:** `like`, `dislike`, `fire`, `poop`, `clown`

---

## 2. API Endpoints

**Base URL:** `https://moiraidrone.fvds.ru/hh`

### 2.1 Вакансии

#### `GET /vacancy/{vacancy_id}`

**Ответ:**
```json
{
  "vacancy_id": 123,
  "is_active": true,
  "area": "Москва",
  "professional_roles": ["96", "156"],
  "is_remote": false,
  "age": {
    "age_total_days": 15,
    "days_since_boost": 2,
    "initial_created_at": "2026-03-20T10:00:00+00:00",
    "last_boosted_at": "2026-03-31T14:00:00+00:00"
  },
  "closing_time": {
    "median_days": 21,
    "sample_size": 45
  },
  "competition": {
    "count": 312,
    "salary_transparency": {
      "percent": 65,
      "sample_size": 312
    }
  },
  "reopen": {
    "past_attempts": 3,
    "avg_reopen_days": 18
  },
  "salary": {
    "from": 120000,
    "to": 180000,
    "currency": "RUR",
    "market": {
      "median": 150000,
      "sample_size": 156,
      "label": "на уровне рынка",
      "salary_type": "avg"
    }
  }
}
```

**Коды:** 200, 404 (вакансия не в БД)

**Особенности:**
- Если `published_at` null — автоматически делает запрос к hh.ru API
- `salary_type`: "from" | "to" | "avg"
- `label`: "ниже рынка" (< 0.85x медианы), "выше рынка" (> 1.15x), "на уровне рынка"

#### `GET /vacancy/{vacancy_id}/history`

**Ответ:** массив изменений, лимит 50, DESC по времени
```json
[
  {
    "changed_at": "2026-03-28T12:30:00+00:00",
    "field": "salary",
    "old_value": "100000/150000",
    "new_value": "120000/180000"
  }
]
```

### 2.2 Зарплата

#### `GET /salary`

**Query params:**
- `experience_id` — e.g. "between1And3"
- `area` — e.g. "Москва"
- `roles` — comma-separated IDs, e.g. "96,156"

**Ответ:**
```json
{
  "p25": 100000,
  "median": 140000,
  "p75": 200000,
  "sample_size": 287,
  "area": "Москва",
  "experience_id": "between1And3"
}
```

**Коды:** 200, 404 (нет данных)

### 2.3 Компании

#### `GET /company/{company_id}`

**Query params:** `roles`, `area`, `is_remote`

**Ответ:**
```json
{
  "company_id": 456,
  "active_vacancies": 12,
  "total_vacancies": 450,
  "median_days_to_fill": 23.5,
  "median_sample_size": 98,
  "trend": {
    "company": [{"month": "2026-01", "opened": 5, "closed": 3}],
    "market": [{"month": "2026-01", "opened": 145, "closed": 120}]
  }
}
```

**Особенности:**
- `active_vacancies` — live запрос к hh.ru, не из БД
- `trend` — последние 12 месяцев

### 2.4 Краулер

#### `GET /crawler/status`
```json
{
  "running": true,
  "started_at": "2026-04-02T10:30:00+00:00",
  "finished_at": null,
  "vacancies_processed": 145230
}
```

### 2.5 Статистика

#### `GET /stats`
```json
{
  "total_vacancies": 234567,
  "active_vacancies": 45230,
  "archived_vacancies": 189337,
  "companies": 12450,
  "changes_tracked": 87654,
  "crawl_started": "2025-11-15",
  "last_crawl": "2026-04-02"
}
```

#### `GET /roles`
```json
{"96": "Python разработчик", "156": "Java разработчик", ...}
```

### 2.6 Отзывы

#### `POST /reviews`
```json
{
  "company_id": 456,
  "company_name": "Яндекс",
  "role_category": "Backend",
  "stages": ["hr", "test", "tech"],
  "test_task_status": "passed",
  "process_status": "offer_accepted",
  "stopped_at_stage": null,
  "difficulty": 4,
  "hr_rating": 5,
  "duration_range": "1_2w",
  "comment": "...",
  "questions": "...",
  "user_hash": "a1b2c3d4..."
}
```

**Коды:** 200, 409 (дубль), 429 (rate limit > 3 за 24ч)

#### `GET /reviews/{company_id}`
```json
{
  "aggregate": {
    "total": 42,
    "avg_difficulty": 3.5,
    "avg_hr": 4.2,
    "ghost_rate": 15,
    "offer_rate": 65,
    "reject_rate": 20
  },
  "reviews": [
    {
      "id": 1001,
      "role_category": "Backend",
      "stages": ["hr", "test", "tech"],
      "process_status": "offer_accepted",
      "difficulty": 4,
      "hr_rating": 5,
      "comment": "...",
      "submitted_at": "2026-03-28T...",
      "likes": 12,
      "dislikes": 1,
      "fire": 3,
      "poop": 0,
      "clown": 0
    }
  ]
}
```
Лимит 50 отзывов, только `is_flagged=FALSE`, newest first.

#### `POST /reviews/{review_id}/vote/{vote_type}`

**vote_type:** `like` | `dislike` | `fire` | `poop` | `clown`

**Тело:** `{"user_hash": "vote_hash_..."}`

**Ответ:** все 5 счётчиков (`likes`, `dislikes`, `fire`, `poop`, `clown`)

**Коды:** 200, 400 (неверный vote), 404, 409 (уже голосовал)

#### `POST /reviews/{review_id}/flag`

Инкрементирует `flag_count`. При 5+ → `is_flagged=TRUE`.

#### `GET /reviews/stats`
```json
{
  "total": 1234,
  "companies": 567,
  "offers": 800,
  "rejected": 250,
  "ghosted": 150,
  "ongoing": 34,
  "avg_difficulty": 3.2,
  "avg_hr": 4.1,
  "top_companies": [{"name": "Яндекс", "count": 87}]
}
```

### 2.7 Администрирование

#### `DELETE /admin/reviews/{review_id}`
**Заголовок:** `X-Admin-Token: <ADMIN_TOKEN>`
**Коды:** 200, 403, 404

#### `PATCH /admin/reviews/{review_id}`
**Заголовок:** `X-Admin-Token: <ADMIN_TOKEN>`
**Тело (все поля опциональны):**
```json
{
  "process_status": "rejected",
  "comment": "...",
  "is_flagged": false,
  ...
}
```

### 2.8 Health check

#### `GET /health`
```json
{"status": "ok"}
```

---

## 3. Функции database.py

### Инициализация

| Функция | Описание |
|---------|----------|
| `get_pool(dsn)` | Создаёт asyncpg пул (min=2, max=10), с кэшем `_pool` |
| `init_db(pool)` | CREATE TABLE IF NOT EXISTS + миграции + индексы |

### Upsert

| Функция | Описание |
|---------|----------|
| `upsert_company(pool, c: dict)` | INSERT OR UPDATE по id, обновляет updated_at |
| `upsert_vacancy(pool, v: dict)` | INSERT OR UPDATE. При UPDATE: initial_created_at не меняется. Также пишет в vacancy_daily |

### Архивирование

| Функция | Описание |
|---------|----------|
| `mark_archived(pool, vacancy_ids: list)` | SET is_active=FALSE, archived_at=NOW() для исчезнувших вакансий |

### Change tracking

| Функция | Описание |
|---------|----------|
| `get_vacancy_snapshot(pool, id)` | SELECT title, salary, published_at, experience, employment, schedule, roles |
| `insert_vacancy_change(pool, id, field, old, new)` | INSERT в vacancy_changes |
| `get_vacancy_changes(pool, id)` | SELECT последние 50 изменений DESC |

### Аналитика

| Функция | Описание |
|---------|----------|
| `get_vacancy_insights(pool, id)` | SELECT vacancies + companies |
| `get_salary_stats(pool, exp, area, roles)` | PERCENTILE_CONT 0.25/0.50/0.75 для активных вакансий в RUR > 10000 |
| `get_salary_median_for_comparison(pool, exp, area, roles, is_remote, salary_type)` | Медиана для сравнения. salary_type: "from"/"to"/"avg" |
| `get_competition_count(pool, roles)` | COUNT активных вакансий по ролям |
| `get_salary_transparency(pool, roles)` | % вакансий с указанной зарплатой |
| `get_company_reopen_stats(pool, company_id, exp, roles)` | Сколько раз переоткрывали вакансию и средний интервал |
| `get_median_closing_time(pool, exp, roles)` | Медиана дней от first_seen до archived (только >= 3 дней) |
| `get_company_profile(pool, company_id)` | total_vacancies, median_days_to_fill, sample_size |
| `get_hiring_trend(pool, company_id, roles, area, is_remote)` | Тренд открытий/закрытий за 12 месяцев |

### Краулер

| Функция | Описание |
|---------|----------|
| `start_crawler_run(pool)` | INSERT в crawler_runs, возвращает id |
| `update_crawler_progress(pool, run_id, count)` | UPDATE vacancies_processed |
| `finish_crawler_run(pool, run_id, count)` | UPDATE finished_at + vacancies_processed |
| `get_crawler_status(pool)` | SELECT последняя запись, running = (finished_at IS NULL) |
| `update_vacancy_published_at(pool, id, published_at)` | UPDATE published_at |

### Отзывы

| Функция | Описание |
|---------|----------|
| `insert_review(pool, r)` | INSERT с проверками: rate limit (3/24h), UNIQUE(user_hash, company_id) |
| `get_reviews(pool, company_id)` | SELECT 50 отзывов WHERE is_flagged=FALSE |
| `get_reviews_aggregate(pool, company_id)` | Агрегат: total, avg_*, rates |
| `flag_review(pool, review_id)` | flag_count++, при >= 5 → is_flagged=TRUE |
| `vote_review(pool, review_id, vote, user_hash)` | INSERT review_votes → UPDATE счётчика |
| `delete_review(pool, review_id)` | DELETE |
| `update_review(pool, review_id, fields)` | Whitelist-обновление полей |
| `get_reviews_stats(pool)` | Агрегат по всем отзывам + top 5 компаний |

---

## 4. Логика краулера

### Точка входа: `run_scheduler()`
- Запускает `run_crawl()` сразу, затем каждые 24 часа
- Ошибки логируются, краулер продолжает работу

### Этапы `run_crawl()`

```
1. start_crawler_run() → run_id
2. seen_ids = set()
3. for role_id in IT_DIGITAL_ROLE_IDS:
     async for item in crawl_role(session, role_id):
       old = get_vacancy_snapshot()
       upsert_company()
       upsert_vacancy()
       detect_changes(old, new) → insert_vacancy_change()
       seen_ids.add(vacancy_id)
4. mark_archived(active_ids - seen_ids)
5. finish_crawler_run()
```

### Rate limiting (hh.ru)
- **429:** retry × 3 с задержкой 60/120/180 сек, затем skip
- **Между страницами:** `sleep(0.3)`
- **Между ролями:** `sleep(1)`
- **Соединения:** `TCPConnector(limit=5)`

### Параметры запроса к hh.ru
```
professional_role = role_id
per_page = 100
page = 0..19 (max 20 страниц = 2000 вакансий на роль)
only_with_salary = false
order_by = publication_time
```

### Определение is_remote
```python
is_remote = (schedule_id in REMOTE_SCHEDULES) OR (any work_format_id in REMOTE_FORMATS)
```

### Детектирование изменений `_detect_changes(old, new)`
Сравнивает: salary, published_at (boost), title, experience_id, employment/schedule format, professional_roles

---

## 5. Функции popup.js

### Хэши
```javascript
getUserHash(companyId)   // SHA-256(uuid + companyId + "dhsalt2026")
getVoteHash(reviewId)    // SHA-256(uuid + reviewId + "dhvote2026")
```

### Форматирование
```javascript
getVacancyId(url)        // RegEx /\/vacancy\/(\d+)/
fmt(n)                   // число → "100 000 ₽"
fmtDays(days)            // 0→"сегодня", 1→"1 день", 7+→"2 нед."
fmtDate(isoStr)          // ISO → "2 апр"
fmtMonth(yyyyMM)         // "2026-01" → "янв. 2026"
fmtSalaryVal(s)          // "50000/60000" → "50 000–60 000 ₽"
fmtFormat(val)           // "full/remote" → "полная занятость, удалёнка"
fmtChange(c, roles)      // красивый вывод изменения
```

### API
```javascript
apiFetchWithTimeout(path, options)  // fetch с таймаутом 10000ms, AbortController
apiFetch(path, options)             // обёртка над apiFetchWithTimeout
loadRoles()                         // GET /roles, кэширует в _rolesCache
```

### Рендеринг
```javascript
render(vacancyId)                   // главная функция, строит все 3 таба
loadCompany(data, token, vacancyId) // асинхронно заполняет блок компании
row(label, value, valueClass)       // HTML строка label/value
card(title, content)                // HTML карточка
note(text)                          // HTML заметка
buildCrawlerStatus(cs)              // блок статуса краулера
buildReopenBlock(reopen)            // блок переоткрытий
buildTrendRows(trend)               // таблица тренда (6 месяцев)
```

### Отзывы
```javascript
loadReviewsTab(companyId, companyName)  // загружает и рендерит отзывы (lazy)
openReviewForm(companyId, companyName)  // форма отправки отзыва
```

### Глобальное состояние
```javascript
_currentVacancyId = null   // дедупликация
_renderToken = 0           // race condition guard
_rolesCache = null         // кэш /roles
_reviewsLoaded = false     // lazy load флаг
```

### Константы
```javascript
API = "https://moiraidrone.fvds.ru/hh"
FETCH_TIMEOUT_MS = 10000
EXP_LABELS, EMPLOYMENT_LABELS, SCHEDULE_LABELS
STAGE_LABELS, STATUS_LABELS, TEST_LABELS, DURATION_LABELS
```

---

## 6. Алгоритмы хэширования

### user_hash (для отзывов)
```
SHA-256(uuid + company_id + "dhsalt2026")
```
- `uuid` — генерируется один раз, хранится в `chrome.storage.local.uuid`
- Детерминирован для одного пользователя + одной компании
- Разный для разных компаний

### vote_hash (для реакций)
```
SHA-256(uuid + review_id + "dhvote2026")
```
- Использует review_id, а не company_id
- Хранится в `chrome.storage.local.voted_reviews`

---

## 7. Content.js — инжекция на страницу

```javascript
injectVacancyPanel(vacancyId)  // создаёт панель между элементами на странице вакансии
injectCompanySection(panel, data)  // добавляет блок компании
injectHistory(panel, vacancyId)    // добавляет историю изменений
init()                             // запускается автоматически, парсит vacancy_id из URL
```

**Защита от двойной инжекции:** флаг `_injecting`

---

## 8. Конфигурация и переменные окружения

### backend/.env
```
DATABASE_URL=postgresql://hhuser:hhpass@localhost:5432/hhdb
ADMIN_TOKEN=your-secret-token-here
```

### config.py
```python
DATABASE_URL = os.getenv("DATABASE_URL", "")
ADMIN_TOKEN  = os.getenv("ADMIN_TOKEN", "")
HH_API_BASE  = "https://api.hh.ru"
HH_USER_AGENT = "hh-insights-extension/1.0 (contact@yourdomain.com)"
CRAWL_INTERVAL_HOURS = 24
MAX_VACANCIES_PER_CRAWL = 200_000
API_PORT = 8000
```

### manifest.json
```json
{
  "manifest_version": 3,
  "name": "DreamHole",
  "version": "0.2.0",
  "permissions": ["tabs", "storage"],
  "host_permissions": [
    "https://hh.ru/*",
    "https://*.hh.ru/*",
    "https://moiraidrone.fvds.ru/*"
  ]
}
```

### hh.ru ID справочник

**experience_id:** `noExperience`, `between1And3`, `between3And6`, `moreThan6`

**schedule_id:** `fullDay`, `shift`, `flexible`, `remote`, `flyInFlyOut`

**employment_id (старые):** `full`, `part`, `project`, `volunteer`, `probation`

**employment_id (новые):** `FULL`, `PART`, `PROJECT`, `VOLUNTEER`, `PROBATION`, `FLY_IN_FLY_OUT`, `SIDE_JOB`

---

## 9. Деплой

### deploy.py — процесс

1. SSH подключение (credentials из `.env.deploy`)
2. `apt-get install postgresql python3-pip python3-venv`
3. Создание пользователя и БД PostgreSQL
4. Создание venv в `/opt/hh-extension/venv`
5. SFTP upload: config.py, database.py, crawler.py, api.py, main.py, requirements.txt, .env
6. `pip install -r requirements.txt`
7. Создание `/etc/systemd/system/hh-extension.service`
8. `systemctl enable + restart`

### systemd сервис
```ini
[Unit]
Description=HH Extension Backend
After=network.target postgresql.service

[Service]
WorkingDirectory=/opt/hh-extension
ExecStart=/opt/hh-extension/venv/bin/python main.py
Restart=always
RestartSec=5
```

### main.py — архитектура запуска
```python
asyncio.gather(
    uvicorn.serve(app, port=8000),  # FastAPI API
    run_scheduler()                  # Краулер
)
```

---

## 10. Нюансы и особенности

### Salary logic
- Сравнение с рынком только для RUR
- Если обе границы указаны → используется среднее (avg)
- Если одна граница → сравнивается именно она (from или to)
- Фильтр: salary > 10000 (убирает мусор)

### Remote detection
- Два источника: `schedule` (старое поле hh.ru) и `work_format` (новое)
- `is_remote = True` если хотя бы один из них содержит remote

### Race conditions (popup.js)
- `_renderToken` инкрементируется на каждый рендер
- Старый рендер проверяет token перед обновлением DOM и отбрасывается при несовпадении

### Lazy loading
- Отзывы загружаются только при первом клике на таб "Отзывы"
- `loadCompany()` выполняется после основного рендера, не блокирует UI

### Chrome storage keys
- `uuid` — генерируется один раз навсегда
- `voted_reviews` — объект `{review_id: vote_type}`
- `admin_token` — токен для модерации

### Closing time фильтр
- Учитываются только вакансии, которые были активны >= 3 дней
- Исключает вакансии, скрытые в день публикации (дубли, ошибки)

### Aggregate rates в отзывах
- `offer_rate` — process_status LIKE 'offer%' (accepted + declined + revoked)
- `ghost_rate` — process_status = 'ghosted'
- `reject_rate` — process_status = 'rejected'

### CORS
- Backend открыт для всех источников (`allow_origins=["*"]`)
- Разрешены методы: GET, POST, DELETE, PATCH

### Производительность
- asyncpg пул: min=2, max=10
- PERCENTILE_CONT вместо ORDER BY LIMIT
- TCPConnector(limit=5) в краулере
- Параллельная загрузка 5 запросов при открытии popup
