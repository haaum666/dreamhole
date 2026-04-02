import asyncpg
import logging
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)
_pool: asyncpg.Pool | None = None


async def get_pool(dsn: str) -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10)
    return _pool


async def init_db(pool: asyncpg.Pool):
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS companies (
                id          BIGINT PRIMARY KEY,
                name        TEXT NOT NULL,
                site_url    TEXT,
                area        TEXT,
                trusted     BOOLEAN DEFAULT FALSE,
                updated_at  TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS vacancies (
                id                  BIGINT PRIMARY KEY,
                title               TEXT NOT NULL,
                company_id          BIGINT REFERENCES companies(id),
                company_name        TEXT,
                salary_from         INTEGER,
                salary_to           INTEGER,
                salary_currency     TEXT,
                experience_id       TEXT,
                employment_id       TEXT,
                schedule_id         TEXT,
                is_remote           BOOLEAN DEFAULT FALSE,
                area                TEXT,
                professional_roles  TEXT[],
                published_at        TIMESTAMPTZ,
                initial_created_at  TIMESTAMPTZ,
                first_seen_at       TIMESTAMPTZ DEFAULT NOW(),
                last_seen_at        TIMESTAMPTZ DEFAULT NOW(),
                archived_at         TIMESTAMPTZ,
                is_active           BOOLEAN DEFAULT TRUE
            )
        """)

        # Migrations for existing tables
        await conn.execute("""
            ALTER TABLE vacancies ADD COLUMN IF NOT EXISTS initial_created_at TIMESTAMPTZ
        """)
        await conn.execute("""
            ALTER TABLE vacancies ADD COLUMN IF NOT EXISTS is_remote BOOLEAN DEFAULT FALSE
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS vacancy_daily (
                vacancy_id  BIGINT REFERENCES vacancies(id),
                seen_date   DATE DEFAULT CURRENT_DATE,
                is_active   BOOLEAN DEFAULT TRUE,
                PRIMARY KEY (vacancy_id, seen_date)
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS vacancy_changes (
                id          BIGSERIAL PRIMARY KEY,
                vacancy_id  BIGINT REFERENCES vacancies(id),
                changed_at  TIMESTAMPTZ DEFAULT NOW(),
                field       TEXT NOT NULL,
                old_value   TEXT,
                new_value   TEXT
            )
        """)

        # Indexes
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_vacancies_company ON vacancies(company_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_vacancies_published ON vacancies(published_at)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_vacancies_active ON vacancies(is_active)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_vacancies_area ON vacancies(area)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_vacancies_experience ON vacancies(experience_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_vacancies_initial ON vacancies(initial_created_at)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_vacancy_changes_vacancy ON vacancy_changes(vacancy_id)")

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS crawler_runs (
                id          BIGSERIAL PRIMARY KEY,
                started_at  TIMESTAMPTZ DEFAULT NOW(),
                finished_at TIMESTAMPTZ,
                vacancies_processed INTEGER DEFAULT 0
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS interview_reviews (
                id                BIGSERIAL PRIMARY KEY,
                company_id        BIGINT NOT NULL,
                company_name      TEXT NOT NULL,
                role_category     TEXT,
                stages            TEXT[],
                test_task_status  TEXT,
                process_status    TEXT NOT NULL,
                stopped_at_stage  TEXT,
                difficulty        SMALLINT,
                hr_rating         SMALLINT,
                duration_range    TEXT,
                comment           TEXT,
                questions         TEXT,
                user_hash         TEXT NOT NULL,
                likes             INTEGER DEFAULT 0,
                dislikes          INTEGER DEFAULT 0,
                is_flagged        BOOLEAN DEFAULT FALSE,
                flag_count        INTEGER DEFAULT 0,
                submitted_at      TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("ALTER TABLE interview_reviews ADD COLUMN IF NOT EXISTS likes INTEGER DEFAULT 0")
        await conn.execute("ALTER TABLE interview_reviews ADD COLUMN IF NOT EXISTS dislikes INTEGER DEFAULT 0")
        await conn.execute("ALTER TABLE interview_reviews ADD COLUMN IF NOT EXISTS fire INTEGER DEFAULT 0")
        await conn.execute("ALTER TABLE interview_reviews ADD COLUMN IF NOT EXISTS poop INTEGER DEFAULT 0")
        await conn.execute("ALTER TABLE interview_reviews ADD COLUMN IF NOT EXISTS clown INTEGER DEFAULT 0")

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS review_votes (
                user_hash  TEXT NOT NULL,
                review_id  BIGINT NOT NULL REFERENCES interview_reviews(id) ON DELETE CASCADE,
                vote       TEXT NOT NULL,
                voted_at   TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (user_hash, review_id)
            )
        """)

        await conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_reviews_user_company
            ON interview_reviews (user_hash, company_id)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_reviews_company
            ON interview_reviews (company_id)
        """)

        log.info("Database initialized")


# ── Upsert ────────────────────────────────────────────────────────────────────

async def upsert_company(pool: asyncpg.Pool, c: dict):
    await pool.execute("""
        INSERT INTO companies (id, name, site_url, area, trusted, updated_at)
        VALUES ($1, $2, $3, $4, $5, NOW())
        ON CONFLICT (id) DO UPDATE SET
            name = EXCLUDED.name,
            site_url = EXCLUDED.site_url,
            area = EXCLUDED.area,
            trusted = EXCLUDED.trusted,
            updated_at = NOW()
    """, c["id"], c["name"], c.get("site_url"), c.get("area"), c.get("trusted", False))


async def upsert_vacancy(pool: asyncpg.Pool, v: dict):
    await pool.execute("""
        INSERT INTO vacancies (
            id, title, company_id, company_name,
            salary_from, salary_to, salary_currency,
            experience_id, employment_id, schedule_id, is_remote,
            area, professional_roles, published_at, initial_created_at,
            first_seen_at, last_seen_at, is_active
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,NOW(),NOW(),TRUE)
        ON CONFLICT (id) DO UPDATE SET
            title = EXCLUDED.title,
            company_name = EXCLUDED.company_name,
            salary_from = EXCLUDED.salary_from,
            salary_to = EXCLUDED.salary_to,
            salary_currency = EXCLUDED.salary_currency,
            experience_id = EXCLUDED.experience_id,
            employment_id = EXCLUDED.employment_id,
            schedule_id = EXCLUDED.schedule_id,
            is_remote = EXCLUDED.is_remote,
            area = EXCLUDED.area,
            professional_roles = EXCLUDED.professional_roles,
            published_at = EXCLUDED.published_at,
            last_seen_at = NOW(),
            is_active = TRUE,
            archived_at = NULL
            -- initial_created_at intentionally NOT updated on conflict
    """,
        v["id"], v["title"], v.get("company_id"), v.get("company_name"),
        v.get("salary_from"), v.get("salary_to"), v.get("salary_currency"),
        v.get("experience_id"), v.get("employment_id"), v.get("schedule_id"),
        v.get("is_remote", False),
        v.get("area"), v.get("professional_roles", []), v.get("published_at"),
        v.get("initial_created_at"),
    )
    await pool.execute("""
        INSERT INTO vacancy_daily (vacancy_id, seen_date, is_active)
        VALUES ($1, CURRENT_DATE, TRUE)
        ON CONFLICT (vacancy_id, seen_date) DO NOTHING
    """, v["id"])


async def mark_archived(pool: asyncpg.Pool, vacancy_ids: list[int]):
    if not vacancy_ids:
        return
    await pool.execute("""
        UPDATE vacancies
        SET is_active = FALSE, archived_at = NOW()
        WHERE id = ANY($1) AND is_active = TRUE
    """, vacancy_ids)


# ── Change tracking ───────────────────────────────────────────────────────────

async def get_vacancy_snapshot(pool: asyncpg.Pool, vacancy_id: int) -> dict | None:
    row = await pool.fetchrow("""
        SELECT title, salary_from, salary_to, published_at,
               experience_id, employment_id, schedule_id, professional_roles
        FROM vacancies WHERE id = $1
    """, vacancy_id)
    return dict(row) if row else None


async def insert_vacancy_change(
    pool: asyncpg.Pool,
    vacancy_id: int,
    field: str,
    old_value: str | None,
    new_value: str | None,
):
    await pool.execute("""
        INSERT INTO vacancy_changes (vacancy_id, field, old_value, new_value)
        VALUES ($1, $2, $3, $4)
    """, vacancy_id, field, old_value, new_value)


async def get_vacancy_changes(pool: asyncpg.Pool, vacancy_id: int) -> list[dict]:
    rows = await pool.fetch("""
        SELECT changed_at, field, old_value, new_value
        FROM vacancy_changes
        WHERE vacancy_id = $1
        ORDER BY changed_at DESC
        LIMIT 50
    """, vacancy_id)
    return [dict(r) for r in rows]


# ── Read queries ──────────────────────────────────────────────────────────────

async def get_vacancy_insights(pool: asyncpg.Pool, vacancy_id: int) -> dict | None:
    row = await pool.fetchrow("""
        SELECT v.*, c.site_url, c.trusted
        FROM vacancies v
        LEFT JOIN companies c ON v.company_id = c.id
        WHERE v.id = $1
    """, vacancy_id)
    return dict(row) if row else None


async def get_salary_stats(
    pool: asyncpg.Pool,
    experience_id: str,
    area: str,
    professional_roles: list[str],
) -> dict:
    """Used by the /salary endpoint (extension page extraction path)."""
    row = await pool.fetchrow("""
        SELECT
            PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY s) AS p25,
            PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY s) AS median,
            PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY s) AS p75,
            COUNT(*) AS sample_size
        FROM (
            SELECT
                CASE
                    WHEN salary_from IS NOT NULL AND salary_to IS NOT NULL
                        THEN (salary_from + salary_to) / 2
                    WHEN salary_from IS NOT NULL THEN salary_from
                    ELSE salary_to
                END AS s
            FROM vacancies
            WHERE is_active = TRUE
              AND salary_currency = 'RUR'
              AND (salary_from IS NOT NULL OR salary_to IS NOT NULL)
              AND experience_id = $1
              AND area = $2
              AND professional_roles && $3
        ) sub
        WHERE s IS NOT NULL AND s > 10000
    """, experience_id, area, professional_roles)
    return dict(row) if row else {}


async def get_salary_median_for_comparison(
    pool: asyncpg.Pool,
    experience_id: str,
    area: str | None,
    professional_roles: list[str],
    is_remote: bool,
    salary_type: str,  # 'from', 'to', or 'avg'
) -> dict:
    # salary_type controls which field we compare — honest like-for-like comparison
    if salary_type == "from":
        select_expr = "salary_from"
        where_extra = "salary_from IS NOT NULL AND salary_from > 10000"
    elif salary_type == "to":
        select_expr = "salary_to"
        where_extra = "salary_to IS NOT NULL AND salary_to > 10000"
    else:  # avg — both boundaries provided
        select_expr = "(salary_from + salary_to) / 2.0"
        where_extra = "salary_from IS NOT NULL AND salary_to IS NOT NULL AND (salary_from + salary_to) / 2 > 10000"

    if is_remote:
        row = await pool.fetchrow(f"""
            SELECT
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY {select_expr}) AS median,
                COUNT(*) AS sample_size
            FROM vacancies
            WHERE is_active = TRUE
              AND salary_currency = 'RUR'
              AND {where_extra}
              AND schedule_id = 'remote'
              AND professional_roles && $1
              AND experience_id = $2
        """, professional_roles, experience_id)
    else:
        row = await pool.fetchrow(f"""
            SELECT
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY {select_expr}) AS median,
                COUNT(*) AS sample_size
            FROM vacancies
            WHERE is_active = TRUE
              AND salary_currency = 'RUR'
              AND {where_extra}
              AND area = $1
              AND professional_roles && $2
              AND experience_id = $3
        """, area, professional_roles, experience_id)
    return dict(row) if row else {}


async def get_competition_count(
    pool: asyncpg.Pool,
    professional_roles: list[str],
) -> int:
    return await pool.fetchval("""
        SELECT COUNT(*) FROM vacancies
        WHERE is_active = TRUE
          AND professional_roles && $1
    """, professional_roles) or 0


async def get_salary_transparency(
    pool: asyncpg.Pool,
    professional_roles: list[str],
) -> dict | None:
    """% активных вакансий по роли с указанной зарплатой."""
    row = await pool.fetchrow("""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE salary_from IS NOT NULL OR salary_to IS NOT NULL) AS with_salary
        FROM vacancies
        WHERE is_active = TRUE
          AND professional_roles && $1
    """, professional_roles)
    if not row or not row["total"]:
        return None
    return {
        "percent": round(row["with_salary"] * 100 / row["total"]),
        "sample_size": row["total"],
    }


async def get_company_reopen_stats(
    pool: asyncpg.Pool,
    company_id: int,
    experience_id: str,
    professional_roles: list[str],
) -> dict | None:
    """Сколько раз компания уже открывала похожую вакансию (текучка / фантомный найм)."""
    rows = await pool.fetch("""
        SELECT first_seen_at, archived_at
        FROM vacancies
        WHERE company_id = $1
          AND experience_id = $2
          AND professional_roles && $3
        ORDER BY first_seen_at
    """, company_id, experience_id, professional_roles)

    if len(rows) < 2:
        return None

    archived = [r for r in rows if r["archived_at"] is not None]
    if not archived:
        return None

    # Среднее время между открытиями одинаковых вакансий
    dates = [r["first_seen_at"] for r in rows]
    gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1) if (dates[i + 1] - dates[i]).days > 0]
    avg_gap = round(sum(gaps) / len(gaps)) if gaps else None

    return {
        "past_attempts": len(archived),
        "avg_reopen_days": avg_gap,
    }


async def get_median_closing_time(
    pool: asyncpg.Pool,
    experience_id: str,
    professional_roles: list[str],
) -> dict:
    row = await pool.fetchrow("""
        SELECT
            PERCENTILE_CONT(0.5) WITHIN GROUP (
                ORDER BY EXTRACT(EPOCH FROM (
                    archived_at - first_seen_at
                )) / 86400
            ) AS median_days,
            COUNT(*) AS sample_size
        FROM vacancies
        WHERE archived_at IS NOT NULL
          AND archived_at - first_seen_at >= INTERVAL '3 days'
          AND professional_roles && $1
          AND experience_id = $2
    """, professional_roles, experience_id)
    return dict(row) if row else {}


async def get_company_profile(pool: asyncpg.Pool, company_id: int) -> dict:
    total = await pool.fetchval(
        "SELECT COUNT(*) FROM vacancies WHERE company_id = $1", company_id
    )
    row = await pool.fetchrow("""
        SELECT
            PERCENTILE_CONT(0.5) WITHIN GROUP (
                ORDER BY EXTRACT(EPOCH FROM (
                    archived_at - first_seen_at
                )) / 86400
            ) AS ttf,
            COUNT(*) AS sample_size
        FROM vacancies
        WHERE company_id = $1
          AND archived_at IS NOT NULL
          AND archived_at - first_seen_at >= INTERVAL '3 days'
    """, company_id)
    return {
        "total_vacancies": total,
        "median_days_to_fill": round(row["ttf"], 1) if row and row["ttf"] else None,
        "median_sample_size": row["sample_size"] if row else 0,
    }


async def get_hiring_trend(
    pool: asyncpg.Pool,
    company_id: int,
    professional_roles: list[str] | None = None,
    area: str | None = None,
    is_remote: bool = False,
) -> dict:
    co = await pool.fetch("""
        SELECT TO_CHAR(DATE_TRUNC('month', first_seen_at), 'YYYY-MM') AS month,
               COUNT(*) AS count
        FROM vacancies
        WHERE company_id = $1 AND first_seen_at >= NOW() - INTERVAL '12 months'
        GROUP BY 1 ORDER BY 1
    """, company_id)
    cc = await pool.fetch("""
        SELECT TO_CHAR(DATE_TRUNC('month', archived_at), 'YYYY-MM') AS month,
               COUNT(*) AS count
        FROM vacancies
        WHERE company_id = $1 AND archived_at >= NOW() - INTERVAL '12 months'
        GROUP BY 1 ORDER BY 1
    """, company_id)

    company_map: dict = {}
    for r in co:
        company_map.setdefault(r["month"], {"month": r["month"], "opened": 0, "closed": 0})["opened"] = r["count"]
    for r in cc:
        company_map.setdefault(r["month"], {"month": r["month"], "opened": 0, "closed": 0})["closed"] = r["count"]

    market_data: list = []
    if professional_roles and (area or is_remote):
        if is_remote:
            mo = await pool.fetch("""
                SELECT TO_CHAR(DATE_TRUNC('month', first_seen_at), 'YYYY-MM') AS month,
                       COUNT(*) AS count
                FROM vacancies
                WHERE schedule_id = 'remote'
                  AND professional_roles && $1
                  AND first_seen_at >= NOW() - INTERVAL '12 months'
                GROUP BY 1 ORDER BY 1
            """, professional_roles)
            mc = await pool.fetch("""
                SELECT TO_CHAR(DATE_TRUNC('month', archived_at), 'YYYY-MM') AS month,
                       COUNT(*) AS count
                FROM vacancies
                WHERE schedule_id = 'remote'
                  AND professional_roles && $1
                  AND archived_at >= NOW() - INTERVAL '12 months'
                GROUP BY 1 ORDER BY 1
            """, professional_roles)
        else:
            mo = await pool.fetch("""
                SELECT TO_CHAR(DATE_TRUNC('month', first_seen_at), 'YYYY-MM') AS month,
                       COUNT(*) AS count
                FROM vacancies
                WHERE area = $1
                  AND professional_roles && $2
                  AND first_seen_at >= NOW() - INTERVAL '12 months'
                GROUP BY 1 ORDER BY 1
            """, area, professional_roles)
            mc = await pool.fetch("""
                SELECT TO_CHAR(DATE_TRUNC('month', archived_at), 'YYYY-MM') AS month,
                       COUNT(*) AS count
                FROM vacancies
                WHERE area = $1
                  AND professional_roles && $2
                  AND archived_at >= NOW() - INTERVAL '12 months'
                GROUP BY 1 ORDER BY 1
            """, area, professional_roles)

        market_map: dict = {}
        for r in mo:
            market_map.setdefault(r["month"], {"month": r["month"], "opened": 0, "closed": 0})["opened"] = r["count"]
        for r in mc:
            market_map.setdefault(r["month"], {"month": r["month"], "opened": 0, "closed": 0})["closed"] = r["count"]
        market_data = sorted(market_map.values(), key=lambda x: x["month"])

    return {
        "company": sorted(company_map.values(), key=lambda x: x["month"]),
        "market": market_data,
    }


async def start_crawler_run(pool: asyncpg.Pool) -> int:
    return await pool.fetchval(
        "INSERT INTO crawler_runs (started_at) VALUES (NOW()) RETURNING id"
    )


async def update_crawler_progress(pool: asyncpg.Pool, run_id: int, vacancies_processed: int):
    await pool.execute(
        "UPDATE crawler_runs SET vacancies_processed = $1 WHERE id = $2",
        vacancies_processed, run_id
    )


async def finish_crawler_run(pool: asyncpg.Pool, run_id: int, vacancies_processed: int):
    await pool.execute(
        "UPDATE crawler_runs SET finished_at = NOW(), vacancies_processed = $1 WHERE id = $2",
        vacancies_processed, run_id
    )


async def get_crawler_status(pool: asyncpg.Pool) -> dict:
    row = await pool.fetchrow("""
        SELECT started_at, finished_at, vacancies_processed
        FROM crawler_runs
        ORDER BY id DESC
        LIMIT 1
    """)
    if not row:
        return {"running": False, "last_run": None, "next_run": None, "vacancies_processed": 0}

    running = row["finished_at"] is None
    return {
        "running": running,
        "started_at": row["started_at"].isoformat(),
        "finished_at": row["finished_at"].isoformat() if row["finished_at"] else None,
        "vacancies_processed": row["vacancies_processed"],
    }


async def update_vacancy_published_at(pool: asyncpg.Pool, vacancy_id: int, published_at):
    await pool.execute(
        "UPDATE vacancies SET published_at = $1 WHERE id = $2",
        published_at, vacancy_id
    )


# ── Interview reviews ─────────────────────────────────────────────────────────

async def insert_review(pool: asyncpg.Pool, r: dict) -> dict:
    """Вставить отзыв. Возвращает {"ok": True} или {"error": "..."}."""
    # Антиспам: макс 3 отзыва за 24 часа с одного user_hash
    recent = await pool.fetchval("""
        SELECT COUNT(*) FROM interview_reviews
        WHERE user_hash = $1 AND submitted_at > NOW() - INTERVAL '24 hours'
    """, r["user_hash"])
    if recent >= 3:
        return {"error": "rate_limit"}

    # Дедупликация: один отзыв на компанию
    try:
        await pool.execute("""
            INSERT INTO interview_reviews (
                company_id, company_name, role_category,
                stages, test_task_status, process_status, stopped_at_stage,
                difficulty, hr_rating, duration_range,
                comment, questions, user_hash
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
        """,
            r["company_id"], r["company_name"], r.get("role_category"),
            r.get("stages", []), r.get("test_task_status"), r["process_status"],
            r.get("stopped_at_stage"), r.get("difficulty"), r.get("hr_rating"),
            r.get("duration_range"), r.get("comment"), r.get("questions"),
            r["user_hash"],
        )
    except Exception as e:
        if "idx_reviews_user_company" in str(e):
            return {"error": "duplicate"}
        raise
    return {"ok": True}


async def get_reviews(pool: asyncpg.Pool, company_id: int) -> list[dict]:
    rows = await pool.fetch("""
        SELECT id, role_category, stages, test_task_status, process_status,
               stopped_at_stage, difficulty, hr_rating, duration_range,
               comment, questions, submitted_at,
               likes, dislikes, fire, poop
        FROM interview_reviews
        WHERE company_id = $1 AND is_flagged = FALSE
        ORDER BY submitted_at DESC
        LIMIT 50
    """, company_id)
    return [dict(r) for r in rows]


async def get_reviews_aggregate(pool: asyncpg.Pool, company_id: int) -> dict | None:
    row = await pool.fetchrow("""
        SELECT
            COUNT(*)                                                        AS total,
            ROUND(AVG(difficulty), 1)                                       AS avg_difficulty,
            ROUND(AVG(hr_rating), 1)                                        AS avg_hr,
            COUNT(*) FILTER (WHERE process_status = 'ghosted')             AS ghosted,
            COUNT(*) FILTER (WHERE process_status LIKE 'offer%')           AS offers,
            COUNT(*) FILTER (WHERE process_status = 'rejected')            AS rejected
        FROM interview_reviews
        WHERE company_id = $1 AND is_flagged = FALSE
    """, company_id)
    if not row or not row["total"]:
        return None
    total = row["total"]
    return {
        "total": total,
        "avg_difficulty": float(row["avg_difficulty"]) if row["avg_difficulty"] else None,
        "avg_hr": float(row["avg_hr"]) if row["avg_hr"] else None,
        "ghost_rate": round(row["ghosted"] * 100 / total),
        "offer_rate": round(row["offers"] * 100 / total),
        "reject_rate": round(row["rejected"] * 100 / total),
    }


async def flag_review(pool: asyncpg.Pool, review_id: int) -> bool:
    result = await pool.execute("""
        UPDATE interview_reviews
        SET flag_count = flag_count + 1,
            is_flagged = (flag_count + 1 >= 5)
        WHERE id = $1
    """, review_id)
    return result == "UPDATE 1"


async def vote_review(pool: asyncpg.Pool, review_id: int, vote: str, user_hash: str) -> dict | None:
    """vote: 'like' | 'dislike' | 'fire' | 'poop' | 'clown'.
    Один голос на отзыв на пользователя. Возвращает новые счётчики или None при дубле."""
    col_map = {"like": "likes", "dislike": "dislikes", "fire": "fire", "poop": "poop", "clown": "clown"}
    col = col_map.get(vote)
    if not col:
        return None
    async with pool.acquire() as conn:
        async with conn.transaction():
            try:
                await conn.execute("""
                    INSERT INTO review_votes (user_hash, review_id, vote)
                    VALUES ($1, $2, $3)
                """, user_hash, review_id, vote)
            except Exception as e:
                if "unique" in str(e).lower() or "duplicate" in str(e).lower():
                    return {"error": "duplicate"}
                raise
            row = await conn.fetchrow(f"""
                UPDATE interview_reviews
                SET {col} = {col} + 1
                WHERE id = $1 AND is_flagged = FALSE
                RETURNING likes, dislikes, fire, poop, clown
            """, review_id)
    return dict(row) if row else None


async def delete_review(pool: asyncpg.Pool, review_id: int) -> bool:
    result = await pool.execute("DELETE FROM interview_reviews WHERE id = $1", review_id)
    return result == "DELETE 1"


async def update_review(pool: asyncpg.Pool, review_id: int, fields: dict) -> dict | None:
    allowed = {"process_status", "stopped_at_stage", "role_category", "stages",
               "test_task_status", "difficulty", "hr_rating", "duration_range",
               "comment", "questions", "is_flagged"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return None
    sets = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(updates))
    values = list(updates.values())
    row = await pool.fetchrow(
        f"UPDATE interview_reviews SET {sets} WHERE id = $1 RETURNING *",
        review_id, *values,
    )
    return dict(row) if row else None


async def get_reviews_stats(pool: asyncpg.Pool) -> dict:
    row = await pool.fetchrow("""
        SELECT
            COUNT(*)                                                        AS total,
            COUNT(DISTINCT company_id)                                      AS companies,
            COUNT(*) FILTER (WHERE process_status LIKE 'offer%')           AS offers,
            COUNT(*) FILTER (WHERE process_status = 'rejected')            AS rejected,
            COUNT(*) FILTER (WHERE process_status = 'ghosted')             AS ghosted,
            COUNT(*) FILTER (WHERE process_status = 'ongoing')             AS ongoing,
            ROUND(AVG(difficulty), 1)                                       AS avg_difficulty,
            ROUND(AVG(hr_rating), 1)                                        AS avg_hr
        FROM interview_reviews
        WHERE is_flagged = FALSE
    """)
    top = await pool.fetch("""
        SELECT company_name, COUNT(*) AS cnt
        FROM interview_reviews
        WHERE is_flagged = FALSE
        GROUP BY company_name
        ORDER BY cnt DESC
        LIMIT 5
    """)
    return {
        "total": row["total"],
        "companies": row["companies"],
        "offers": row["offers"],
        "rejected": row["rejected"],
        "ghosted": row["ghosted"],
        "ongoing": row["ongoing"],
        "avg_difficulty": float(row["avg_difficulty"]) if row["avg_difficulty"] else None,
        "avg_hr": float(row["avg_hr"]) if row["avg_hr"] else None,
        "top_companies": [{"name": r["company_name"], "count": r["cnt"]} for r in top],
    }
