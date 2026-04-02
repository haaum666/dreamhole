const API = "https://moiraidrone.fvds.ru/hh";
const root = document.getElementById("root");

// UUID для дедупликации отзывов
async function getUserHash(companyId) {
  let uuid = (await chrome.storage.local.get("uuid")).uuid;
  if (!uuid) {
    uuid = crypto.randomUUID();
    await chrome.storage.local.set({ uuid });
  }
  const encoder = new TextEncoder();
  const data = encoder.encode(uuid + String(companyId) + "dhsalt2026");
  const buf = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, "0")).join("");
}

async function getVoteHash(reviewId) {
  let uuid = (await chrome.storage.local.get("uuid")).uuid;
  if (!uuid) {
    uuid = crypto.randomUUID();
    await chrome.storage.local.set({ uuid });
  }
  const encoder = new TextEncoder();
  const data = encoder.encode(uuid + String(reviewId) + "dhvote2026");
  const buf = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, "0")).join("");
}

let _currentVacancyId = null;  // deduplication
let _renderToken = 0;           // race condition guard

const FETCH_TIMEOUT_MS = 10000;

async function apiFetchWithTimeout(path, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    const r = await fetch(API + path, { signal: controller.signal, ...options });
    clearTimeout(timer);
    if (!r.ok) return null;
    return await r.json();
  } catch { clearTimeout(timer); return null; }
}

// ── Utils ─────────────────────────────────────────────────────────────────────

function getVacancyId(url) {
  const m = (url || "").match(/\/vacancy\/(\d+)/);
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
  return `${Math.round(days / 30)} мес.`;
}

function fmtDate(isoStr) {
  return new Date(isoStr).toLocaleDateString("ru-RU", { day: "numeric", month: "short" });
}

function fmtMonth(yyyyMM) {
  const [y, m] = yyyyMM.split("-");
  return new Date(+y, +m - 1, 1).toLocaleDateString("ru-RU", { month: "short", year: "numeric" });
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
  // Новый формат: "50000/60000", "/60000", "50000/"
  if (s.includes("/")) {
    const [a, b] = s.split("/");
    const from = a ? parseInt(a) : null;
    const to = b ? parseInt(b) : null;
    if (from && to) return `${from.toLocaleString("ru-RU")}–${to.toLocaleString("ru-RU")} ₽`;
    if (from) return `от ${from.toLocaleString("ru-RU")} ₽`;
    if (to) return `до ${to.toLocaleString("ru-RU")} ₽`;
  }
  // Старый формат: "None-50000", "50000-None"
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

async function apiFetch(path, options = {}) {
  return apiFetchWithTimeout(path, options);
}

// ── Render helpers ────────────────────────────────────────────────────────────

function row(label, value, valueClass = "") {
  return `<div class="row">
    <span class="label">${label}</span>
    <span class="value ${valueClass}">${value}</span>
  </div>`;
}

function card(title, content) {
  return `<div class="card">
    ${title ? `<div class="card-title">${title}</div>` : ""}
    ${content}
  </div>`;
}

function note(text) {
  return `<div class="note">${text}</div>`;
}

// ── Crawler status ────────────────────────────────────────────────────────────

function buildCrawlerStatus(cs) {
  if (!cs) return note("Статус краулера недоступен");

  if (cs.running) {
    const count = cs.vacancies_processed?.toLocaleString("ru-RU") || "0";
    return `<div class="card-title">Краулинг в процессе — ${count} вакансий
      <span class="dots"><span>.</span><span>.</span><span>.</span></span>
    </div>`;
  }

  if (cs.finished_at) {
    const finishedMs = new Date(cs.finished_at).getTime();
    const nextMs = finishedMs + 24 * 3600 * 1000;
    const diffMs = nextMs - Date.now();
    let timeStr = "скоро";
    if (diffMs > 0) {
      const h = Math.floor(diffMs / 3600000);
      const m = Math.floor((diffMs % 3600000) / 60000);
      timeStr = h > 0 ? `через ${h} ч ${m} мин` : `через ${m} мин`;
    }
    const processed = cs.vacancies_processed?.toLocaleString("ru-RU") || "0";
    return `<div class="card-title">Последний краулинг: ${processed} вакансий. <span style="font-weight:400;color:#777">Следующий — ${timeStr}.</span></div>`;
  }

  return note("Краулинг ещё не запускался");
}


// ── Main render ───────────────────────────────────────────────────────────────

async function render(vacancyId) {
  // Deduplication — skip if same vacancy already loaded
  if (vacancyId === _currentVacancyId) return;
  _currentVacancyId = vacancyId;

  // Race guard — if a newer render starts, this one stops
  const token = ++_renderToken;

  root.innerHTML = `<div class="loading">Загружаю данные...</div>`;

  const [data, changes, stats, crawlerStatus, reviewsStats] = await Promise.all([
    apiFetch(`/vacancy/${vacancyId}`),
    apiFetch(`/vacancy/${vacancyId}/history`),
    apiFetch(`/stats`),
    apiFetch(`/crawler/status`),
    apiFetch(`/reviews/stats`),
  ]);

  // Newer render started — discard this result
  if (token !== _renderToken) return;

  if (!data) {
    root.innerHTML = `<div class="empty">Вакансия ещё не в базе.<br>Данные появятся после следующего краулинга.</div>`;
    return;
  }

  const { age, closing_time, competition, salary } = data;
  let html = ``;

  // ── Вакансия ──
  let ageText = age.age_total_days === 0
    ? "Вакансия создана сегодня"
    : age.age_total_days !== null
    ? `Вакансия создана ${fmtDays(age.age_total_days)} назад`
    : "Дата создания неизвестна";

  if (age.days_since_boost !== null && age.days_since_boost < age.age_total_days - 1) {
    const b = age.days_since_boost === 0 ? "сегодня" : `${fmtDays(age.days_since_boost)} назад`;
    ageText += ` · подъём ${b}`;
  }

  const closingText = closing_time?.median_days
    ? `~${closing_time.median_days} дней (по ${closing_time.sample_size} вак.)`
    : "данные накапливаются";

  const transparencyText = competition.salary_transparency
    ? `${competition.salary_transparency.percent}% указывают зарплату`
    : "";

  html += card(ageText, `
    ${row("Похожих вакансий в базе:", competition.count !== null
      ? `${competition.count}${transparencyText ? ` (${transparencyText})` : ""}`
      : "—")}
    ${row("Похожие вакансии живут:", closingText)}
  `);

  html += `<hr class="divider">`;

  // ── Зарплата ──
  const sf = salary.from, st = salary.to, cur = salary.currency;
  let salaryTitle = "Зарплата в вакансии: не указана";
  if (sf && st) salaryTitle = `Зарплата в вакансии: ${fmt(sf)} — ${fmt(st)}`;
  else if (sf)  salaryTitle = `Зарплата в вакансии: от ${fmt(sf)}`;
  else if (st)  salaryTitle = `Зарплата в вакансии: до ${fmt(st)}`;

  const market = salary.market;
  const marketCls = market?.label === "выше рынка" ? "green" : market?.label === "ниже рынка" ? "red" : "";
  const salaryHeader = market
    ? `${salaryTitle} · <span class="${marketCls}">${market.label}</span>`
    : salaryTitle;

  let marketContent = "";
  if (market) {
    const typeLabel = market.salary_type === "from" ? "по нижней границе" : market.salary_type === "to" ? "по верхней границе" : "по среднему";
    marketContent = row(`Медиана рынка (${market.sample_size} вак., ${typeLabel})`, fmt(market.median));
  } else if (!cur || cur === "RUR") {
    marketContent = note("Для сравнения с рынком нужно больше вакансий с указанной зарплатой по этой роли и региону. База пополняется ежедневно.");
  }

  html += card(salaryHeader, marketContent || "");

  html += `<hr class="divider">`;

  // ── История вакансии ──
  let historyContent = "";
  if (!changes || !changes.length) {
    historyContent = note("История отслеживает изменения зарплаты, переподъёмы, смену требований и формата работы. Появится после следующего краулинга (раз в сутки).");
  } else {
    const roles = await loadRoles();
    historyContent = changes.map(c => `
      <div class="row" style="align-items:flex-start">
        <span class="label" style="white-space:nowrap">${fmtDate(c.changed_at)}</span>
        <span style="font-size:12px;text-align:right">${fmtChange(c, roles)}</span>
      </div>`).join("");
  }
  // ── Таб 1: Аналитика ──
  let tab1 = html;
  tab1 += card("История изменений вакансии", historyContent);
  tab1 += `<div id="hhi-company-placeholder"></div>`;

  // ── Таб 2: Отзывы ──
  const tab2 = buildReviewsTab();

  // ── Таб 3: БД ──
  let tab3 = `<div id="hhi-trend-placeholder"></div>`;
  if (stats) {
    const since = stats.crawl_started
      ? new Date(stats.crawl_started).toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" })
      : "—";
    const crawlerBlock = buildCrawlerStatus(crawlerStatus);
    tab3 += card("База данных расширения", `
      ${row("Вакансий собрано:", stats.total_vacancies?.toLocaleString("ru-RU"))}
      <div class="note" style="margin-top:2px;margin-bottom:6px">Направления: разработка (backend, frontend, mobile, fullstack, gamedev и др.), DevOps/администрирование, тестирование (QA/AQA), аналитика/BI, data science/ML, дизайн, управление продуктом/проектом, digital-маркетинг, техподдержка</div>
      <hr class="divider">
      ${row("Активных / архивных:", `${stats.active_vacancies?.toLocaleString("ru-RU")} / ${stats.archived_vacancies?.toLocaleString("ru-RU")}`)}
      ${row("Компаний:", stats.companies?.toLocaleString("ru-RU"))}
      ${row("Изменений отслежено:", stats.changes_tracked?.toLocaleString("ru-RU"))}
      <hr class="divider">
      <div id="hhi-crawler-status">${crawlerBlock}</div>
      ${note(`Первый запуск БД ${since}. Чем дольше работает — тем точнее аналитика.`)}
    `);
  }

  // ── Статистика отзывов ──
  if (reviewsStats && reviewsStats.total > 0) {
    const rs = reviewsStats;
    const total = rs.total;
    const topHtml = (rs.top_companies || []).map(c =>
      `<div class="row"><span class="label">${c.name}</span><span class="value">${c.count}</span></div>`
    ).join("");
    tab3 += card("Отзывы о найме", `
      ${row("Всего отзывов:", total)}
      ${row("Компаний с отзывами:", rs.companies)}
      <hr class="divider">
      ${row("✅ Оффер:",        `${rs.offers} (${Math.round(rs.offers*100/total)}%)`)}
      ${row("❌ Отказ:",        `${rs.rejected} (${Math.round(rs.rejected*100/total)}%)`)}
      ${row("👻 Гхост:",        `${rs.ghosted} (${Math.round(rs.ghosted*100/total)}%)`)}
      ${row("⏳ В процессе:",   `${rs.ongoing} (${Math.round(rs.ongoing*100/total)}%)`)}
      ${rs.avg_difficulty ? `<hr class="divider">${row("Сложность (avg):", `${rs.avg_difficulty} / 5`)}` : ""}
      ${rs.avg_hr ? row("Оценка HR (avg):", `${rs.avg_hr} / 5`) : ""}
      ${topHtml ? `<hr class="divider"><div class="note" style="margin-bottom:4px">Топ компаний по кол-ву отзывов:</div>${topHtml}` : ""}
    `);
  }


  root.innerHTML = `
    <div class="tabs">
      <button class="tab active" data-tab="analytics">Аналитика</button>
      <button class="tab" data-tab="reviews">Отзывы</button>
      <button class="tab" data-tab="db">БД</button>
    </div>
    <div id="tab-analytics" class="tab-content active">${tab1}</div>
    <div id="tab-reviews" class="tab-content">${tab2}</div>
    <div id="tab-db" class="tab-content">${tab3}</div>
  `;

  let _reviewsLoaded = false;

  document.querySelectorAll(".tab").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach(b => b.classList.remove("active"));
      document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById(`tab-${btn.dataset.tab}`).classList.add("active");
      // Загружаем отзывы лениво при первом открытии таба
      if (btn.dataset.tab === "reviews" && !_reviewsLoaded) {
        _reviewsLoaded = true;
        if (data._companyId) loadReviewsTab(data._companyId, data._companyName);
        else document.getElementById("reviews-loading").textContent = "Откройте страницу вакансии компании на hh.ru";
      }
    });
  });


  // ── Компания (async) ──
  loadCompany(data, token, vacancyId);
}

async function loadCompany(data, token, vacancyId) {
  const params = new URLSearchParams();
  if (data.professional_roles?.length) params.set("roles", data.professional_roles.join(","));
  if (data.area) params.set("area", data.area);
  if (data.is_remote) params.set("is_remote", "true");

  try {
    const hhController = new AbortController();
    const hhTimer = setTimeout(() => hhController.abort(), FETCH_TIMEOUT_MS);
    const hhResp = await fetch(`https://api.hh.ru/vacancies/${vacancyId}`, {
      headers: { "User-Agent": "HHInsights/1.0" },
      signal: hhController.signal,
    });
    clearTimeout(hhTimer);
    if (!hhResp.ok) return;
    const hhData = await hhResp.json();
    const employerId = hhData?.employer?.id;
    const employerName = hhData?.employer?.name || "";
    if (!employerId) return;

    // Сохраняем для таба отзывов
    data._companyId = parseInt(employerId);
    data._companyName = employerName;

    const profile = await apiFetch(`/company/${employerId}?${params}`);
    if (!profile) return;

    // Race guard — if a newer render started, don't update DOM
    if (token !== _renderToken) return;

    const ttfContent = profile.median_days_to_fill
      ? row("Медиана времени найма:", `${profile.median_days_to_fill} дней (по ${profile.median_sample_size} вак.)`)
      : note("Медиана времени найма от публикации до закрытия вакансии: пока недостаточно архивных данных — появится по мере накопления.");

    const trendContent = buildTrendRows(profile.trend);

    const placeholder = document.getElementById("hhi-company-placeholder");
    if (!placeholder) return;
    const reopenContent = buildReopenBlock(data.reopen);

    // Таб 1 — компания
    placeholder.innerHTML =
      `<hr class="divider">` +
      card("Компания", `
        ${row("Активных вакансий (hh.ru):", profile.active_vacancies ?? "—")}
        ${reopenContent}
        <hr class="divider">
        ${ttfContent}
      `);

    // Таб 3 — тренд
    if (trendContent) {
      const trendPlaceholder = document.getElementById("hhi-trend-placeholder");
      if (trendPlaceholder) {
        trendPlaceholder.innerHTML = card("Тренд найма", `
          <div class="note" style="margin-bottom:6px">сколько вакансий открывалось/закрывалось в месяц</div>
          ${trendContent}
        `) + `<hr class="divider">`;
      }
    }
  } catch {}
}

function buildReopenBlock(reopen) {
  if (!reopen || !reopen.past_attempts) return "";
  const times = reopen.past_attempts === 1 ? "1 раз" : `${reopen.past_attempts} раза`;
  const gap = reopen.avg_reopen_days ? `, в среднем через ${reopen.avg_reopen_days} дн.` : "";
  return `<div class="note" style="color:#b26a00">⚠ Компания уже открывала похожую вакансию ${times}${gap} — возможная текучка или фантомный найм</div>`;
}

function buildTrendRows(trend) {
  if (!trend) return "";
  const company = trend.company || [];
  const market = trend.market || [];
  if (!company.length && !market.length) return "";

  const allMonths = [...new Set([
    ...company.map(r => r.month),
    ...market.map(r => r.month),
  ])].sort().slice(-6);

  if (!allMonths.length) return "";

  const cm = Object.fromEntries(company.map(r => [r.month, r]));
  const mm = Object.fromEntries(market.map(r => [r.month, r]));

  const rows = allMonths.reverse().map(month => {
    const c = cm[month], mk = mm[month];
    const parts = [];
    if (c)  parts.push(`компания: +${c.opened} открыто, −${c.closed} закрыто`);
    if (mk) parts.push(`рынок: +${mk.opened}/−${mk.closed}`);
    return `<div style="padding:3px 0;font-size:11px;color:#555">
      <span style="color:#aaa">${fmtMonth(month)}:</span> ${parts.join(" · ")}
    </div>`;
  }).join("");

  return rows;
}

// ── Reviews ───────────────────────────────────────────────────────────────────

const STAGE_LABELS   = { hr: "HR", test: "Тестовое", tech: "Техническое", final: "Финал" };
const STATUS_LABELS  = {
  offer_accepted: "Получил оффер ✓",
  offer_declined: "Оффер — сам отказался",
  offer_revoked:  "Оффер отозвали",
  rejected:       "Отказали",
  ghosted:        "Перестали отвечать",
  frozen:         "Позицию заморозили",
  withdrew:       "Сам вышел из процесса",
  waiting:        "Всё ещё жду ответа",
};
const TEST_LABELS = {
  passed:      "Проверили — прошёл",
  failed:      "Проверили — отказали",
  not_checked: "Не проверили, зависло",
  skipped:     "Не стал делать",
};
const DURATION_LABELS = {
  lt1w: "< 1 недели", "1_2w": "1–2 недели", "2_4w": "2–4 недели", gt1m: "> месяца",
};

function buildReviewsTab() {
  return `
    <div id="reviews-loading" class="note" style="padding:8px 0">Загружаю отзывы...</div>
    <div id="reviews-content" style="display:none"></div>
    <div id="review-form-wrap" style="display:none"></div>
  `;
}

async function loadReviewsTab(companyId, companyName) {
  const wrap = document.getElementById("tab-reviews");
  if (!wrap) return;

  const data = await apiFetch(`/reviews/${companyId}`);
  const loading = document.getElementById("reviews-loading");
  const content = document.getElementById("reviews-content");
  if (!loading || !content) return;

  loading.style.display = "none";
  content.style.display = "block";

  const agg = data?.aggregate;
  let aggHtml = "";
  if (agg) {
    const ghostColor = agg.ghost_rate > 20 ? "color:#c62828" : "color:#555";
    aggHtml = card("Итоги найма", `
      ${row("Отзывов:", agg.total)}
      ${row("Гостинг:", `<span style="${ghostColor}">${agg.ghost_rate}%</span>`)}
      ${row("Офферов:", `${agg.offer_rate}%`)}
      ${agg.avg_difficulty ? row("Средняя сложность:", `${agg.avg_difficulty} / 5`) : ""}
      ${agg.avg_hr ? row("Оценка HR:", `${agg.avg_hr} / 5`) : ""}
    `);
  }

  const reviews = data?.reviews || [];
  const stored = await chrome.storage.local.get(["voted_reviews", "admin_token"]);
  const votes = stored.voted_reviews || {};
  const adminToken = stored.admin_token || "";
  let listHtml = "";
  if (reviews.length) {
    listHtml = reviews.map(r => {
      const stages = (r.stages || []).map(s => STAGE_LABELS[s] || s).join(" → ");
      const status = STATUS_LABELS[r.process_status] || r.process_status;
      const date = new Date(r.submitted_at).toLocaleDateString("ru-RU", { day: "numeric", month: "short" });
      const diff = r.difficulty ? `сложность ${r.difficulty}/5` : "";
      const hr = r.hr_rating ? `HR ${r.hr_rating}/5` : "";
      const meta = [r.role_category, stages, diff, hr].filter(Boolean).join(" · ");
      const voted = votes[r.id];
      const REACTIONS = [
        { key: "like",    emoji: "👍", count: r.likes    || 0 },
        { key: "dislike", emoji: "👎", count: r.dislikes || 0 },
        { key: "fire",    emoji: "🔥", count: r.fire     || 0 },
        { key: "poop",    emoji: "💩", count: r.poop     || 0 },
        { key: "clown",   emoji: "🤡", count: r.clown    || 0 },
      ];
      const pillsHtml = REACTIONS.map(rx => {
        const active = voted === rx.key;
        return `<button class="btn-vote" data-id="${r.id}" data-vote="${rx.key}"
          style="display:inline-flex;align-items:center;gap:3px;padding:3px 8px;border-radius:20px;
                 border:1px solid ${active ? "#555" : "#e0e0e0"};
                 background:${active ? "#f0f0f0" : "#fff"};
                 cursor:pointer;font-size:12px;font-family:inherit;line-height:1.4;
                 transition:background 0.1s,border-color 0.1s">
          ${rx.emoji}<span class="vote-${rx.key}-${r.id}">${rx.count}</span>
        </button>`;
      }).join("");
      const adminHtml = adminToken ? `
        <div style="display:flex;gap:6px;margin-top:6px;padding-top:6px;border-top:1px solid #f0f0f0">
          <button class="btn-admin-delete" data-id="${r.id}"
            style="font-size:11px;color:#c62828;background:none;border:1px solid #f5c6c6;border-radius:4px;padding:2px 8px;cursor:pointer;font-family:inherit">
            🗑 удалить
          </button>
          <button class="btn-admin-edit" data-id="${r.id}"
            style="font-size:11px;color:#555;background:none;border:1px solid #ddd;border-radius:4px;padding:2px 8px;cursor:pointer;font-family:inherit">
            ✏️ редактировать
          </button>
          <span class="note" style="margin-left:auto">id:${r.id}</span>
        </div>` : "";
      return `<div class="card" data-review-id="${r.id}" style="margin-bottom:4px">
        <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:4px">
          <span class="card-title" style="margin:0">${status}</span>
          <span class="note">${date}</span>
        </div>
        ${meta ? `<div class="note" style="margin-bottom:4px">${meta}</div>` : ""}
        ${r.questions ? `<div style="font-size:12px;color:#555;margin-bottom:2px">Вопросы: ${r.questions}</div>` : ""}
        ${r.comment ? `<div style="font-size:12px;color:#333">${r.comment}</div>` : ""}
        <div style="display:flex;align-items:center;gap:5px;flex-wrap:wrap;margin-top:6px">
          ${pillsHtml}
        </div>
        ${adminHtml}
      </div>`;
    }).join("");
  } else {
    listHtml = note("Отзывов пока нет. Будьте первым!");
  }

  content.innerHTML = `
    ${aggHtml}
    ${aggHtml ? `<hr class="divider">` : ""}
    ${card("", `
      <button id="btn-open-form" style="width:100%;padding:8px;background:#111;color:#fff;border:none;border-radius:6px;font-size:12px;cursor:pointer;font-family:inherit">
        + Оставить отзыв о собеседовании
      </button>
    `)}
    <div id="review-form-wrap"></div>
    ${listHtml ? `<hr class="divider">${listHtml}` : ""}
  `;

  document.getElementById("btn-open-form")?.addEventListener("click", () => {
    openReviewForm(companyId, companyName);
  });

  content.querySelectorAll(".btn-vote").forEach(btn => {
    btn.addEventListener("click", async () => {
      const id = btn.dataset.id;
      const vote = btn.dataset.vote;
      if (votes[id]) return; // уже голосовал (локально)

      const userHash = await getVoteHash(id);
      const result = await apiFetch(`/reviews/${id}/vote/${vote}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_hash: userHash }),
      });
      if (!result || result.error) return; // дубль на сервере — тихо игнорируем

      votes[id] = vote;
      const stored2 = await chrome.storage.local.get("voted_reviews");
      await chrome.storage.local.set({ voted_reviews: { ...(stored2.voted_reviews || {}), [id]: vote } });

      // Обновляем счётчики всех реакций
      const colMap = { like: "likes", dislike: "dislikes", fire: "fire", poop: "poop", clown: "clown" };
      for (const [key, col] of Object.entries(colMap)) {
        const el = content.querySelector(`.vote-${key}-${id}`);
        if (el && result[col] !== undefined) el.textContent = result[col];
      }

      // Подсвечиваем активную пилюлю
      content.querySelectorAll(`.btn-vote[data-id="${id}"]`).forEach(b => {
        const active = b.dataset.vote === vote;
        b.style.border = `1px solid ${active ? "#555" : "#e0e0e0"}`;
        b.style.background = active ? "#f0f0f0" : "#fff";
      });
    });
  });

  if (adminToken) {
    content.querySelectorAll(".btn-admin-delete").forEach(btn => {
      btn.addEventListener("click", async () => {
        const id = btn.dataset.id;
        if (!confirm(`Удалить отзыв #${id}?`)) return;
        const result = await apiFetch(`/admin/reviews/${id}`, {
          method: "DELETE",
          headers: { "X-Admin-Token": adminToken },
        });
        if (result?.ok) {
          const card = content.querySelector(`[data-review-id="${id}"]`);
          if (card) card.remove();
        } else {
          alert("Ошибка удаления");
        }
      });
    });

    content.querySelectorAll(".btn-admin-edit").forEach(btn => {
      btn.addEventListener("click", async () => {
        const id = btn.dataset.id;
        const comment = prompt("Новый комментарий (пусто = не менять):");
        const statusInput = prompt("Новый статус (offer/rejected/ghosted/ongoing/пусто = не менять):");
        const fields = {};
        if (comment !== null && comment.trim()) fields.comment = comment.trim();
        if (statusInput !== null && statusInput.trim()) fields.process_status = statusInput.trim();
        if (!Object.keys(fields).length) return;
        const result = await apiFetch(`/admin/reviews/${id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json", "X-Admin-Token": adminToken },
          body: JSON.stringify(fields),
        });
        if (result?.ok) {
          loadReviewsTab(companyId, companyName); // перезагружаем таб
        } else {
          alert("Ошибка редактирования");
        }
      });
    });
  }

}

async function openReviewForm(companyId, companyName) {
  const wrap = document.getElementById("review-form-wrap");
  if (!wrap) return;

  wrap.innerHTML = card("Ваш опыт", `
    <div style="font-size:11px;color:#999;margin-bottom:10px">${companyName} · анонимно, без регистрации</div>

    <div class="form-section">
      <div class="form-label">Этапы которые были</div>
      <div class="chips" id="f-stages">
        ${Object.entries(STAGE_LABELS).map(([k,v]) =>
          `<button class="chip" data-val="${k}">${v}</button>`
        ).join("")}
      </div>
    </div>

    <div class="form-section">
      <div class="form-label">Чем завершился процесс <span style="color:#c62828">*</span></div>
      <div class="radio-group" id="f-status">
        ${Object.entries(STATUS_LABELS).map(([k,v]) =>
          `<label class="radio-opt"><input type="radio" name="status" value="${k}"> ${v}</label>`
        ).join("")}
      </div>
    </div>

    <div class="form-section">
      <div class="form-label">На каком этапе остановились</div>
      <div class="radio-group" id="f-stopped">
        ${Object.entries(STAGE_LABELS).map(([k,v]) =>
          `<label class="radio-opt"><input type="radio" name="stopped" value="${k}"> ${v}</label>`
        ).join("")}
      </div>
    </div>

    <div id="f-test-wrap" class="form-section" style="display:none">
      <div class="form-label">Тестовое задание</div>
      <div class="radio-group">
        ${Object.entries(TEST_LABELS).map(([k,v]) =>
          `<label class="radio-opt"><input type="radio" name="test" value="${k}"> ${v}</label>`
        ).join("")}
      </div>
    </div>

    <div class="form-section">
      <div class="form-label">Ваша роль</div>
      <select id="f-role" style="width:100%;padding:6px;border:1px solid #e0e0e0;border-radius:6px;font-size:12px;font-family:inherit">
        <option value="">— не указывать —</option>
        <option>Backend</option><option>Frontend</option><option>Fullstack</option>
        <option>Mobile</option><option>DevOps</option><option>QA/AQA</option>
        <option>Data Science/ML</option><option>Аналитика/BI</option>
        <option>Дизайн</option><option>Продукт</option><option>Маркетинг</option>
        <option>Техподдержка</option><option>Другое</option>
      </select>
    </div>

    <div class="form-section">
      <div class="form-label">Сложность</div>
      <div class="radio-row" id="f-diff">
        ${[1,2,3,4,5].map(n =>
          `<label class="radio-num"><input type="radio" name="diff" value="${n}"> ${n}</label>`
        ).join("")}
        <span class="note" style="margin-left:4px">1 — просто, 5 — хардкор</span>
      </div>
    </div>

    <div class="form-section">
      <div class="form-label">Оценка HR</div>
      <div class="radio-row" id="f-hr">
        ${[1,2,3,4,5].map(n =>
          `<label class="radio-num"><input type="radio" name="hr" value="${n}"> ${n}</label>`
        ).join("")}
        <span class="note" style="margin-left:4px">1 — ужасно, 5 — отлично</span>
      </div>
    </div>

    <div class="form-section">
      <div class="form-label">Срок процесса</div>
      <div class="radio-group">
        ${Object.entries(DURATION_LABELS).map(([k,v]) =>
          `<label class="radio-opt"><input type="radio" name="duration" value="${k}"> ${v}</label>`
        ).join("")}
      </div>
    </div>

    <div class="form-section">
      <div class="form-label">Что спрашивали <span class="note">(опционально)</span></div>
      <textarea id="f-questions" rows="2" placeholder="SQL, алгоритмы, системный дизайн..." style="width:100%;padding:6px;border:1px solid #e0e0e0;border-radius:6px;font-size:12px;font-family:inherit;resize:vertical"></textarea>
    </div>

    <div class="form-section">
      <div class="form-label">Комментарий <span class="note">(опционально)</span></div>
      <textarea id="f-comment" rows="3" placeholder="Атмосфера, скорость фидбека, советы..." style="width:100%;padding:6px;border:1px solid #e0e0e0;border-radius:6px;font-size:12px;font-family:inherit;resize:vertical"></textarea>
    </div>

    <div id="form-error" class="note" style="color:#c62828;display:none;margin-bottom:6px"></div>

    <button id="btn-submit-review" style="width:100%;padding:8px;background:#111;color:#fff;border:none;border-radius:6px;font-size:12px;cursor:pointer;font-family:inherit">
      Отправить отзыв
    </button>
    <div class="note" style="margin-top:6px;text-align:center">Анонимно. Без аккаунта. Без IP-логов.</div>
  `);

  // Показываем блок тестового если этап "test" выбран
  wrap.querySelectorAll("#f-stages .chip").forEach(chip => {
    chip.addEventListener("click", () => {
      chip.classList.toggle("active");
      const hasTest = !!wrap.querySelector(".chip[data-val='test'].active");
      document.getElementById("f-test-wrap").style.display = hasTest ? "block" : "none";
    });
  });

  wrap.querySelector("#btn-submit-review").addEventListener("click", async () => {
    const status = wrap.querySelector("input[name='status']:checked")?.value;
    if (!status) {
      document.getElementById("form-error").textContent = "Укажите чем завершился процесс";
      document.getElementById("form-error").style.display = "block";
      return;
    }
    document.getElementById("form-error").style.display = "none";

    const stages = [...wrap.querySelectorAll(".chip.active")].map(c => c.dataset.val);
    const body = {
      company_id: companyId,
      company_name: companyName,
      role_category: wrap.querySelector("#f-role").value || null,
      stages,
      test_task_status: wrap.querySelector("input[name='test']:checked")?.value || null,
      process_status: status,
      stopped_at_stage: wrap.querySelector("input[name='stopped']:checked")?.value || null,
      difficulty: parseInt(wrap.querySelector("input[name='diff']:checked")?.value) || null,
      hr_rating: parseInt(wrap.querySelector("input[name='hr']:checked")?.value) || null,
      duration_range: wrap.querySelector("input[name='duration']:checked")?.value || null,
      comment: wrap.querySelector("#f-comment").value.trim() || null,
      questions: wrap.querySelector("#f-questions").value.trim() || null,
      user_hash: await getUserHash(companyId),
    };

    const btn = wrap.querySelector("#btn-submit-review");
    btn.disabled = true;
    btn.textContent = "Отправляю...";

    try {
      const r = await fetch(API + "/reviews", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (r.status === 409) {
        wrap.innerHTML = card("", note("Вы уже оставляли отзыв об этой компании."));
      } else if (!r.ok) {
        btn.disabled = false;
        btn.textContent = "Отправить отзыв";
        document.getElementById("form-error").textContent = "Ошибка отправки. Попробуйте позже.";
        document.getElementById("form-error").style.display = "block";
      } else {
        wrap.innerHTML = card("", `
          <div style="text-align:center;padding:8px 0">
            <div style="font-size:20px;margin-bottom:6px">✓</div>
            <div style="font-weight:600;margin-bottom:4px">Отзыв отправлен</div>
            <div class="note">Спасибо! Это помогает другим соискателям.</div>
          </div>
        `);
        setTimeout(() => loadReviewsTab(companyId, companyName), 1000);
      }
    } catch {
      btn.disabled = false;
      btn.textContent = "Отправить отзыв";
    }
  });
}

// ── Init ──────────────────────────────────────────────────────────────────────

async function init() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  const url = tabs[0]?.url || "";
  const vacancyId = getVacancyId(url);

  if (!vacancyId) {
    root.innerHTML = `<div class="empty">Откройте страницу вакансии на hh.ru</div>`;
    return;
  }

  render(vacancyId);
}

init();
