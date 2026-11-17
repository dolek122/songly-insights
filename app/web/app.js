const API = "/api/v1";
const MAX_DAYS = 366;
const PAGE_SIZE = 25;

const state = { range: null, days: "30", chart: null };
let renderToken = 0;

class ApiError extends Error {
  constructor(status, error) {
    super(error.message);
    this.status = status;
    this.code = error.code;
  }
}

async function api(path, params = {}) {
  const url = new URL(API + path, location.origin);
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== "") {
      url.searchParams.set(key, value);
    }
  }
  const response = await fetch(url);
  const body = await response.json();
  if (!response.ok) {
    throw new ApiError(response.status, body.error);
  }
  return body;
}

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function number(value) {
  return Number(value ?? 0).toLocaleString("pl-PL");
}

function hours(ms) {
  return (ms / 3_600_000).toLocaleString("pl-PL", { maximumFractionDigits: 1 }) + " h";
}

function minutes(value) {
  if (value === null || value === undefined) {
    return "–";
  }
  return Math.round(value).toLocaleString("pl-PL") + " min";
}

function dateTime(value) {
  return new Date(value).toLocaleString("pl-PL", { dateStyle: "medium", timeStyle: "short" });
}

function shortDay(day) {
  return new Date(day + "T00:00:00Z").toLocaleDateString("pl-PL", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
}

function addDays(day, count) {
  const date = new Date(day + "T00:00:00Z");
  date.setUTCDate(date.getUTCDate() + count);
  return date.toISOString().slice(0, 10);
}

function daysBetween(from, to) {
  return Math.round((new Date(to) - new Date(from)) / 86_400_000);
}

function currentWindow() {
  const to = addDays(state.range.last_day, 1);
  const wanted = state.days === "all" ? daysBetween(state.range.first_day, to) : Number(state.days);
  return { from: addDays(to, -Math.min(wanted, MAX_DAYS)), to };
}

function windowLabel(period) {
  return `${shortDay(period.from)} – ${shortDay(addDays(period.to, -1))}`;
}

function tile(label, value) {
  return `<div class="tile"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div></div>`;
}

function card(title, body) {
  return `<section class="card"><h2>${esc(title)}</h2>${body}</section>`;
}

function empty(text = "Brak danych w tym okresie.") {
  return `<p class="muted">${esc(text)}</p>`;
}

function bars(items, { label, value, href, extra }) {
  if (!items.length) {
    return empty();
  }
  const max = Math.max(...items.map(value), 1);
  const rows = items.map((item) => {
    const name = href ? `<a href="${href(item)}">${esc(label(item))}</a>` : esc(label(item));
    const note = extra ? ` <span class="extra">${esc(extra(item))}</span>` : "";
    const width = (value(item) / max) * 100;
    return `<li style="--w: ${width}%"><span class="name">${name}${note}</span><span class="num">${number(value(item))}</span></li>`;
  });
  return `<ol class="bars">${rows.join("")}</ol>`;
}

function trendList(items) {
  if (!items.length) {
    return empty();
  }
  const rows = items.map((item) => {
    const css = item.change >= 0 ? "up" : "down";
    const sign = item.change > 0 ? "+" : "";
    const pct = item.change_pct === null ? "nowy" : `${sign}${Math.round(item.change_pct)}%`;
    return `<tr>
      <td><a href="#/artists/${item.id}">${esc(item.name)}</a></td>
      <td class="num">${number(item.previous_plays)} → ${number(item.plays)}</td>
      <td class="num ${css}">${sign}${number(item.change)} (${pct})</td>
    </tr>`;
  });
  return `<div class="table-wrap"><table>
    <thead><tr><th>Artysta</th><th class="num">Odsłuchy</th><th class="num">Zmiana</th></tr></thead>
    <tbody>${rows.join("")}</tbody>
  </table></div>`;
}

function dailyChart(items) {
  return {
    labels: items.map((item) => shortDay(item.day)),
    values: items.map((item) => item.plays),
  };
}

function drawChart(chart) {
  if (state.chart) {
    state.chart.destroy();
    state.chart = null;
  }
  const canvas = document.getElementById("daily-chart");
  if (!chart || !canvas || !window.Chart) {
    return;
  }
  const styles = getComputedStyle(document.documentElement);
  const accent = styles.getPropertyValue("--accent").trim();
  const muted = styles.getPropertyValue("--muted").trim();
  const border = styles.getPropertyValue("--border").trim();
  state.chart = new window.Chart(canvas, {
    type: "line",
    data: {
      labels: chart.labels,
      datasets: [
        {
          label: "Odsłuchy",
          data: chart.values,
          borderColor: accent,
          backgroundColor: accent + "33",
          fill: true,
          cubicInterpolationMode: "monotone",
          pointRadius: 0,
          pointHitRadius: 10,
        },
      ],
    },
    options: {
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: muted, maxTicksLimit: 10 }, grid: { display: false } },
        y: { beginAtZero: true, ticks: { color: muted }, grid: { color: border } },
      },
    },
  });
}

async function overviewPage() {
  const period = currentWindow();
  const [daily, sessions, artists, genres, tracks, rising, falling] = await Promise.all([
    api("/stats/daily", period),
    api("/stats/sessions", period),
    api("/stats/top-artists", { ...period, limit: 8 }),
    api("/stats/top-genres", { ...period, limit: 8 }),
    api("/stats/top-tracks", { ...period, limit: 8 }),
    api("/stats/trending-artists", { ...period, limit: 5 }),
    api("/stats/trending-artists", { ...period, limit: 5, direction: "falling" }),
  ]);
  const totalPlays = daily.items.reduce((sum, item) => sum + item.plays, 0);
  const html = `
    <h1>Przegląd</h1>
    <p class="subtitle">${windowLabel(period)} · trendy w porównaniu z okresem ${windowLabel({
      from: rising.previous_window.from.slice(0, 10),
      to: rising.previous_window.to.slice(0, 10),
    })}</p>
    <div class="tiles">
      ${tile("Odsłuchy", number(totalPlays))}
      ${tile("Sesje słuchania", number(sessions.sessions))}
      ${tile("Średnia sesja", minutes(sessions.avg_duration_minutes))}
      ${tile("Mediana sesji", minutes(sessions.median_duration_minutes))}
    </div>
    <section class="card" style="margin-bottom: 16px">
      <h2>Odsłuchy dziennie (UTC)</h2>
      <div class="chart-box"><canvas id="daily-chart"></canvas></div>
    </section>
    <div class="grid">
      ${card("Najpopularniejsi artyści", bars(artists.items, {
        label: (a) => a.name,
        value: (a) => a.plays,
        href: (a) => `#/artists/${a.artist_id}`,
      }))}
      ${card("Najpopularniejsze gatunki", bars(genres.items, {
        label: (g) => g.name,
        value: (g) => g.plays,
      }))}
      ${card("Najpopularniejsze utwory", bars(tracks.items, {
        label: (t) => t.title,
        value: (t) => t.plays,
        extra: (t) => t.artist_name,
      }))}
    </div>
    <div class="grid">
      ${card("Najszybciej rosnący artyści", trendList(rising.items))}
      ${card("Najszybciej tracący artyści", trendList(falling.items))}
    </div>`;
  return { html, chart: dailyChart(daily.items) };
}

function pager(total, offset, link) {
  if (total <= PAGE_SIZE) {
    return "";
  }
  const prev = offset > 0 ? `<a href="${link(Math.max(offset - PAGE_SIZE, 0))}">← Poprzednie</a>` : "<span></span>";
  const next = offset + PAGE_SIZE < total ? `<a href="${link(offset + PAGE_SIZE)}">Następne →</a>` : "<span></span>";
  const to = Math.min(offset + PAGE_SIZE, total);
  return `<div class="pager">${prev}<span>${offset + 1}–${to} z ${total}</span>${next}</div>`;
}

async function listenersPage(params) {
  const offset = Number(params.get("offset") || 0);
  const page = await api("/listeners", { limit: PAGE_SIZE, offset });
  const rows = page.items.map(
    (listener) => `<tr>
      <td><a href="#/listeners/${listener.id}">${esc(listener.username)}</a></td>
      <td>${esc(listener.country || "–")}</td>
      <td>${listener.listenbrainz_user ? "ListenBrainz" : "dane syntetyczne"}</td>
    </tr>`,
  );
  const html = `
    <h1>Słuchacze</h1>
    <p class="subtitle">Kliknij słuchacza, żeby zobaczyć jego statystyki, sesje i podobnych słuchaczy.</p>
    <section class="card">
      <div class="table-wrap"><table>
        <thead><tr><th>Nazwa</th><th>Kraj</th><th>Źródło</th></tr></thead>
        <tbody>${rows.join("")}</tbody>
      </table></div>
      ${pager(page.total, offset, (value) => `#/listeners?offset=${value}`)}
    </section>`;
  return { html };
}

async function listenerPage(params, id) {
  const period = currentWindow();
  const [listener, summary, daily, artists, sessions, similar] = await Promise.all([
    api(`/listeners/${id}`),
    api(`/listeners/${id}/summary`, period),
    api("/stats/daily", { ...period, listener_id: id }),
    api("/stats/top-artists", { ...period, listener_id: id, limit: 8 }),
    api(`/listeners/${id}/sessions`, { ...period, limit: 10 }),
    api(`/listeners/${id}/similar`, { ...period, limit: 5 }),
  ]);
  const sessionRows = sessions.items.map(
    (session) => `<tr>
      <td>${dateTime(session.started_at)}</td>
      <td class="num">${minutes(session.duration_minutes)}</td>
      <td class="num">${number(session.plays)}</td>
      <td class="num">${number(session.unique_artists)}</td>
    </tr>`,
  );
  const similarRows = similar.items.map(
    (item) => `<li>
      <a href="#/listeners/${item.listener_id}">${esc(item.username)}</a>
      <span class="num muted"> · ${Math.round(item.similarity * 100)}% podobieństwa</span>
      <div>${item.top_shared_artists.map((a) => `<span class="tag">${esc(a.name)}</span>`).join("")}</div>
    </li>`,
  );
  const html = `
    <p><a href="#/listeners">← Słuchacze</a></p>
    <h1>${esc(listener.username)}</h1>
    <p class="subtitle">${windowLabel(period)}${listener.country ? ` · ${esc(listener.country)}` : ""}</p>
    <div class="tiles">
      ${tile("Odsłuchy", number(summary.total_plays))}
      ${tile("Czas słuchania", hours(summary.total_listening_ms))}
      ${tile("Różnych artystów", number(summary.unique_artists))}
      ${tile("Ulubiony gatunek", summary.top_genre ? summary.top_genre.name : "–")}
    </div>
    <section class="card" style="margin-bottom: 16px">
      <h2>Odsłuchy dziennie (UTC)</h2>
      <div class="chart-box"><canvas id="daily-chart"></canvas></div>
    </section>
    <div class="grid">
      ${card("Ulubieni artyści", bars(artists.items, {
        label: (a) => a.name,
        value: (a) => a.plays,
        href: (a) => `#/artists/${a.artist_id}`,
      }))}
      ${card(
        "Podobni słuchacze",
        similarRows.length ? `<ul class="similar">${similarRows.join("")}</ul>` : empty(),
      )}
    </div>
    ${card(
      `Ostatnie sesje (${number(sessions.total)} w tym okresie)`,
      sessionRows.length
        ? `<div class="table-wrap"><table>
            <thead><tr><th>Początek</th><th class="num">Długość</th><th class="num">Utwory</th><th class="num">Artyści</th></tr></thead>
            <tbody>${sessionRows.join("")}</tbody>
          </table></div>`
        : empty(),
    )}`;
  return { html, chart: dailyChart(daily.items) };
}

async function artistsPage(params) {
  const offset = Number(params.get("offset") || 0);
  const q = params.get("q") || "";
  const page = await api("/artists", { limit: PAGE_SIZE, offset, q });
  const rows = page.items.map(
    (artist) => `<tr>
      <td><a href="#/artists/${artist.id}">${esc(artist.name)}</a></td>
      <td>${artist.genres.map((g) => `<span class="tag">${esc(g.name)}</span>`).join("")}</td>
    </tr>`,
  );
  const query = q ? `&q=${encodeURIComponent(q)}` : "";
  const html = `
    <h1>Artyści</h1>
    <p class="subtitle">Katalog artystów z danych syntetycznych i MusicBrainz.</p>
    <form class="toolbar" id="artist-search">
      <input name="q" type="search" placeholder="Szukaj artysty…" value="${esc(q)}">
      <button type="submit">Szukaj</button>
    </form>
    <section class="card">
      ${rows.length ? `<div class="table-wrap"><table>
        <thead><tr><th>Artysta</th><th>Gatunki</th></tr></thead>
        <tbody>${rows.join("")}</tbody>
      </table></div>` : empty("Nie znaleziono artystów.")}
      ${pager(page.total, offset, (value) => `#/artists?offset=${value}${query}`)}
    </section>`;
  return { html };
}

async function artistPage(params, id) {
  const [artist, tracks] = await Promise.all([
    api(`/artists/${id}`),
    api("/tracks", { artist_id: id, limit: 200 }),
  ]);
  const rows = tracks.items.map(
    (track) => `<tr>
      <td>${esc(track.title)}</td>
      <td class="num">${track.duration_ms ? formatDuration(track.duration_ms) : "–"}</td>
    </tr>`,
  );
  const source = artist.mbid
    ? `<a href="https://musicbrainz.org/artist/${esc(artist.mbid)}" target="_blank" rel="noopener">MusicBrainz</a>`
    : "dane syntetyczne";
  const html = `
    <p><a href="#/artists">← Artyści</a></p>
    <h1>${esc(artist.name)}</h1>
    <p class="subtitle">${artist.genres.map((g) => `<span class="tag">${esc(g.name)}</span>`).join("")} Źródło: ${source}</p>
    ${card(
      `Utwory (${number(tracks.total)})`,
      rows.length
        ? `<div class="table-wrap"><table>
            <thead><tr><th>Tytuł</th><th class="num">Długość</th></tr></thead>
            <tbody>${rows.join("")}</tbody>
          </table></div>`
        : empty("Brak utworów."),
    )}`;
  return { html };
}

function formatDuration(ms) {
  const total = Math.round(ms / 1000);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

function errorPage(error) {
  if (error.code === "marts_not_ready") {
    return `<div class="message"><h1>Brak statystyk</h1>
      <p>Statystyki powstają w pipelinie danych. Uruchom go poleceniem <code>python -m pipeline run</code> i odśwież stronę.</p></div>`;
  }
  if (error.status === 404) {
    return `<div class="message"><h1>Nie znaleziono</h1><p>${esc(error.message)}</p>
      <p><a href="#/">Wróć do przeglądu</a></p></div>`;
  }
  return `<div class="message"><h1>Coś poszło nie tak</h1><p>${esc(error.message)}</p></div>`;
}

const routes = [
  [/^\/$/, overviewPage, "overview"],
  [/^\/listeners$/, listenersPage, "listeners"],
  [/^\/listeners\/(\d+)$/, listenerPage, "listeners"],
  [/^\/artists$/, artistsPage, "artists"],
  [/^\/artists\/(\d+)$/, artistPage, "artists"],
];

function highlightNav(section) {
  for (const link of document.querySelectorAll("[data-nav]")) {
    link.classList.toggle("active", link.dataset.nav === section);
  }
}

async function loadRange() {
  state.range = await api("/stats/data-range");
  const footer = document.getElementById("footer");
  footer.textContent = state.range.last_day
    ? `Dane od ${state.range.first_day} do ${state.range.last_day} · ostatnie uruchomienie pipeline'u: ${dateTime(state.range.data_as_of)}`
    : "";
}

async function render() {
  const token = ++renderToken;
  const [path, query = ""] = location.hash.slice(1).split("?");
  const params = new URLSearchParams(query);
  const view = document.getElementById("view");
  const route = routes.find(([pattern]) => pattern.test(path || "/"));
  if (!route) {
    location.hash = "#/";
    return;
  }
  const [pattern, page, section] = route;
  highlightNav(section);
  view.innerHTML = `<p class="muted">Wczytywanie…</p>`;
  try {
    if (!state.range) {
      await loadRange();
    }
    if (!state.range.last_day) {
      throw new ApiError(503, {
        code: "marts_not_ready",
        message: "Brak odsłuchów w martach.",
      });
    }
    const match = (path || "/").match(pattern);
    const result = await page(params, ...match.slice(1));
    if (token !== renderToken) {
      return;
    }
    view.innerHTML = result.html;
    drawChart(result.chart);
    bindForms();
  } catch (error) {
    if (token !== renderToken) {
      return;
    }
    drawChart(null);
    view.innerHTML = errorPage(error);
  }
}

function bindForms() {
  const search = document.getElementById("artist-search");
  if (search) {
    search.addEventListener("submit", (event) => {
      event.preventDefault();
      const q = new FormData(search).get("q").trim();
      location.hash = q ? `#/artists?q=${encodeURIComponent(q)}` : "#/artists";
    });
  }
}

document.getElementById("window").addEventListener("change", (event) => {
  state.days = event.target.value;
  render();
});

window.addEventListener("hashchange", render);
render();
