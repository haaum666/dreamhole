"""Export quest-bot stats from Baserow to Excel."""
import httpx
import openpyxl
from datetime import datetime

BASEROW_TOKEN = 'loQZyspHtcWuMOHVEyvjI3YwfoeqgE67'
BASEROW_API_URL = 'https://api.baserow.io/api'
TABLE_STATS = 901473

HEADERS = {'Authorization': f'Token {BASEROW_TOKEN}'}

COLUMNS = [
    ('field_7805776', 'chat_id'),
    ('field_7805777', 'username'),
    ('field_7805778', 'date'),
    ('field_7805779', 'city'),
    ('field_7805780', 'journey_score'),
    ('field_7805781', 'quest_score'),
    ('field_7805782', 'code_collected'),
    ('field_7805783', 'completed'),
    ('field_7839055', 'maskirovka_photo_url'),
    ('field_7839056', 'story_photo_url'),
]

def fetch_all_rows():
    rows = []
    page = 1
    while True:
        url = f'{BASEROW_API_URL}/database/rows/table/{TABLE_STATS}/?user_field_names=false&size=200&page={page}'
        r = httpx.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        data = r.json()
        rows.extend(data['results'])
        print(f'  Загружено: {len(rows)} строк...')
        if not data.get('next'):
            break
        page += 1
    return rows

def export_to_excel(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Stats'

    # Header
    ws.append([col[1] for col in COLUMNS])

    # Data
    for row in rows:
        ws.append([row.get(col[0], '') for col in COLUMNS])

    # Auto column width
    for col in ws.columns:
        max_len = max((len(str(cell.value or '')) for cell in col), default=10)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 50)

    filename = f'quest_stats_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    wb.save(filename)
    return filename

print('Загружаю данные из Baserow...')
rows = fetch_all_rows()
print(f'Всего строк: {len(rows)}')
filename = export_to_excel(rows)
print(f'Сохранено: {filename}')
