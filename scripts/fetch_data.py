#!/usr/bin/env python3
"""
Kickbase Liga Datenfetcher
Holt Tabellenstände und Manager-Kader von allen Kickbase-Ligen des Accounts
und schreibt die Daten in Firebase Firestore.
"""

import os
import json
import sys
import logging
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore

# ─── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# ─── Umgebungsvariablen laden ────────────────────────────────────────────────
load_dotenv()

KICKBASE_EMAIL = os.environ["KICKBASE_EMAIL"]
KICKBASE_PASSWORD = os.environ["KICKBASE_PASSWORD"]
FIREBASE_SERVICE_ACCOUNT_JSON = os.environ["FIREBASE_SERVICE_ACCOUNT_JSON"]

# Optional: Kommagetrennte Liga-IDs filtern (leer = alle Ligen)
_league_ids_env = os.environ.get("KICKBASE_LEAGUE_IDS", "").strip()
FILTER_LEAGUE_IDS = [x.strip() for x in _league_ids_env.split(",") if x.strip()]

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
        # Log keys for debugging (safe)
        log.info("Login-Antwort Keys: %s", list(data.keys()))
        
        self.token = data.get("tkn") or data.get("token") or data.get("accessToken")
        
        # User ID extraction
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
        # v4 leagues
        resp = self.session.get(f"{BASE_URL}/v4/leagues", timeout=30)
        log.info("GET /v4/leagues Status: %s", resp.status_code)
        
        leagues = []
        if resp.status_code == 200:
            data = resp.json()
            log.info("Leagues-Antwort Keys: %s", list(data.keys()))
            # 'lins' scheint der aktuelle v4 Key für 'Leagues In' zu sein
            leagues = data.get("leagues") or data.get("items") or data.get("lins") or data.get("l") or []
        
        if not leagues:
            # Fallback v2/v3
            log.info("Keine Ligen in v4 gefunden, versuche v2 Fallback...")
            resp2 = self.session.get(f"{BASE_URL}/user/leagues", timeout=30)
            if resp2.status_code == 200:
                leagues = resp2.json().get("leagues") or []
        
        # Manchmal ist die Antwort ein Dictionary und die Ligen liegen in einer Liste darin (z.B. 'leagues')
        if isinstance(leagues, dict):
            leagues = leagues.get("leagues") or leagues.get("items") or []

        log.info("Gefundene Ligen: %d", len(leagues))
        return leagues

    def get_standings_raw(self, league_id: str) -> dict:
        """Holt das komplette Ranking-Objekt (inkl. versteckter Infos)."""
        resp = self.session.get(f"{BASE_URL}/v4/leagues/{league_id}/ranking", timeout=30)
        if resp.status_code == 200:
            return resp.json()
        return {}

    def get_all_players(self, league_id: str) -> list[dict]:
        """Holt den gesamten Spielerpool der Liga (für Meta-Daten Suche)."""
        # Versuch v4 Pool Varianten
        urls = [
            f"{BASE_URL}/v4/leagues/{league_id}/players",
            f"{BASE_URL}/v4/leagues/{league_id}/market",
        ]
        for url in urls:
            resp = self.session.get(url, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                players = data.get("players") or data.get("items") or data.get("p") or []
                if players:
                    return players
        
        # Fallback v2/v3
        resp2 = self.session.get(f"{BASE_URL}/leagues/{league_id}/market", timeout=30)
        if resp2.status_code == 200:
            return resp2.json().get("players") or []
            
        return []

    def get_player_details_bulk(self, player_ids: list[str]) -> list[dict]:
        """Versucht Meta-Daten für eine Liste von Player-IDs zu holen."""
        if not player_ids:
            return []
        
        results = []
        # Da Bulk oft 404 liefert, probieren wir es für die ersten 5-10 Spieler einzeln
        # um zu sehen, ob der Endpoint überhaupt existiert.
        for pid in player_ids[:15]:
            try:
                resp = self.session.get(f"{BASE_URL}/v4/players/{pid}", timeout=5)
                if resp.status_code == 200:
                    results.append(resp.json())
            except:
                pass
        return results

    def get_squad(self, league_id: str, manager_user_id: str) -> list[dict]:
        """Kader eines Managers in einer bestimmten Liga."""
        # Liste möglicher Endpunkte (v4 und Fallbacks)
        endpoints = [
            f"{BASE_URL}/v4/leagues/{league_id}/ranking?managerId={manager_user_id}", # v4 Ranking Detail
            f"{BASE_URL}/v4/leagues/{league_id}/lineup?managerId={manager_user_id}", # v4 Lineup Query
        ]
        
        for url in endpoints:
            try:
                resp = self.session.get(url, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    players = []
                    # v4: Die Spieler sind oft unter data['u']['pl'] oder data['pl']
                    if isinstance(data, dict):
                        # Wenn wir ranking?managerId abrufen, liegt der User oft unter 'u' oder 'user'
                        u_obj = data.get("u") or data.get("user") or data
                        if isinstance(u_obj, dict):
                            players = u_obj.get("pl") or u_obj.get("players") or u_obj.get("lineup") or []
                    
                    if players:
                        return players
            except Exception as e:
                log.debug("Fehler bei %s: %s", url, e)

        return []


# ─── Hilfsfunktionen ─────────────────────────────────────────────────────────

POSITION_MAP = {1: "TW", 2: "ABW", 3: "MF", 4: "STU"}


def _clean_player(raw: dict) -> dict:
    """Normalisiert einen Spieler-Datensatz auf die Felder, die wir brauchen."""
    return {
        "id": str(raw.get("i") or raw.get("id", "")),
        "firstName": raw.get("fn") or raw.get("firstName") or "",
        "lastName": raw.get("ln") or raw.get("lastName") or raw.get("name") or "",
        "teamName": raw.get("tn") or raw.get("teamName") or raw.get("team", {}).get("name") if isinstance(raw.get("team"), dict) else raw.get("teamName", ""),
        "position": POSITION_MAP.get(raw.get("pos") or raw.get("position"), "?"),
        "marketValue": raw.get("mv") or raw.get("marketValue") or 0,
        "totalPoints": raw.get("tp") or raw.get("totalPoints") or raw.get("points") or 0,
        "status": raw.get("s") or raw.get("status", 0),
    }


def _clean_manager(raw: dict, rank: int) -> dict:
    """Normalisiert einen Manager-/Standings-Eintrag."""
    # User-Objekt kann direkt in raw oder unter 'u' liegen
    user_data = raw.get("u") if isinstance(raw.get("u"), dict) else raw
    
    return {
        "rank": rank,
        "userId": str(user_data.get("i") or user_data.get("userId") or raw.get("id", "")),
        "name": user_data.get("n") or user_data.get("name") or user_data.get("userName") or "Unbekannt",
        "profileUrl": user_data.get("pu") or user_data.get("profileUrl", ""),
        "points": raw.get("sp") or raw.get("pt") or raw.get("points") or raw.get("totalPoints") or 0,
        "teamValue": raw.get("tv") or raw.get("teamValue") or 0,
        "budget": raw.get("b") or raw.get("budget") or 0,
        "squadSize": raw.get("sq") or raw.get("squadSize") or 0,
    }


# ─── Firestore ───────────────────────────────────────────────────────────────

def init_firestore():
    """Firebase-Admin initialisieren. Gibt den Firestore-Client zurück."""
    service_account_info = json.loads(FIREBASE_SERVICE_ACCOUNT_JSON)
    cred = credentials.Certificate(service_account_info)
    firebase_admin.initialize_app(cred)
    return firestore.client()


def write_league_to_firestore(db, league: dict, standings: list, squads: dict):
    """Schreibt alle Daten einer Liga in Firestore."""
    league_id = str(league.get("i") or league.get("id") or "")
    league_name = league.get("n") or league.get("name") or league_id

    if not league_id:
        log.error("Kann Liga ohne ID nicht speichern: %s", league)
        return

    log.info("Schreibe Liga '%s' (%s) in Firestore ...", league_name, league_id)

    now = datetime.now(timezone.utc)

    # Liga-Metadaten & Tabelle
    league_ref = db.collection("leagues").document(league_id)
    league_ref.set(
        {
            "id": league_id,
            "name": league_name,
            "imageUrl": league.get("imageUrl") or league.get("leagueImage", ""),
            "standings": standings,
            "lastUpdated": now,
        }
    )
    log.info("  ✓ Liga-Dokument + %d Standings gespeichert", len(standings))

    # Kader pro Manager
    batch = db.batch()
    squad_count = 0
    for manager_data in standings:
        uid = manager_data.get("userId", "")
        if not uid:
            continue
        squad = squads.get(uid, [])
        squad_ref = league_ref.collection("squads").document(uid)
        batch.set(
            squad_ref,
            {
                "userId": uid,
                "managerName": manager_data.get("name", ""),
                "players": squad,
                "lastUpdated": now,
            },
        )
        squad_count += 1

    batch.commit()
    log.info("  ✓ %d Manager-Kader gespeichert", squad_count)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    log.info("═══ Kickbase Datenfetcher gestartet ═══")

    # 1. Firebase initialisieren
    db = init_firestore()

    # 2. Kickbase Login
    kb = KickbaseClient()
    kb.login(KICKBASE_EMAIL, KICKBASE_PASSWORD)

    # 3. Ligen abrufen
    all_leagues = kb.get_leagues()

    if FILTER_LEAGUE_IDS:
        leagues = [lg for lg in all_leagues if str(lg.get("id")) in FILTER_LEAGUE_IDS]
        log.info("Gefiltertete Ligen: %d von %d", len(leagues), len(all_leagues))
    else:
        leagues = all_leagues

    if not leagues:
        log.error("Keine Ligen gefunden! Bitte KICKBASE_LEAGUE_IDS prüfen.")
        sys.exit(1)

    # 4. Für jede Liga: Standings + Kader holen und in Firestore schreiben
    for league in leagues:
        league_id = str(league.get("i") or league.get("id") or "")
        league_name = league.get("n") or league.get("name") or league_id
        log.info("── Verarbeite Liga: '%s' (%s) ──", league_name, league_id)

        if not league_id:
            continue

        # 4a. Komplettes Ranking holen
        ranking_data = kb.get_standings_raw(league_id)
        raw_standings = ranking_data.get("us") or ranking_data.get("users") or []
        
        if not raw_standings:
            log.warning("Keine Standings für Liga %s", league_id)
            continue

        # Debug: Was steckt in 'il' oder 'nd'?
        il_data = ranking_data.get("il") or []
        log.info("   'il' (Teams/Info) enthält %d Einträge", len(il_data) if isinstance(il_data, list) else 0)
        
        # Mapping bauen aus 'il' (oft sind das die Team/Player-Metadaten in v4)
        meta_map = {}
        if isinstance(il_data, list):
            for item in il_data:
                iid = str(item.get("i") or item.get("id") or "")
                if iid:
                    meta_map[iid] = item

        # Sortiere nach Punkten (sp) absteigend
        raw_standings.sort(key=lambda x: x.get("sp") or 0, reverse=True)
        cleaned_standings = [_clean_manager(m, i + 1) for i, m in enumerate(raw_standings)]

        # 4b. Metadata-Mapping vervollständigen
        all_players_raw = kb.get_all_players(league_id)
        player_map = {str(p.get("i") or p.get("id")): _clean_player(p) for p in all_players_raw}
        
        # Ergänze aus meta_map (il)
        for iid, m_data in meta_map.items():
            if iid not in player_map:
                player_map[iid] = _clean_player(m_data)

        log.info("   Spieler-Metadaten geladen: %d Spieler bekannt", len(player_map))

        # Kader pro Manager
        squads = {}
        for manager in cleaned_standings:
            uid = manager.get("userId", "")
            if not uid:
                continue
            
            # Hole Player IDs aus 'lp' (Lineup Players)
            manager_raw = next((m for m in raw_standings if str(m.get("i") or m.get("id")) == uid), {})
            player_ids = manager_raw.get("lp", [])
            
            if not isinstance(player_ids, list):
                player_ids = []

            # Versuche Kader-Details über Player-Pool zu mappen
            current_squad = []
            for pid in player_ids:
                pid_str = str(pid)
                if pid_str in player_map:
                    current_squad.append(player_map[pid_str])
                else:
                    # Fallback: Wenigstens die ID speichern
                    current_squad.append({"id": pid_str, "lastName": f"Spieler {pid_str}", "teamName": "Unbekannt", "position": "?", "marketValue": 0, "totalPoints": 0})

            # Falls 'lp' leer war, versuchen wir den alten API-Weg (Fallback)
            if not current_squad:
                raw_squad = kb.get_squad(league_id, uid)
                current_squad = [_clean_player(p) for p in raw_squad]

            squads[uid] = current_squad
            log.info("   Kader von %s: %d Spieler", manager["name"], len(squads[uid]))

        # In Firestore schreiben
        write_league_to_firestore(db, league, cleaned_standings, squads)

    log.info("═══ Fertig! Alle Daten gespeichert. ═══")


if __name__ == "__main__":
    main()
