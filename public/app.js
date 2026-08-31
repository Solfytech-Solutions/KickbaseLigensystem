/**
 * Kickbase Ligen Dashboard – app.js
 *
 * Liest die statische Datei data/leagues.json, die vom GitHub-Actions-Workflow
 * erzeugt wird, und rendert die Tabelle jeder Liga. Keine Datenbank, kein Login –
 * jeder Besucher sieht immer alle Ligen.
 */

const DATA_URL = "data/leagues.json";

// ────────────────────────────────────────────────────────────
// DOM-REFERENZEN
// ────────────────────────────────────────────────────────────
const $loading     = document.getElementById("loadingState");
const $error       = document.getElementById("errorState");
const $errorMsg    = document.getElementById("errorMessage");
const $grid        = document.getElementById("leaguesGrid");
const $lastUpdated = document.getElementById("lastUpdated");

// ────────────────────────────────────────────────────────────
// HILFSFUNKTIONEN
// ────────────────────────────────────────────────────────────

function formatMoney(val) {
  if (!val) return "–";
  const m = val / 1_000_000;
  return m >= 1
    ? `${m.toFixed(1)} Mio.`
    : `${(val / 1_000).toFixed(0)}K`;
}

function formatDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString("de-DE", {
    day: "2-digit", month: "2-digit", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

function rankClass(rank) {
  if (rank === 1) return "rank-1";
  if (rank === 2) return "rank-2";
  if (rank === 3) return "rank-3";
  return "rank-other";
}

function escHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function showError(msg) {
  $loading.classList.add("hidden");
  $grid.classList.add("hidden");
  $errorMsg.textContent = msg;
  $error.classList.remove("hidden");
}

// ────────────────────────────────────────────────────────────
// RENDERING
// ────────────────────────────────────────────────────────────

function buildLeagueCard(league) {
  const section = document.createElement("section");
  section.className = "league-section";

  const standings = [...(league.standings || [])]
    .sort((a, b) => (a.rank || 0) - (b.rank || 0));

  const rowsHtml = standings.length
    ? standings.map((m) => `
        <tr>
          <td class="col-rank"><span class="rank-badge ${rankClass(m.rank)}">${m.rank}</span></td>
          <td class="col-name"><span class="manager-name">${escHtml(m.name)}</span></td>
          <td class="col-points"><span class="points-val">${m.points ?? "–"}</span></td>
          <td class="col-value"><span class="team-value">${formatMoney(m.teamValue)}</span></td>
        </tr>
      `).join("")
    : `<tr><td colspan="4" class="empty-row">Keine Daten vorhanden</td></tr>`;

  section.innerHTML = `
    <h2 class="section-title">🏆 ${escHtml(league.name)}</h2>
    <div class="standings-table-wrapper">
      <table class="standings-table">
        <thead>
          <tr>
            <th class="col-rank">#</th>
            <th class="col-name">Manager</th>
            <th class="col-points">Punkte</th>
            <th class="col-value">Teamwert</th>
          </tr>
        </thead>
        <tbody>${rowsHtml}</tbody>
      </table>
    </div>
  `;

  return section;
}

function render(data) {
  const leagues = data.leagues || [];

  if (!leagues.length) {
    showError("Keine Liga-Daten gefunden. Bitte den GitHub-Actions-Workflow einmal manuell ausführen.");
    return;
  }

  leagues.sort((a, b) => (a.name || "").localeCompare(b.name || "", "de"));

  $grid.innerHTML = "";
  leagues.forEach((lg) => $grid.appendChild(buildLeagueCard(lg)));

  const stamp = formatDate(data.generatedAt);
  $lastUpdated.textContent = stamp ? `Aktualisiert: ${stamp}` : "";

  $loading.classList.add("hidden");
  $error.classList.add("hidden");
  $grid.classList.remove("hidden");
}

// ────────────────────────────────────────────────────────────
// START
// ────────────────────────────────────────────────────────────

// cache: "no-cache" → Browser fragt beim Server nach, ob es neue Daten gibt,
// statt eine alte Tabelle aus dem Cache zu zeigen.
fetch(DATA_URL, { cache: "no-cache" })
  .then((res) => {
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    return res.json();
  })
  .then(render)
  .catch((err) => {
    console.error("Fehler beim Laden der Daten:", err);
    showError(`Daten konnten nicht geladen werden (${err.message}).`);
  });
