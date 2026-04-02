"""
hh.ru dictionaries cache.
Fetches /dictionaries once at startup, validates expected fields exist,
provides lookup helpers used by the crawler.
"""
import logging
import aiohttp
from config import HH_API_BASE, HH_USER_AGENT

log = logging.getLogger(__name__)

_cache: dict | None = None
_roles: dict[str, str] = {}  # id -> name

HEADERS = {
    "User-Agent": HH_USER_AGENT,
    "HH-User-Agent": HH_USER_AGENT,
}


async def load(session: aiohttp.ClientSession) -> None:
    """Fetch /dictionaries and /professional_roles. Call once at crawler startup."""
    global _cache, _roles
    try:
        async with session.get(
            f"{HH_API_BASE}/dictionaries",
            headers=HEADERS,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            resp.raise_for_status()
            _cache = await resp.json()
        _validate()
        log.info("hh.ru dictionaries loaded OK")
    except Exception as e:
        log.error(f"Failed to load hh.ru dictionaries: {e}. Using fallback values.")
        _cache = {}

    try:
        async with session.get(
            f"{HH_API_BASE}/professional_roles",
            headers=HEADERS,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
        _roles = {
            role["id"]: role["name"]
            for cat in data.get("categories", [])
            for role in cat.get("roles", [])
        }
        log.info(f"Loaded {len(_roles)} professional roles")
    except Exception as e:
        log.error(f"Failed to load professional roles: {e}")
        _roles = {}


def _validate() -> None:
    """Warn if expected ids disappear from dictionaries (API changed)."""
    issues = []

    remote_sched = get_remote_schedule_ids()
    if not remote_sched:
        issues.append("schedule: no remote id found")

    remote_fmt = get_remote_work_format_ids()
    if not remote_fmt:
        issues.append("work_format: no remote id found")

    exp_ids = {e["id"] for e in (_cache or {}).get("experience", [])}
    for expected in ("noExperience", "between1And3", "between3And6", "moreThan6"):
        if expected not in exp_ids:
            issues.append(f"experience: missing id '{expected}'")

    if issues:
        log.warning(f"hh.ru API dictionary changes detected: {issues}")
    else:
        log.info(
            f"Dictionaries validated. remote_schedule={remote_sched} "
            f"remote_work_format={remote_fmt}"
        )


def get_remote_schedule_ids() -> set[str]:
    """IDs in schedule[] that mean remote work (by name match)."""
    if not _cache:
        return {"remote"}  # fallback
    return {
        e["id"]
        for e in _cache.get("schedule", [])
        if "удал" in e.get("name", "").lower()
    }


def get_remote_work_format_ids() -> set[str]:
    """IDs in work_format[] that mean remote work (by name match)."""
    if not _cache:
        return {"REMOTE"}  # fallback
    return {
        e["id"]
        for e in _cache.get("work_format", [])
        if "удал" in e.get("name", "").lower()
    }


def get_role_names() -> dict[str, str]:
    """Returns {id: name} map for all professional roles."""
    return _roles


def is_remote_vacancy(schedule_id: str | None, work_format_ids: list[str]) -> bool:
    """
    Returns True if vacancy allows remote work.
    Checks both old (schedule) and new (work_format) fields.
    """
    remote_sched = get_remote_schedule_ids()
    remote_fmt = get_remote_work_format_ids()
    return (
        (schedule_id or "") in remote_sched
        or any(f in remote_fmt for f in work_format_ids)
    )
