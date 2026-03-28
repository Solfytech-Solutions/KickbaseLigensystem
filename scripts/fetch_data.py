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
        if data.get("srvl"):
            log.info("Server-Liste (srvl): %s", data.get("srvl"))

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
        """Holt den gesamten Spielerpool der Bundesliga (v4 Competitions)."""
        # Bundesliga Competition ID ist 1
        url = f"{BASE_URL}/v4/competitions/1/players"
        all_meta_players = []
        try:
            resp = self.session.get(url, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                log.info("   Metadaten-Keys gefunden: %s", list(data.keys()))
                it_list = data.get("it") or []
                log.info("   Feld 'it' enthält %d Einträge", len(it_list))
                all_meta_players.extend(it_list)
        except Exception as e:
            log.warning("Fehler beim Laden des globalen Spielerpools: %s", e)
        
        # NEU: Falls 'it' zu klein ist, versuchen wir Team-Details
        if len(all_meta_players) < 100:
            log.info("   Pool zu klein (%d), versuche über Teams zu laden...", len(all_meta_players))
            try:
                teams_resp = self.session.get(f"{BASE_URL}/v4/competitions/1/teams", timeout=15)
                if teams_resp.status_code == 200:
                    teams = teams_resp.json().get("it") or []
                    log.info("   %d Teams gefunden. Lade Kader-Metadaten...", len(teams))
                    for t in teams:
                        tid = t.get("i") or t.get("id")
                        if tid:
                            t_resp = self.session.get(f"{BASE_URL}/v4/competitions/1/teams/{tid}/teamprofile", timeout=10)
                            if t_resp.status_code == 200:
                                t_data = t_resp.json()
                                t_players = t_data.get("it") or []
                                # Team-Name für alle Spieler dieses Teams setzen
                                tn = t_data.get("tn") or t_data.get("name")
                                for tp in t_players:
                                    if tn: tp["tn"] = tn
                                all_meta_players.extend(t_players)
                    log.info("   Pool nach Team-Batch: %d Spieler", len(all_meta_players))
            except Exception as e:
                log.warning("Fehler beim Team-Batch-Laden: %s", e)

        if all_meta_players:
            return all_meta_players
        
        # Fallback v2/v3
        resp2 = self.session.get(f"{BASE_URL}/leagues/{league_id}/market", timeout=30)
        if resp2.status_code == 200:
            return resp2.json().get("players") or []
            
        return []

    def get_manager_full_squad(self, league_id: str, manager_user_id: str) -> list[dict]:
        """Holt den KOMPLETTEN Kader (Lineup + Bank) eines Managers."""
        url = f"{BASE_URL}/v4/leagues/{league_id}/managers/{manager_user_id}/squad"
        try:
            resp = self.session.get(url, timeout=30)
            if resp.status_code == 200:
                return resp.json().get("it") or []
        except Exception as e:
            log.warning("Fehler beim Laden des vollen Kaders (%s): %s", manager_user_id, e)
        return []

    def get_squad(self, league_id: str, manager_user_id: str) -> list[dict]:
        """Kader eines Managers (Lineup v4 Fallback)."""
        return self.get_manager_full_squad(league_id, manager_user_id)


# ─── Hilfsfunktionen ─────────────────────────────────────────────────────────

POSITION_MAP = {1: "TW", 2: "ABW", 3: "MF", 4: "STU"}


def _clean_player(raw: dict) -> dict:
    """Normalisiert einen Spieler-Datensatz auf die Felder, die wir brauchen."""
    # v4 nutzt pi oder i für ID, pn oder n oder ln für Name
    p_id = str(raw.get("pi") or raw.get("i") or raw.get("id", ""))
    first_name = raw.get("fn") or raw.get("firstName") or ""
    last_name = raw.get("pn") or raw.get("n") or raw.get("ln") or raw.get("lastName") or raw.get("name") or "Unbekannt"
    
    # Team-Name extraktion (tn oder aus team Objekt)
    t_name = raw.get("tn") or raw.get("teamName") or ""
    if not t_name and isinstance(raw.get("team"), dict):
        t_name = raw.get("team", {}).get("name", "")

    return {
        "id": p_id,
        "firstName": first_name,
        "lastName": last_name,
        "teamName": t_name,
        "position": POSITION_MAP.get(raw.get("pos") or raw.get("position"), "?"),
        "marketValue": raw.get("mv") or raw.get("marketValue") or 0,
        "totalPoints": raw.get("p") or raw.get("tp") or raw.get("totalPoints") or raw.get("points") or 0,
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

        # 4a. Standings sortieren und säubern
        raw_standings.sort(key=lambda x: x.get("sp") or 0, reverse=True)
        cleaned_standings = [_clean_manager(m, i + 1) for i, m in enumerate(raw_standings)]

        # 4b. Metadata-Mapping (Pool laden)
        all_players_raw = kb.get_all_players(league_id)
        # v4 nutzt 'pi' oder 'i' für ID
        player_map = {str(p.get("pi") or p.get("i") or p.get("id")): _clean_player(p) for p in all_players_raw}
        log.info("   Spieler-Metadaten geladen: %d Spieler bekannt", len(player_map))

        # 4c. Kader pro Manager (Volle Kader inkl. Bank laden)
        squads = {}
        for manager_profile in cleaned_standings:
            uid = manager_profile.get("userId", "")
            if not uid:
                continue
            
            log.info("   Lade VOLLEN Kader von %s...", manager_profile["name"])
            raw_squad = kb.get_manager_full_squad(league_id, uid)
            
            current_squad = []
            if raw_squad:
                # Wir mappen die v4 Rohdaten über unseren Pool, um sicher zu gehen,
                # aber nutzen vorrangig die Daten aus dem Squad-Endpoint selbst.
                for p_raw in raw_squad:
                    p_cleaned = _clean_player(p_raw)
                    # Falls Spieler im globalen Pool bessere Daten hat:
                    if p_cleaned["id"] in player_map:
                        # Kombination: Aktuelle Stats aus Squad + Teamnamen/Namen aus Pool
                        p_pool = player_map[p_cleaned["id"]]
                        p_cleaned["firstName"] = p_cleaned["firstName"] or p_pool["firstName"]
                        p_cleaned["lastName"] = p_cleaned["lastName"] or p_pool["lastName"]
                        p_cleaned["teamName"] = p_cleaned["teamName"] or p_pool["teamName"]
                    
                    current_squad.append(p_cleaned)
            else:
                # Fallback auf 'lp' IDs aus dem Ranking (nur Lineup), falls Squad-Endpoint fehlschlägt
                manager_raw = next((m for m in raw_standings if str(m.get("i") or m.get("id")) == uid), {})
                player_ids = manager_raw.get("lp", []) or []
                for pid in player_ids:
                    pid_str = str(pid)
                    if pid_str in player_map:
                        current_squad.append(player_map[pid_str])
                    else:
                        current_squad.append({"id": pid_str, "lastName": f"Spieler {pid_str}", "teamName": "Kickbase v4", "position": "?", "marketValue": 0, "totalPoints": 0})
            
            squads[uid] = current_squad
            log.info("   ✓ Kader von %s: %d Spieler", manager_profile["name"], len(current_squad))

        # In Firestore schreiben
        write_league_to_firestore(db, league, cleaned_standings, squads)

    log.info("═══ Fertig! Alle Daten gespeichert. ═══")


if __name__ == "__main__":
    main()
