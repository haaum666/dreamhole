import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
HH_API_BASE = "https://api.hh.ru"
HH_USER_AGENT = "hh-insights-extension/1.0 (contact@yourdomain.com)"

# IT/Digital professional role IDs on hh.ru
# Fetch fresh list: GET https://api.hh.ru/professional_roles
IT_DIGITAL_ROLE_IDS = [
    # Разработка
    "96", "156", "160", "164", "116", "148", "150", "151", "152", "157",
    "158", "159", "161", "163", "165", "166", "167", "168", "172", "173",
    # DevOps / Администрирование
    "114", "124", "125", "126", "155",
    # Тестирование
    "104", "105", "106",
    # Аналитика
    "10", "11", "12", "148", "164",
    # Data Science / ML
    "165", "171",
    # Дизайн
    "34", "36", "270",
    # Продукт / Проект
    "73", "107", "112",
    # Маркетинг (digital)
    "3", "4", "5", "6", "7",
    # Техподдержка
    "121", "122",
]

CRAWL_INTERVAL_HOURS = 24
MAX_VACANCIES_PER_CRAWL = 200_000
API_PORT = 8000
