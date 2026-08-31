/**
 * Kickbase Ligen Dashboard – app.js
 *
 * Liest die statische Datei data/leagues.json, die vom GitHub-Actions-Workflow
 * erzeugt wird, und rendert die Tabelle jeder Liga. Keine Datenbank, kein Login –
 * jeder Besucher sieht immer alle Ligen.
 */

const DATA_URL = "data/leagues.json";

// ────────────────────────────────────────────────────────────
// LIGA-KONFIGURATION
// ────────────────────────────────────────────────────────────
// Bestimmt Anzeige-Reihenfolge, Überschrift und Anzahl der Abstiegsplätze
// (= die letzten N Plätze der Tabelle). Die IDs stammen aus Kickbase und
// stehen in data/leagues.json.
// Ligen, die hier nicht aufgeführt sind, werden hinten alphabetisch
// angehängt und haben keine Abstiegsplätze.
const LIGEN = [
  { id: "3648767", titel: "1. Liga", absteiger: 2 },
  { id: "6853982", titel: "2. Liga", absteiger: 0 },
];

// Immer die ersten drei Plätze als Podium hervorheben
const PODIUM_PLAETZE = 3;

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

function escHtml(str) {
  if (str === null || str === undefined) return "";
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

/** Bringt die Ligen in die konfigurierte Reihenfolge und hängt die Konfig an. */
function ligenOrdnen(leagues) {
  const konfiguriert = [];
  const rest = [];

  leagues.forEach((lg) => {
    const konfig = LIGEN.find((k) => k.id === String(lg.id));
    if (konfig) {
      konfiguriert.push({ ...lg, konfig, position: LIGEN.indexOf(konfig) });
    } else {
      rest.push({ ...lg, konfig: { titel: lg.name, absteiger: 0 } });
    }
  });

  konfiguriert.sort((a, b) => a.position - b.position);
  rest.sort((a, b) => (a.name || "").localeCompare(b.name || "", "de"));

  return [...konfiguriert, ...rest];
}

// ────────────────────────────────────────────────────────────
// RENDERING
// ────────────────────────────────────────────────────────────

/**
 * Ordnet einem Platz seine Auszeichnung zu.
 * Das Podium hat Vorrang, damit ein Platz in einer sehr kleinen Liga nicht
 * gleichzeitig als Podium und als Abstiegsplatz markiert wird.
 */
function platzKlasse(rank, anzahl, absteiger) {
  if (rank <= PODIUM_PLAETZE) return `platz-${rank}`;
  if (absteiger > 0 && rank > anzahl - absteiger) return "platz-abstieg";
  return "platz-normal";
}

function buildLegende(absteiger) {
  const eintraege = [
    `<span class="legende-item"><span class="legende-dot dot-platz-1"></span>Platz 1</span>`,
    `<span class="legende-item"><span class="legende-dot dot-platz-2"></span>Platz 2</span>`,
    `<span class="legende-item"><span class="legende-dot dot-platz-3"></span>Platz 3</span>`,
  ];
  if (absteiger > 0) {
    eintraege.push(
      `<span class="legende-item"><span class="legende-dot dot-platz-abstieg"></span>` +
      `${absteiger === 1 ? "Abstiegsplatz" : `Abstiegsplätze (letzte ${absteiger})`}</span>`
    );
  }
  return `<div class="legende">${eintraege.join("")}</div>`;
}

function buildLeagueCard(league) {
  const { titel, absteiger } = league.konfig;
  const standings = [...(league.standings || [])].sort((a, b) => (a.rank || 0) - (b.rank || 0));
  const anzahl = standings.length;

  const rowsHtml = standings.length
    ? standings.map((m) => {
        const klasse = platzKlasse(m.rank, anzahl, absteiger);
        return `
          <tr class="row-${klasse}">
            <td class="col-rank"><span class="rank-badge badge-${klasse}">${m.rank}</span></td>
            <td class="col-name"><span class="manager-name">${escHtml(m.name)}</span></td>
            <td class="col-points"><span class="points-val">${m.points ?? "–"}</span></td>
            <td class="col-value"><span class="team-value">${formatMoney(m.teamValue)}</span></td>
          </tr>
        `;
      }).join("")
    : `<tr><td colspan="4" class="empty-row">Keine Daten vorhanden</td></tr>`;

  const section = document.createElement("section");
  section.className = "league-card";
  section.innerHTML = `
    <div class="league-card-header">
      <h2 class="league-titel">${escHtml(titel)}</h2>
      <span class="league-meta">${escHtml(league.name)} · ${anzahl} Manager</span>
    </div>
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
    ${buildLegende(absteiger)}
  `;

  return section;
}

function render(data) {
  const leagues = ligenOrdnen(data.leagues || []);

  if (!leagues.length) {
    showError("Keine Liga-Daten gefunden. Bitte den GitHub-Actions-Workflow einmal manuell ausführen.");
    return;
  }

  $grid.innerHTML = "";
  leagues.forEach((lg) => $grid.appendChild(buildLeagueCard(lg)));

  const stamp = formatDate(data.generatedAt);
  $lastUpdated.textContent = stamp ? `Stand: ${stamp}` : "";

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
