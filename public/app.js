/**
 * Kickbase Ligen Dashboard – app.js
 *
 * !! KONFIGURATION ERFORDERLICH !!
 * Ersetze den firebaseConfig-Block mit deinen eigenen Firebase-Werten.
 * Diese findest du in der Firebase Console unter:
 * Projekteinstellungen → Allgemein → Deine Apps → Firebase SDK snippet → Konfiguration
 */

// ────────────────────────────────────────────────────────────
// 1. FIREBASE KONFIGURATION  ← hier deine Werte eintragen
// ────────────────────────────────────────────────────────────
const firebaseConfig = {
  apiKey: "AIzaSyDkD-eI8rFdhppaSHrRfa2-A4M_7vZnS1o",
  authDomain: "kickbaseligensystem.firebaseapp.com",
  projectId: "kickbaseligensystem",
  storageBucket: "kickbaseligensystem.firebasestorage.app",
  messagingSenderId: "230279687527",
  appId: "1:230279687527:web:6e77ae9c84ed7157b953c2"
};

// ────────────────────────────────────────────────────────────
// 2. FIREBASE INIT
// ────────────────────────────────────────────────────────────
firebase.initializeApp(firebaseConfig);
const db = firebase.firestore();

// ────────────────────────────────────────────────────────────
// 3. STATE
// ────────────────────────────────────────────────────────────
let leagues = [];          // [{id, name, standings, lastUpdated}]
let squadsCache = {};      // { leagueId: { userId: [players] } }
let activeLeagueId = null;
let activeUnsubscribe = null;
let squadListeners = {};

// ────────────────────────────────────────────────────────────
// 4. DOM-REFERENZEN
// ────────────────────────────────────────────────────────────
const $tabs         = document.getElementById("ligaTabs");
const $loading      = document.getElementById("loadingState");
const $error        = document.getElementById("errorState");
const $errorMsg     = document.getElementById("errorMessage");
const $content      = document.getElementById("leagueContent");
const $tableBody    = document.getElementById("standingsBody");
const $squadsGrid   = document.getElementById("squadsGrid");
const $lastUpdated  = document.getElementById("lastUpdated");
const $modal        = document.getElementById("squadModal");
const $modalTitle   = document.getElementById("modalTitle");
const $modalBody    = document.getElementById("modalBody");
const $modalClose   = document.getElementById("modalClose");

// ────────────────────────────────────────────────────────────
// 5. HILFSFUNKTIONEN
// ────────────────────────────────────────────────────────────

function formatMoney(val) {
  if (!val) return "–";
  const m = val / 1_000_000;
  return m >= 1
    ? `${m.toFixed(1)} Mio.`
    : `${(val / 1_000).toFixed(0)}K`;
}

function formatDate(ts) {
  if (!ts) return "";
  const d = ts.toDate ? ts.toDate() : new Date(ts);
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

function showError(msg) {
  $loading.classList.add("hidden");
  $content.classList.add("hidden");
  $errorMsg.textContent = msg;
  $error.classList.remove("hidden");
}

function hideError() {
  $error.classList.add("hidden");
}

// ────────────────────────────────────────────────────────────
// 6. TABS RENDERN
// ────────────────────────────────────────────────────────────

function renderTabs() {
  $tabs.innerHTML = "";
  leagues.forEach((lg) => {
    const btn = document.createElement("button");
    btn.className = "tab-btn" + (lg.id === activeLeagueId ? " active" : "");
    btn.textContent = lg.name;
    btn.id = `tab-${lg.id}`;
    btn.addEventListener("click", () => switchLeague(lg.id));
    $tabs.appendChild(btn);
  });
}

function switchLeague(id) {
  activeLeagueId = id;
  // Tab-Highlight
  document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
  const activeTab = document.getElementById(`tab-${id}`);
  if (activeTab) activeTab.classList.add("active");

  const lg = leagues.find((l) => l.id === id);
  if (lg) renderLeague(lg);
}

// ────────────────────────────────────────────────────────────
// 7. LIGA RENDERN
// ────────────────────────────────────────────────────────────

function renderLeague(lg) {
  $lastUpdated.textContent = `Aktualisiert: ${formatDate(lg.lastUpdated)}`;
  renderStandings(lg.standings || []);

  // Kader nachladen falls noch nicht gecacht
  const cache = squadsCache[lg.id];
  if (cache) {
    renderSquads(lg.standings || [], cache);
  } else {
    loadSquads(lg);
  }

  $loading.classList.add("hidden");
  $error.classList.add("hidden");
  $content.classList.remove("hidden");
}

function renderStandings(standings) {
  $tableBody.innerHTML = "";
  if (!standings.length) {
    $tableBody.innerHTML = `<tr><td colspan="5" style="text-align:center;color:var(--text-muted);padding:32px">Keine Daten vorhanden</td></tr>`;
    return;
  }
  standings.forEach((m) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="col-rank"><span class="rank-badge ${rankClass(m.rank)}">${m.rank}</span></td>
      <td class="col-name"><span class="manager-name">${escHtml(m.name)}</span></td>
      <td class="col-points"><span class="points-val">${m.points ?? "–"}</span></td>
      <td class="col-value"><span class="team-value">${formatMoney(m.teamValue)}</span></td>
      <td class="col-squad">
        <button class="squad-btn" data-uid="${m.userId}" aria-label="Kader von ${escHtml(m.name)} anzeigen">
          Kader →
        </button>
      </td>
    `;
    $tableBody.appendChild(tr);
  });

  // Event-Delegation für Kader-Buttons
  $tableBody.querySelectorAll(".squad-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const uid = btn.dataset.uid;
      const manager = standings.find((m) => m.userId === uid);
      openModal(manager, squadsCache[activeLeagueId]?.[uid] || []);
    });
  });
}

function renderSquads(standings, squadsMap) {
  $squadsGrid.innerHTML = "";
  standings.forEach((m) => {
    const players = squadsMap[m.userId] || [];
    const card = buildSquadCard(m, players);
    $squadsGrid.appendChild(card);
  });
}

function buildSquadCard(manager, players) {
  const preview = players.slice(0, 5);
  const extra = players.length - preview.length;

  const card = document.createElement("div");
  card.className = "squad-card";
  card.setAttribute("role", "button");
  card.setAttribute("tabindex", "0");
  card.setAttribute("aria-label", `Kader von ${manager.name}`);

  const pillsHtml = preview.map((p) => `
    <div class="player-pill">
      <span class="pos-badge pos-${p.position}">${p.position}</span>
      <span class="player-pill-name">${escHtml(p.lastName)} ${escHtml(p.firstName?.[0] ?? "")}.`
        + `</span>
      <span class="player-mv">${formatMoney(p.marketValue)}</span>
    </div>
  `).join("");

  card.innerHTML = `
    <div class="squad-card-header">
      <span class="squad-manager">${escHtml(manager.name)}</span>
      <span class="squad-rank">Platz ${manager.rank} · ${manager.points ?? "–"} Pts</span>
    </div>
    <div class="squad-players-preview">${pillsHtml || '<p style="color:var(--text-muted);font-size:.82rem;padding:8px 0">Kader wird geladen …</p>'}</div>
    ${extra > 0 ? `<div class="squad-more">+ ${extra} weitere Spieler</div>` : ""}
  `;

  const openFn = () => openModal(manager, players);
  card.addEventListener("click", openFn);
  card.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") openFn(); });

  return card;
}

// ────────────────────────────────────────────────────────────
// 8. KADER LADEN (Firestore Subcollection)
// ────────────────────────────────────────────────────────────

function loadSquads(lg) {
  // Einmalig alle Squads dieser Liga laden
  db.collection("leagues")
    .doc(lg.id)
    .collection("squads")
    .get()
    .then((snapshot) => {
      if (!squadsCache[lg.id]) squadsCache[lg.id] = {};
      snapshot.forEach((doc) => {
        const data = doc.data();
        squadsCache[lg.id][data.userId] = data.players || [];
      });
      renderSquads(lg.standings || [], squadsCache[lg.id]);
    })
    .catch((err) => {
      console.error("Fehler beim Laden der Kader:", err);
    });
}

// ────────────────────────────────────────────────────────────
// 9. MODAL
// ────────────────────────────────────────────────────────────

function openModal(manager, players) {
  $modalTitle.textContent = `${manager.name} – Kader (${players.length} Spieler)`;
  $modalBody.innerHTML = "";

  if (!players.length) {
    $modalBody.innerHTML = `<p style="color:var(--text-muted);text-align:center;padding:24px">Keine Spieler vorhanden</p>`;
  } else {
    // Sortierung: TW → ABW → MF → STU
    const posOrder = { TW: 0, ABW: 1, MF: 2, STU: 3, "?": 4 };
    const sorted = [...players].sort((a, b) => (posOrder[a.position] ?? 9) - (posOrder[b.position] ?? 9));

    sorted.forEach((p) => {
      const el = document.createElement("div");
      el.className = "modal-player";
      el.innerHTML = `
        <span class="pos-badge pos-${p.position}">${p.position}</span>
        <div class="modal-player-info">
          <div class="modal-player-name">${escHtml(p.lastName)}${p.firstName ? ", " + escHtml(p.firstName) : ""}</div>
          <div class="modal-player-team">${escHtml(p.teamName || "–")}</div>
        </div>
        <div class="modal-player-stats">
          <span class="modal-player-pts">${p.totalPoints ?? "–"} Pts</span>
          <span class="player-mv">${formatMoney(p.marketValue)}</span>
        </div>
      `;
      $modalBody.appendChild(el);
    });
  }

  $modal.classList.remove("hidden");
  document.body.style.overflow = "hidden";
}

function closeModal() {
  $modal.classList.add("hidden");
  document.body.style.overflow = "";
}

$modalClose.addEventListener("click", closeModal);
$modal.addEventListener("click", (e) => { if (e.target === $modal) closeModal(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });

// ────────────────────────────────────────────────────────────
// 10. SECURITY – HTML ESCAPING
// ────────────────────────────────────────────────────────────

function escHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ────────────────────────────────────────────────────────────
// 11. FIRESTORE ECHTZEIT-LISTENER
// ────────────────────────────────────────────────────────────

function startListening() {
  // Listener auf die "leagues" Collection – reagiert auf Änderungen in Echtzeit
  db.collection("leagues").onSnapshot(
    (snapshot) => {
      if (snapshot.empty) {
        showError(
          "Keine Liga-Daten in Firestore gefunden. " +
          "Bitte führe den GitHub Actions Workflow einmal manuell aus."
        );
        return;
      }

      const prevActiveId = activeLeagueId;

      // Ligen-Array aufbauen und sortieren
      leagues = [];
      snapshot.forEach((doc) => {
        const d = doc.data();
        leagues.push({
          id: doc.id,
          name: d.name || doc.id,
          standings: d.standings || [],
          lastUpdated: d.lastUpdated,
          imageUrl: d.imageUrl || "",
        });
      });
      leagues.sort((a, b) => a.name.localeCompare(b.name, "de"));

      // Tabs neu rendern
      renderTabs();

      // Aktive Liga bestimmen
      const stillActive = prevActiveId && leagues.find((l) => l.id === prevActiveId);
      if (!stillActive) {
        activeLeagueId = leagues[0].id;
        document.getElementById(`tab-${activeLeagueId}`)?.classList.add("active");
      }

      const activeLg = leagues.find((l) => l.id === activeLeagueId);
      if (activeLg) renderLeague(activeLg);
    },
    (err) => {
      console.error("Firestore Fehler:", err);
      showError(`Firestore Fehler: ${err.message}`);
    }
  );
}

// ────────────────────────────────────────────────────────────
// 12. START
// ────────────────────────────────────────────────────────────
startListening();
