const API = "https://moiraidrone.fvds.ru/hh";


// ── Utils ─────────────────────────────────────────────────────────────────────

function getVacancyId() {
  const m = location.pathname.match(/\/vacancy\/(\d+)/);
  return m ? m[1] : null;
}

function fmt(n) {
  if (!n) return "—";
  return Number(n).toLocaleString("ru-RU") + " ₽";
}

function fmtDays(days) {
  if (days === null || days === undefined) return "—";
  if (days === 0) return "сегодня";
  if (days === 1) return "1 день";
  if (days < 7) return `${days} дн.`;
  if (days < 30) return `${Math.round(days / 7)} нед.`;
  const months = Math.round(days / 30);
  return `${months} мес.`;
}

function fmtDate(isoStr) {
  const d = new Date(isoStr);
  return d.toLocaleDateString("ru-RU", { day: "numeric", month: "short" });
}

const EXP_LABELS = {
  noExperience: "без опыта",
  between1And3: "1–3 года",
  between3And6: "3–6 лет",
  moreThan6: "6+ лет",
};

const EMPLOYMENT_LABELS = {
  full: "полная занятость", part: "частичная", project: "проектная",
  volunteer: "волонтёрство", probation: "стажировка",
  FULL: "полная занятость", PART: "частичная", PROJECT: "проектная",
  VOLUNTEER: "волонтёрство", PROBATION: "стажировка", FLY_IN_FLY_OUT: "вахта",
  SIDE_JOB: "подработка",
};

const SCHEDULE_LABELS = {
  fullDay: "офис", shift: "сменный", flexible: "гибкий",
  remote: "удалёнка", flyInFlyOut: "вахта",
  REMOTE: "удалёнка", OFFICE: "офис", HYBRID: "гибрид",
  ON_SITE: "на месте", FULL_DAY: "полный день", FLEXIBLE: "гибкий",
  FIELD_WORK: "разъездной",
};

let _rolesCache = null;

async function loadRoles() {
  if (_rolesCache) return _rolesCache;
  try {
    const r = await fetch(API + "/roles");
    _rolesCache = r.ok ? await r.json() : {};
  } catch { _rolesCache = {}; }
  return _rolesCache;
}

function fmtSalaryVal(s) {
  if (!s) return "не указана";
  if (s.includes("/")) {
    const [a, b] = s.split("/");
    const from = a ? parseInt(a) : null;
    const to = b ? parseInt(b) : null;
    if (from && to) return `${from.toLocaleString("ru-RU")}–${to.toLocaleString("ru-RU")} ₽`;
    if (from) return `от ${from.toLocaleString("ru-RU")} ₽`;
    if (to) return `до ${to.toLocaleString("ru-RU")} ₽`;
  }
  const parts = s.split("-");
  const from = parts[0] && parts[0] !== "None" ? parseInt(parts[0]) : null;
  const to = parts[1] && parts[1] !== "None" ? parseInt(parts[1]) : null;
  if (from && to) return `${from.toLocaleString("ru-RU")}–${to.toLocaleString("ru-RU")} ₽`;
  if (from) return `от ${from.toLocaleString("ru-RU")} ₽`;
  if (to) return `до ${to.toLocaleString("ru-RU")} ₽`;
  return s;
}

function fmtFormat(val) {
  if (!val) return "не указано";
  const [emp, sch] = val.split("/");
  const parts = [];
  if (emp && emp !== "null" && emp !== "None") parts.push(EMPLOYMENT_LABELS[emp] || emp);
  if (sch && sch !== "null" && sch !== "None") parts.push(SCHEDULE_LABELS[sch] || sch);
  return parts.join(", ") || "не указано";
}

function fmtChange(c, roles = {}) {
  switch (c.field) {
    case "boost": {
      const d = c.new_value ? new Date(c.new_value).toLocaleDateString("ru-RU", { day: "numeric", month: "short" }) : "";
      return d ? `переподъём (${d})` : "переподъём вакансии";
    }
    case "salary":
      return `зарплата: ${fmtSalaryVal(c.old_value)} → ${fmtSalaryVal(c.new_value)}`;
    case "title":
      return `название: «${c.old_value}» → «${c.new_value}»`;
    case "experience":
      return `требования: ${EXP_LABELS[c.old_value] || c.old_value} → ${EXP_LABELS[c.new_value] || c.new_value}`;
    case "format":
      return `формат: ${fmtFormat(c.old_value)} → ${fmtFormat(c.new_value)}`;
    case "roles": {
      const fmt = ids => ids ? ids.split(",").filter(Boolean).map(id => roles[id] || id).join(", ") : "—";
      return `роли: ${fmt(c.old_value)} → ${fmt(c.new_value)}`;
    }
    default: return c.field;
  }
}

async function apiFetch(path) {
  try {
    const r = await fetch(API + path);
    if (!r.ok) return null;
    return await r.json();
  } catch {
    return null;
  }
}


// ── Vacancy page ──────────────────────────────────────────────────────────────

let _injecting = false;

async function injectVacancyPanel(vacancyId) {
  if (document.getElementById("hhi-main-panel")) return;
  if (_injecting) return;
  _injecting = true;

  const target =
    document.querySelector("[data-qa='vacancy-title']")?.closest("section") ||
    document.querySelector(".vacancy-title") ||
    document.querySelector("h1")?.parentElement;

  if (!target) { _injecting = false; return; }

  const panel = document.createElement("div");
  panel.className = "hhi-panel";
  panel.id = "hhi-main-panel";
  panel.innerHTML = `<h3>HH Insights</h3><div class="hhi-loading">Загружаю данные</div>`;
  target.after(panel);

  const data = await apiFetch(`/vacancy/${vacancyId}`);
  if (!data) {
    panel.querySelector(".hhi-loading").outerHTML =
      `<div class="hhi-error">Нет данных — вакансия ещё не в нашей базе.</div>`;
    _injecting = false;
    return;
  }

  const { age, closing_time, competition, salary } = data;

  // ── Age block ──
  let ageText = "";
  if (age.age_total_days !== null) {
    ageText = age.age_total_days === 0
      ? "Создана сегодня"
      : `Создана ${fmtDays(age.age_total_days)} назад`;
    if (
      age.days_since_boost !== null &&
      age.days_since_boost < age.age_total_days - 1
    ) {
      const boostStr = age.days_since_boost === 0 ? "сегодня" : `${fmtDays(age.days_since_boost)} назад`;
      ageText += ` · последний подъём ${boostStr}`;
    }
  }

  // ── Closing time ──
  let closingText = "";
  if (closing_time && closing_time.median_days) {
    closingText = `~${closing_time.median_days} дней (по ${closing_time.sample_size} закрытым вакансиям)`;
  }

  // ── Competition ──
  const transparencyText = competition.salary_transparency
    ? ` · ${competition.salary_transparency.percent}% указывают зарплату`
    : "";
  const competitionVal = competition.count !== null
    ? `${competition.count}<span style="font-size:10px;color:#aaa">${transparencyText}</span>`
    : "—";

  // ── Salary block ──
  const sf = salary.from, st = salary.to, cur = salary.currency;
  let salaryVal = "не указана";
  if (cur && cur !== "RUR") {
    if (sf && st) salaryVal = `${sf.toLocaleString("ru-RU")} — ${st.toLocaleString("ru-RU")} ${cur}`;
    else if (sf) salaryVal = `от ${sf.toLocaleString("ru-RU")} ${cur}`;
    else if (st) salaryVal = `до ${st.toLocaleString("ru-RU")} ${cur}`;
  } else {
    if (sf && st) salaryVal = `${fmt(sf)} — ${fmt(st)}`;
    else if (sf) salaryVal = `от ${fmt(sf)}`;
    else if (st) salaryVal = `до ${fmt(st)}`;
  }

  const market = salary.market;
  const marketColor = market?.label === "выше рынка"
    ? "color:#2e7d32"
    : market?.label === "ниже рынка"
    ? "color:#c62828"
    : "color:#555";
  const salaryLine = market
    ? `${salaryVal} <span style="font-size:11px;${marketColor}">· ${market.label}</span>`
    : salaryVal;

  let marketRow = "";
  if (market) {
    marketRow = `
      <div class="hhi-row" style="margin-top:2px">
        <span class="hhi-label" style="font-size:11px;color:#888">
          Рынок: медиана ${fmt(market.median)} (по ${market.sample_size} похожим вакансиям)
        </span>
      </div>`;
  } else if (!cur || cur === "RUR") {
    marketRow = `
      <div class="hhi-row" style="margin-top:2px">
        <span class="hhi-label" style="font-size:11px;color:#bbb">Рыночные данные накапливаются</span>
      </div>`;
  }

  panel.innerHTML = `
    <h3>HH Insights</h3>
    <div class="hhi-row">
      <span class="hhi-label">${ageText || "Дата создания неизвестна"}</span>
    </div>
    <div class="hhi-row">
      <span class="hhi-label" style="font-size:11px;color:#888">
        Обычно закрываются за: ${closingText || "данные накапливаются"}
      </span>
    </div>
    <div class="hhi-row">
      <span class="hhi-label">Похожих вакансий в базе</span>
      <span class="hhi-value">${competitionVal}</span>
    </div>
    <div class="hhi-row">
      <span class="hhi-label">Зарплата</span>
      <span class="hhi-value">${salaryLine}</span>
    </div>
    ${marketRow}
  `;

  _injecting = false;

  injectCompanySection(panel, data);
  injectHistory(panel, vacancyId);
}


async function injectCompanySection(panel, data) {
  const companyLink = document.querySelector("[data-qa='vacancy-company-name']")?.closest("a");
  if (!companyLink) return;
  const m = companyLink.href.match(/\/employer\/(\d+)/);
  if (!m) return;

  const params = new URLSearchParams();
  if (data.professional_roles?.length) params.set("roles", data.professional_roles.join(","));
  if (data.area) params.set("area", data.area);
  if (data.is_remote) params.set("is_remote", "true");

  const profile = await apiFetch(`/company/${m[1]}?${params}`);
  if (!profile) return;

  const ttfText = profile.median_days_to_fill
    ? `${profile.median_days_to_fill} дней (по ${profile.median_sample_size} вакансиям)`
    : "нет данных";

  const activeText = profile.active_vacancies !== null && profile.active_vacancies !== undefined
    ? profile.active_vacancies
    : "—";

  const trendRows = _buildTrendRows(profile.trend);

  let reopenHtml = "";
  const reopen = data.reopen;
  if (reopen && reopen.past_attempts) {
    const times = reopen.past_attempts === 1 ? "1 раз" : `${reopen.past_attempts} раза`;
    const gap = reopen.avg_reopen_days ? `, в среднем через ${reopen.avg_reopen_days} дн.` : "";
    reopenHtml = `<div style="font-size:11px;color:#b26a00;margin-top:4px">⚠ Компания уже открывала похожую вакансию ${times}${gap}</div>`;
  }

  const block = document.createElement("div");
  block.innerHTML = `
    <div style="margin-top:12px;padding-top:12px;border-top:1px solid #f0f0f0">
      <div class="hhi-row">
        <span class="hhi-label">Активных вакансий</span>
        <span class="hhi-value">${activeText}</span>
      </div>
      ${reopenHtml}
      <div class="hhi-row">
        <span class="hhi-label">Медианное время найма</span>
        <span class="hhi-value">${ttfText}</span>
      </div>
      ${trendRows}
    </div>
  `;
  panel.appendChild(block);
}

function _buildTrendRows(trend) {
  if (!trend) return "";
  const company = trend.company || [];
  const market = trend.market || [];
  if (!company.length && !market.length) return "";

  // Merge by month, show last 6 months
  const allMonths = [...new Set([
    ...company.map(r => r.month),
    ...market.map(r => r.month),
  ])].sort().slice(-6);

  if (!allMonths.length) return "";

  const companyMap = Object.fromEntries(company.map(r => [r.month, r]));
  const marketMap = Object.fromEntries(market.map(r => [r.month, r]));

  const rows = allMonths.reverse().map(month => {
    const c = companyMap[month];
    const mk = marketMap[month];
    const label = _fmtMonth(month);
    let parts = [];
    if (c) parts.push(`компания: +${c.opened}/−${c.closed}`);
    if (mk) parts.push(`рынок: +${mk.opened}/−${mk.closed}`);
    return `<div class="hhi-row" style="font-size:11px">
      <span style="color:#aaa">${label}</span>
      <span>${parts.join(" · ")}</span>
    </div>`;
  }).join("");

  return `
    <div style="margin-top:8px">
      <div class="hhi-label" style="margin-bottom:4px">Тренд найма (по нашим данным)</div>
      ${rows}
    </div>`;
}

function _fmtMonth(yyyyMM) {
  const [y, m] = yyyyMM.split("-");
  const d = new Date(+y, +m - 1, 1);
  return d.toLocaleDateString("ru-RU", { month: "short", year: "numeric" });
}


async function injectHistory(panel, vacancyId) {
  const [changes, roles] = await Promise.all([
    apiFetch(`/vacancy/${vacancyId}/history`),
    loadRoles(),
  ]);

  let content = "";
  if (!changes || !changes.length) {
    content = `<div style="font-size:11px;color:#bbb">История появится после следующего краулинга</div>`;
  } else {
    content = changes.map(c => `
      <div class="hhi-row" style="font-size:12px;align-items:flex-start">
        <span style="color:#aaa;white-space:nowrap;margin-right:8px">${fmtDate(c.changed_at)}</span>
        <span>${fmtChange(c, roles)}</span>
      </div>
    `).join("");
  }

  const block = document.createElement("div");
  block.innerHTML = `
    <div style="margin-top:12px;padding-top:12px;border-top:1px solid #f0f0f0">
      <div class="hhi-label" style="margin-bottom:6px">История вакансии</div>
      ${content}
    </div>
  `;
  panel.appendChild(block);
}


// ── Router ────────────────────────────────────────────────────────────────────

function init() {
  const vacancyId = getVacancyId();
  if (vacancyId) injectVacancyPanel(vacancyId);
}

init();
