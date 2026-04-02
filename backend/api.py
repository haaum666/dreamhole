"""
FastAPI server — serves insights to the Chrome extension.
"""
import logging
import re
from datetime import datetime, timezone
import aiohttp
from fastapi import FastAPI, HTTPException, Query, Header
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

from config import DATABASE_URL, ADMIN_TOKEN
import hh_dicts
from database import (
    get_pool, init_db,
    get_vacancy_insights,
    get_salary_stats,
    get_salary_median_for_comparison,
    get_company_profile,
    get_hiring_trend,
    get_competition_count,
    get_median_closing_time,
    get_vacancy_changes,
    get_crawler_status,
    update_vacancy_published_at,
    get_salary_transparency,
    get_company_reopen_stats,
    insert_review,
    get_reviews,
    get_reviews_aggregate,
    flag_review,
    vote_review,
    delete_review,
    update_review,
    get_reviews_stats,
)

log = logging.getLogger(__name__)
app = FastAPI(title="HH Insights API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    pool = await get_pool(DATABASE_URL)
    await init_db(pool)
    log.info("API ready")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/vacancy/{vacancy_id}")
async def vacancy_insights(vacancy_id: int):
    pool = await get_pool(DATABASE_URL)
    v = await get_vacancy_insights(pool, vacancy_id)
    if not v:
        raise HTTPException(status_code=404, detail="Vacancy not found in DB yet")

    # Fetch published_at on-demand from hh.ru if missing
    if not v["published_at"]:
        hh_data = await _fetch_hh_vacancy(vacancy_id)
        if hh_data and hh_data.get("published_at"):
            try:
                ts = re.sub(r"([+-])(\d{2})(\d{2})$", r"\1\2:\3", hh_data["published_at"])
                published_at = datetime.fromisoformat(ts)
                await update_vacancy_published_at(pool, vacancy_id, published_at)
                v = await get_vacancy_insights(pool, vacancy_id)
            except Exception as e:
                log.warning(f"Failed to parse published_at: {e}")

    is_remote = bool(v.get("is_remote"))
    now = datetime.now(timezone.utc)

    # Age block
    initial = v.get("initial_created_at")
    published = v.get("published_at")
    first_seen = v.get("first_seen_at")

    if initial:
        age_total_days = (now - initial).days
    elif first_seen:
        age_total_days = (now - first_seen).days
    else:
        age_total_days = None

    days_since_boost = (now - published).days if published else None

    # Closing time median
    closing_time = {}
    if v.get("experience_id") and v.get("professional_roles"):
        ct = await get_median_closing_time(
            pool,
            v["experience_id"],
            v["professional_roles"],
        )
        if ct.get("median_days") and ct.get("sample_size"):
            closing_time = {
                "median_days": round(ct["median_days"]),
                "sample_size": ct["sample_size"],
            }

    # Competition count — all similar vacancies regardless of location
    competition_count = None
    if v.get("professional_roles"):
        competition_count = await get_competition_count(
            pool, v["professional_roles"]
        )

    # % вакансий с указанной зарплатой по роли
    salary_transparency = None
    if v.get("professional_roles"):
        salary_transparency = await get_salary_transparency(pool, v["professional_roles"])

    # Повторные открытия вакансии компанией
    reopen_stats = None
    if v.get("company_id") and v.get("experience_id") and v.get("professional_roles"):
        reopen_stats = await get_company_reopen_stats(
            pool, v["company_id"], v["experience_id"], v["professional_roles"]
        )

    # Salary + market comparison
    sf, st = v.get("salary_from"), v.get("salary_to")
    salary_market = None
    if v.get("experience_id") and v.get("professional_roles") and v.get("salary_currency") == "RUR":
        if sf and st:
            vac_value = (sf + st) / 2
            salary_type = "avg"
        elif sf:
            vac_value = sf
            salary_type = "from"
        elif st:
            vac_value = st
            salary_type = "to"
        else:
            vac_value = None
            salary_type = None

        if vac_value and salary_type:
            stats = await get_salary_median_for_comparison(
                pool,
                v["experience_id"],
                v.get("area"),
                v["professional_roles"],
                is_remote,
                salary_type,
            )
            if stats.get("median") and stats.get("sample_size"):
                median = stats["median"]
                ratio = vac_value / median
                if ratio < 0.85:
                    label = "ниже рынка"
                elif ratio > 1.15:
                    label = "выше рынка"
                else:
                    label = "на уровне рынка"
                salary_market = {
                    "median": int(median),
                    "sample_size": stats["sample_size"],
                    "label": label,
                    "salary_type": salary_type,
                }

    return {
        "vacancy_id": vacancy_id,
        "is_active": v["is_active"],
        "area": v.get("area"),
        "professional_roles": v.get("professional_roles", []),
        "is_remote": is_remote,
        "age": {
            "age_total_days": age_total_days,
            "days_since_boost": days_since_boost,
            "initial_created_at": initial.isoformat() if initial else None,
            "last_boosted_at": published.isoformat() if published else None,
        },
        "closing_time": closing_time,
        "competition": {
            "count": competition_count,
            "salary_transparency": salary_transparency,
        },
        "reopen": reopen_stats,
        "salary": {
            "from": sf,
            "to": st,
            "currency": v.get("salary_currency"),
            "market": salary_market,
        },
    }


@app.get("/vacancy/{vacancy_id}/history")
async def vacancy_history(vacancy_id: int):
    pool = await get_pool(DATABASE_URL)
    changes = await get_vacancy_changes(pool, vacancy_id)
    return [
        {
            "changed_at": c["changed_at"].isoformat(),
            "field": c["field"],
            "old_value": c["old_value"],
            "new_value": c["new_value"],
        }
        for c in changes
    ]


@app.get("/salary")
async def salary_stats(experience_id: str, area: str, roles: str):
    pool = await get_pool(DATABASE_URL)
    role_list = [r.strip() for r in roles.split(",") if r.strip()]
    stats = await get_salary_stats(pool, experience_id, area, role_list)
    if not stats or not stats.get("sample_size"):
        raise HTTPException(status_code=404, detail="Not enough salary data")
    return {
        "p25": int(stats["p25"]) if stats.get("p25") else None,
        "median": int(stats["median"]) if stats.get("median") else None,
        "p75": int(stats["p75"]) if stats.get("p75") else None,
        "sample_size": stats.get("sample_size", 0),
        "area": area,
        "experience_id": experience_id,
    }


@app.get("/company/{company_id}")
async def company_profile(
    company_id: int,
    roles: str = Query(default=""),
    area: str = Query(default=""),
    is_remote: bool = Query(default=False),
):
    pool = await get_pool(DATABASE_URL)
    profile = await get_company_profile(pool, company_id)

    # Active vacancies count from hh.ru directly (accurate number)
    active_vacancies = await _fetch_hh_employer_vacancies_count(company_id)

    role_list = [r.strip() for r in roles.split(",") if r.strip()] if roles else None
    trend = await get_hiring_trend(
        pool,
        company_id,
        professional_roles=role_list or None,
        area=area or None,
        is_remote=is_remote,
    )

    return {
        "company_id": company_id,
        "active_vacancies": active_vacancies,
        **profile,
        "trend": trend,
    }


@app.get("/crawler/status")
async def crawler_status():
    pool = await get_pool(DATABASE_URL)
    return await get_crawler_status(pool)


@app.get("/stats")
async def db_stats():
    pool = await get_pool(DATABASE_URL)
    row = await pool.fetchrow("""
        SELECT
            COUNT(*) AS total_vacancies,
            COUNT(*) FILTER (WHERE is_active = TRUE) AS active_vacancies,
            COUNT(*) FILTER (WHERE is_active = FALSE) AS archived_vacancies,
            MIN(first_seen_at)::date AS crawl_started,
            MAX(last_seen_at)::date AS last_crawl
        FROM vacancies
    """)
    companies = await pool.fetchval("SELECT COUNT(*) FROM companies")
    changes = await pool.fetchval("SELECT COUNT(*) FROM vacancy_changes")
    return {
        "total_vacancies": row["total_vacancies"],
        "active_vacancies": row["active_vacancies"],
        "archived_vacancies": row["archived_vacancies"],
        "companies": companies,
        "changes_tracked": changes,
        "crawl_started": row["crawl_started"].isoformat() if row["crawl_started"] else None,
        "last_crawl": row["last_crawl"].isoformat() if row["last_crawl"] else None,
    }


@app.get("/roles")
async def professional_roles():
    return hh_dicts.get_role_names()


# ── Reviews ───────────────────────────────────────────────────────────────────

class ReviewIn(BaseModel):
    company_id: int
    company_name: str
    role_category: str | None = None
    stages: list[str] = []
    test_task_status: str | None = None
    process_status: str
    stopped_at_stage: str | None = None
    difficulty: int | None = None
    hr_rating: int | None = None
    duration_range: str | None = None
    comment: str | None = None
    questions: str | None = None
    user_hash: str


@app.post("/reviews")
async def submit_review(body: ReviewIn):
    pool = await get_pool(DATABASE_URL)
    result = await insert_review(pool, body.dict())
    if "error" in result:
        if result["error"] == "duplicate":
            raise HTTPException(409, "Вы уже оставляли отзыв об этой компании")
        if result["error"] == "rate_limit":
            raise HTTPException(429, "Слишком много отзывов за сутки")
    return result


@app.get("/reviews/{company_id}")
async def company_reviews(company_id: int):
    pool = await get_pool(DATABASE_URL)
    reviews = await get_reviews(pool, company_id)
    aggregate = await get_reviews_aggregate(pool, company_id)
    for r in reviews:
        if r.get("submitted_at"):
            r["submitted_at"] = r["submitted_at"].isoformat()
    return {"aggregate": aggregate, "reviews": reviews}


@app.post("/reviews/{review_id}/flag")
async def flag_review_endpoint(review_id: int):
    pool = await get_pool(DATABASE_URL)
    ok = await flag_review(pool, review_id)
    if not ok:
        raise HTTPException(404, "Отзыв не найден")
    return {"ok": True}


class VoteIn(BaseModel):
    user_hash: str


@app.post("/reviews/{review_id}/vote/{vote}")
async def vote_review_endpoint(review_id: int, vote: str, body: VoteIn):
    if vote not in ("like", "dislike", "fire", "poop", "clown"):
        raise HTTPException(400, "vote должен быть 'like', 'dislike', 'fire', 'poop' или 'clown'")
    pool = await get_pool(DATABASE_URL)
    result = await vote_review(pool, review_id, vote, body.user_hash)
    if not result:
        raise HTTPException(404, "Отзыв не найден")
    if result.get("error") == "duplicate":
        raise HTTPException(409, "Вы уже реагировали на этот отзыв")
    return result


@app.get("/health")
async def health():
    return {"status": "ok"}


# ── Reviews stats ─────────────────────────────────────────────────────────────

@app.get("/reviews/stats")
async def reviews_stats():
    pool = await get_pool(DATABASE_URL)
    return await get_reviews_stats(pool)


# ── Admin ─────────────────────────────────────────────────────────────────────

def _check_admin(token: str | None):
    if not ADMIN_TOKEN or token != ADMIN_TOKEN:
        raise HTTPException(403, "Forbidden")


class ReviewPatch(BaseModel):
    process_status: str | None = None
    stopped_at_stage: str | None = None
    role_category: str | None = None
    stages: list[str] | None = None
    test_task_status: str | None = None
    difficulty: int | None = None
    hr_rating: int | None = None
    duration_range: str | None = None
    comment: str | None = None
    questions: str | None = None
    is_flagged: bool | None = None


@app.delete("/admin/reviews/{review_id}")
async def admin_delete_review(review_id: int, x_admin_token: str | None = Header(default=None)):
    _check_admin(x_admin_token)
    pool = await get_pool(DATABASE_URL)
    ok = await delete_review(pool, review_id)
    if not ok:
        raise HTTPException(404, "Отзыв не найден")
    return {"ok": True}


@app.patch("/admin/reviews/{review_id}")
async def admin_update_review(
    review_id: int,
    body: ReviewPatch,
    x_admin_token: str | None = Header(default=None),
):
    _check_admin(x_admin_token)
    pool = await get_pool(DATABASE_URL)
    result = await update_review(pool, review_id, body.dict(exclude_none=True))
    if not result:
        raise HTTPException(404, "Отзыв не найден")
    return {"ok": True}


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _fetch_hh_vacancy(vacancy_id: int) -> dict:
    try:
        headers = {"User-Agent": "HHInsights/1.0 (analytics)"}
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://api.hh.ru/vacancies/{vacancy_id}",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
    except Exception:
        pass
    return {}


async def _fetch_hh_employer_vacancies_count(employer_id: int) -> int | None:
    try:
        headers = {"User-Agent": "HHInsights/1.0 (analytics)"}
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://api.hh.ru/employers/{employer_id}",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("open_vacancies")
    except Exception:
        pass
    return None
