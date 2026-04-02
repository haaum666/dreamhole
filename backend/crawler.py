"""
Daily crawler for hh.ru IT/Digital vacancies.
Runs once per day, fetches all active vacancies, upserts to DB,
marks missing ones as archived.
"""
import asyncio
import aiohttp
import logging
from datetime import datetime
from typing import AsyncIterator

from config import HH_API_BASE, HH_USER_AGENT, IT_DIGITAL_ROLE_IDS
from database import (
    upsert_company, upsert_vacancy, mark_archived, get_pool,
    get_vacancy_snapshot, insert_vacancy_change,
    start_crawler_run, finish_crawler_run, update_crawler_progress,
)
from config import DATABASE_URL
import hh_dicts

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": HH_USER_AGENT,
    "HH-User-Agent": HH_USER_AGENT,
}


def _parse_salary(salary: dict | None) -> tuple[int | None, int | None, str | None]:
    if not salary:
        return None, None, None
    return salary.get("from"), salary.get("to"), salary.get("currency")


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        # Python 3.10 fromisoformat doesn't support +HHMM (without colon)
        # hh.ru returns e.g. "2026-04-02T09:44:17+0300" — normalize to +03:00
        import re as _re
        normalized = _re.sub(r'([+-])(\d{2})(\d{2})$', r'\1\2:\3', value)
        return datetime.fromisoformat(normalized)
    except Exception:
        return None


def _parse_vacancy(item: dict) -> dict:
    salary_from, salary_to, currency = _parse_salary(item.get("salary"))
    employer = item.get("employer") or {}
    area = item.get("area") or {}
    experience = item.get("experience") or {}
    employment = item.get("employment") or {}
    schedule = item.get("schedule") or {}
    roles = [r["id"] for r in item.get("professional_roles") or []]

    # Новые поля hh.ru (присутствуют одновременно со старыми)
    work_format_ids = [f["id"] for f in item.get("work_format") or []]
    employment_form = (item.get("employment_form") or {}).get("id")

    schedule_id = schedule.get("id")
    is_remote = hh_dicts.is_remote_vacancy(schedule_id, work_format_ids)

    # employment: берём новое поле если есть, иначе старое
    effective_employment = employment_form or employment.get("id")

    # initial_created_at не приходит в list API — используем created_at
    initial_created_at = _parse_dt(
        item.get("initial_created_at") or item.get("created_at")
    )

    return {
        "id": int(item["id"]),
        "title": item.get("name", ""),
        "company_id": int(employer["id"]) if employer.get("id") else None,
        "company_name": employer.get("name"),
        "salary_from": salary_from,
        "salary_to": salary_to,
        "salary_currency": currency,
        "experience_id": experience.get("id"),
        "employment_id": effective_employment,
        "schedule_id": schedule_id,
        "is_remote": is_remote,
        "area": area.get("name"),
        "professional_roles": roles,
        "published_at": _parse_dt(item.get("published_at")),
        "initial_created_at": initial_created_at,
    }


def _parse_company(item: dict) -> dict | None:
    employer = item.get("employer") or {}
    if not employer.get("id"):
        return None
    area = item.get("area") or {}
    return {
        "id": int(employer["id"]),
        "name": employer.get("name", ""),
        "site_url": employer.get("alternate_url"),
        "area": area.get("name"),
        "trusted": employer.get("trusted", False),
    }


def _fmt_salary(sf, st) -> str:
    if sf and st: return f"{sf}/{st}"
    if sf:        return f"{sf}/"
    if st:        return f"/{st}"
    return ""


def _detect_changes(old: dict, new: dict) -> list[tuple[str, str | None, str | None]]:
    changes = []

    # Salary
    old_sf, old_st = old.get("salary_from"), old.get("salary_to")
    new_sf, new_st = new.get("salary_from"), new.get("salary_to")
    if (old_sf, old_st) != (new_sf, new_st):
        changes.append(("salary", _fmt_salary(old_sf, old_st), _fmt_salary(new_sf, new_st)))

    # Boost — published_at date changed
    old_pub = old.get("published_at")
    new_pub = new.get("published_at")
    if old_pub and new_pub:
        old_date = old_pub.date() if hasattr(old_pub, "date") else None
        new_date = new_pub.date() if hasattr(new_pub, "date") else None
        if old_date and new_date and old_date != new_date:
            changes.append(("boost", str(old_pub), str(new_pub)))

    # Title
    if old.get("title") != new.get("title"):
        changes.append(("title", old.get("title"), new.get("title")))

    # Experience requirements
    if old.get("experience_id") != new.get("experience_id"):
        changes.append(("experience", old.get("experience_id"), new.get("experience_id")))

    # Work format (employment + schedule combined)
    def _clean(v): return "" if (not v or v == "None") else v
    old_fmt = f"{_clean(old.get('employment_id'))}/{_clean(old.get('schedule_id'))}"
    new_fmt = f"{_clean(new.get('employment_id'))}/{_clean(new.get('schedule_id'))}"
    if old_fmt != new_fmt and new_fmt != "/":
        changes.append(("format", old_fmt, new_fmt))

    # Professional roles
    old_roles = set(old.get("professional_roles") or [])
    new_roles = set(new.get("professional_roles") or [])
    if old_roles != new_roles:
        changes.append((
            "roles",
            ",".join(sorted(old_roles)),
            ",".join(sorted(new_roles)),
        ))

    return changes


async def fetch_vacancies_page(
    session: aiohttp.ClientSession,
    role_id: str,
    page: int,
) -> tuple[list[dict], int]:
    params = {
        "professional_role": role_id,
        "per_page": 100,
        "page": page,
        "only_with_salary": "false",
        "order_by": "publication_time",
    }
    for attempt in range(3):
        async with session.get(f"{HH_API_BASE}/vacancies", params=params, headers=HEADERS) as resp:
            if resp.status == 429:
                wait = 60 * (attempt + 1)
                log.warning(f"Rate limited (attempt {attempt + 1}), sleeping {wait}s")
                await asyncio.sleep(wait)
                continue
            if resp.status != 200:
                log.error(f"HTTP {resp.status} for role {role_id} page {page}")
                return [], -1  # -1 = hard error, stop this role
            data = await resp.json()
            return data.get("items", []), data.get("pages", 0)
    log.error(f"Role {role_id} page {page} failed after 3 attempts (rate limit)")
    return [], -1


async def crawl_role(
    session: aiohttp.ClientSession,
    role_id: str,
) -> AsyncIterator[dict]:
    page = 0
    total_pages = 1
    while page < total_pages and page < 20:  # hh limits to 2000 results per query
        items, total_pages = await fetch_vacancies_page(session, role_id, page)
        if total_pages == -1:  # hard error — stop this role, continue others
            log.warning(f"Stopping role {role_id} at page {page} due to error")
            return
        for item in items:
            yield item
        page += 1
        await asyncio.sleep(0.3)  # be polite


async def run_crawl():
    pool = await get_pool(DATABASE_URL)
    run_id = await start_crawler_run(pool)
    seen_ids: set[int] = set()

    try:
        connector = aiohttp.TCPConnector(limit=5)
        async with aiohttp.ClientSession(connector=connector) as session:
            await hh_dicts.load(session)
            for role_id in IT_DIGITAL_ROLE_IDS:
                log.info(f"Crawling role {role_id}...")
                count = 0
                async for item in crawl_role(session, role_id):
                    try:
                        company = _parse_company(item)
                        if company:
                            await upsert_company(pool, company)

                        vacancy = _parse_vacancy(item)

                        old = await get_vacancy_snapshot(pool, vacancy["id"])
                        if old:
                            for field, old_val, new_val in _detect_changes(old, vacancy):
                                await insert_vacancy_change(pool, vacancy["id"], field, old_val, new_val)

                        await upsert_vacancy(pool, vacancy)
                        seen_ids.add(vacancy["id"])
                        count += 1

                        if len(seen_ids) % 500 == 0:
                            await update_crawler_progress(pool, run_id, len(seen_ids))
                    except Exception as e:
                        log.error(f"Failed to process vacancy {item.get('id')}: {e}")

                log.info(f"Role {role_id}: {count} vacancies processed")
                await asyncio.sleep(1)

        # Mark vacancies not seen today as archived
        active_ids = await pool.fetch(
            "SELECT id FROM vacancies WHERE is_active = TRUE"
        )
        active_set = {r["id"] for r in active_ids}
        archived = list(active_set - seen_ids)
        if archived:
            await mark_archived(pool, archived)
            log.info(f"Marked {len(archived)} vacancies as archived")

    finally:
        await finish_crawler_run(pool, run_id, len(seen_ids))
        log.info(f"Crawl complete. Total seen: {len(seen_ids)}")


async def run_scheduler():
    """Run crawl once immediately, then every 24 hours."""
    while True:
        log.info("Starting crawl...")
        try:
            await run_crawl()
        except Exception as e:
            log.error(f"Crawl failed: {e}", exc_info=True)
        log.info("Next crawl in 24 hours")
        await asyncio.sleep(24 * 3600)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
    )
    asyncio.run(run_scheduler())
