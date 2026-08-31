#!/usr/bin/env python3
"""
Kickbase Liga Datenfetcher

Holt die Tabellenstände aller Kickbase-Ligen des Accounts und schreibt sie als
statische JSON-Datei nach public/data/leagues.json. Kein Firebase, keine
Datenbank – die Datei wird vom GitHub-Actions-Workflow erzeugt und direkt mit
auf GitHub Pages deployed.
"""

import os
import json
import sys
import logging
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

# ─── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# ─── Umgebungsvariablen laden ────────────────────────────────────────────────
load_dotenv()

try:
    KICKBASE_EMAIL = os.environ["KICKBASE_EMAIL"]
    KICKBASE_PASSWORD = os.environ["KICKBASE_PASSWORD"]
except KeyError as missing:
    log.error("Umgebungsvariable %s fehlt. Siehe .env.example.", missing)
    sys.exit(1)

# Optional: Kommagetrennte Liga-IDs filtern (leer = alle Ligen)
_league_ids_env = os.environ.get("KICKBASE_LEAGUE_IDS", "").strip()
FILTER_LEAGUE_IDS = [x.strip() for x in _league_ids_env.split(",") if x.strip()]

# Manager, die in einer Liga nicht in der Tabelle auftauchen sollen (z. B. Admins,
# die dort nur verwalten und nicht mitspielen). Pro Liga-ID eine Menge von
# User-IDs – bewusst NICHT global, weil dieselben Accounts in der anderen Liga
# ganz normal mitspielen.
AUSGESCHLOSSENE_MANAGER = {
    # SG Bega/Humfeld II – Christopher und Julian sind hier nur Admins
    "6853982": {"2644886", "3185901"},
}

# Zielpfad der generierten Datei (Repo-Root/public/data/leagues.json)
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "public" / "data" / "leagues.json"

# ─── Kickbase API ────────────────────────────────────────────────────────────
BASE_URL = "https://api.kickbase.com"
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Kickbase/ios",
}


class KickbaseClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.token = None
        self.user_id = ""

    def login(self, email: str, password: str) -> None:
        """Authentifizierung gegen die Kickbase API v4."""
        payload = {"em": email, "pass": password, "loy": False, "rep": {}}
        log.info("Logge mich bei Kickbase ein ...")
        resp = self.session.post(f"{BASE_URL}/v4/user/login", json=payload, timeout=30)

        if resp.status_code != 200:
            log.error("Login fehlgeschlagen: %s – %s", resp.status_code, resp.text)
            sys.exit(1)

        data = resp.json()
        self.token = data.get("tkn") or data.get("token") or data.get("accessToken")

        user_obj = data.get("user") or data.get("u") or {}
        if isinstance(user_obj, dict):
            self.user_id = str(user_obj.get("id") or user_obj.get("i") or "")
        else:
            self.user_id = str(user_obj)

        if not self.token:
            log.error("Kein Token in der Antwort gefunden. Antwort-Struktur: %s", list(data.keys()))
            sys.exit(1)

        self.session.headers["Authorization"] = f"Bearer {self.token}"
        log.info("Login erfolgreich. User-ID: '%s'", self.user_id)

    def get_leagues(self) -> list[dict]:
        """Gibt alle Ligen zurück, in denen der User Mitglied ist."""
        resp = self.session.get(f"{BASE_URL}/v4/leagues", timeout=30)
        log.info("GET /v4/leagues Status: %s", resp.status_code)

        leagues = []
        if resp.status_code == 200:
            data = resp.json()
            # 'lins' ist der aktuelle v4 Key für 'Leagues In'
            leagues = data.get("leagues") or data.get("items") or data.get("lins") or data.get("l") or []

        if not leagues:
            log.info("Keine Ligen in v4 gefunden, versuche v2 Fallback ...")
            resp2 = self.session.get(f"{BASE_URL}/user/leagues", timeout=30)
            if resp2.status_code == 200:
                leagues = resp2.json().get("leagues") or []

        if isinstance(leagues, dict):
            leagues = leagues.get("leagues") or leagues.get("items") or []

        log.info("Gefundene Ligen: %d", len(leagues))
        return leagues

    def get_standings_raw(self, league_id: str) -> dict:
        """Holt das komplette Ranking-Objekt einer Liga."""
        resp = self.session.get(f"{BASE_URL}/v4/leagues/{league_id}/ranking", timeout=30)
        if resp.status_code != 200:
            log.warning("Ranking für Liga %s fehlgeschlagen: %s", league_id, resp.status_code)
            return {}
        return resp.json()


# ─── Hilfsfunktionen ─────────────────────────────────────────────────────────

def _clean_manager(raw: dict) -> dict:
    """Normalisiert einen Manager-/Standings-Eintrag (ohne Rang)."""
    # User-Objekt kann direkt in raw oder unter 'u' liegen
    user_data = raw.get("u") if isinstance(raw.get("u"), dict) else raw
    name = user_data.get("n") or user_data.get("name") or user_data.get("userName") or "Unbekannt"

    return {
        "userId": str(user_data.get("i") or user_data.get("userId") or raw.get("id", "")),
        # Kickbase liefert Namen teils mit Leerzeichen am Ende
        "name": str(name).strip(),
        "points": raw.get("sp") or raw.get("pt") or raw.get("points") or raw.get("totalPoints") or 0,
        "teamValue": raw.get("tv") or raw.get("teamValue") or 0,
    }


def _league_id(league: dict) -> str:
    return str(league.get("i") or league.get("id") or "")


def _league_name(league: dict) -> str:
    return league.get("n") or league.get("name") or _league_id(league)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    log.info("═══ Kickbase Datenfetcher gestartet ═══")

    kb = KickbaseClient()
    kb.login(KICKBASE_EMAIL, KICKBASE_PASSWORD)

    all_leagues = kb.get_leagues()

    if FILTER_LEAGUE_IDS:
        leagues = [lg for lg in all_leagues if _league_id(lg) in FILTER_LEAGUE_IDS]
        log.info("Gefilterte Ligen: %d von %d", len(leagues), len(all_leagues))
    else:
        leagues = all_leagues

    if not leagues:
        log.error("Keine Ligen gefunden! Bitte KICKBASE_LEAGUE_IDS prüfen.")
        sys.exit(1)

    result_leagues = []

    for league in leagues:
        league_id = _league_id(league)
        league_name = _league_name(league)

        if not league_id:
            log.warning("Liga ohne ID übersprungen: %s", league)
            continue

        log.info("── Verarbeite Liga: '%s' (%s) ──", league_name, league_id)

        ranking_data = kb.get_standings_raw(league_id)
        raw_standings = ranking_data.get("us") or ranking_data.get("users") or []

        if not raw_standings:
            log.warning("Keine Standings für Liga %s – übersprungen", league_id)
            continue

        raw_standings.sort(key=lambda x: x.get("sp") or 0, reverse=True)
        standings = [_clean_manager(m) for m in raw_standings]

        # Admins o. Ä. entfernen, bevor die Ränge vergeben werden – so bleibt
        # die Tabelle lückenlos von 1 an durchnummeriert.
        ausgeschlossen = AUSGESCHLOSSENE_MANAGER.get(league_id, set())
        if ausgeschlossen:
            vorher = len(standings)
            entfernt = [m["name"] for m in standings if m["userId"] in ausgeschlossen]
            standings = [m for m in standings if m["userId"] not in ausgeschlossen]
            log.info("  ⊘ %d von %d Managern ausgeschlossen: %s",
                     vorher - len(standings), vorher, ", ".join(entfernt) or "–")

        for i, manager in enumerate(standings):
            manager["rank"] = i + 1

        if not standings:
            log.warning("Liga %s hat nach dem Ausschluss keine Manager mehr – übersprungen", league_id)
            continue

        result_leagues.append({
            "id": league_id,
            "name": league_name,
            "standings": standings,
        })
        log.info("  ✓ %d Manager in der Tabelle", len(standings))

    if not result_leagues:
        # Lieber mit Fehler abbrechen, als die bestehende Seite mit leeren Daten
        # zu überschreiben – das letzte erfolgreiche Deployment bleibt dann online.
        log.error("Keine einzige Liga mit Tabellendaten – breche ab, ohne zu schreiben.")
        sys.exit(1)

    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "leagues": result_leagues,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    log.info("═══ Fertig: %d Ligen → %s ═══", len(result_leagues), OUTPUT_PATH)


if __name__ == "__main__":
    main()
