# Contributing

## Локальная разработка

### Расширение

1. Клонируй репо
2. Открой `chrome://extensions` → режим разработчика → загрузить распакованное → папка `extension/`
3. После изменений в JS/CSS — нажми кнопку обновления у расширения в `chrome://extensions`

Расширение по умолчанию обращается к продакшен API (`moiraidrone.fvds.ru`). Для разработки с локальным backend замени `API` в начале `extension/popup.js` и `extension/content.js` на `http://localhost:8000/hh`.

### Backend

**Требования:** Python 3.10+, PostgreSQL 12+

```bash
cd backend

# Создай и активируй виртуальное окружение
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Установи зависимости
pip install -r requirements.txt

# Настрой окружение
cp .env.example .env
# Отредактируй .env — укажи DATABASE_URL и ADMIN_TOKEN
```

**Настройка PostgreSQL:**
```sql
CREATE USER hhuser WITH PASSWORD 'yourpassword';
CREATE DATABASE hhdb OWNER hhuser;
```

**Запуск:**
```bash
python main.py
```

API будет доступен на `http://localhost:8000`. Структура БД создаётся автоматически. Краулер запустится через 24 часа после первого старта (или перезапусти вручную через `crawler.py`).

### Деплой

```bash
cp .env.deploy.example .env.deploy
# Заполни DEPLOY_HOST, DEPLOY_USER, DEPLOY_PASS

python deploy.py
```

## Pull Requests

- Одна задача — один PR
- Проверь что нет секретов в коде (пароли, токены, IP)
- Для новых API endpoints — добавь соответствующую функцию в `database.py`
