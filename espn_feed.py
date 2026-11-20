from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
import re
import requests

from dst_engine import DSTStats

BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"
HEADERS = {"User-Agent": "Mozilla/5.0"}

# ESPN play-by-play text sometimes uses legacy GSIS codes different from scoreboard abbrs
TEXT_ABBR_ALIASES: dict[str, set[str]] = {
    "WSH": {"WSH", "WAS"},
    "HOU": {"HOU", "HST"},
    "BAL": {"BAL", "BLT"},
    "CLE": {"CLE", "CLV"},
    "ARI": {"ARI", "ARZ"},
    "LAR": {"LAR", "LA"},
    "LV": {"LV", "LVR", "OAK"},
    "LAC": {"LAC", "SD"},
    "JAX": {"JAX", "JAC"},
}

SCRIMMAGE_YARD_TYPES = {
    "Rush",
    "Rushing Touchdown",
    "Pass Reception",
    "Passing Touchdown",
    "Pass Incompletion",
    "Sack",
    "Sack Opp Fumble Recovery",
    "Fumble Recovery (Own)",
    "Fumble Recovery (Opponent)",
    "Fumble Return Touchdown",
    "Interception Return",
    "Pass Interception Return",
    "Interception Return Touchdown",
    "Safety",
}

NON_SCRIMMAGE_TYPES = {
    "Kickoff",
    "Kickoff Return (Offense)",
    "Kickoff Return Touchdown",
    "Punt",
    "Punt Return Touchdown",
    "Blocked Punt",
    "Blocked Punt Touchdown",
    "Field Goal Good",
    "Field Goal Missed",
    "Blocked Field Goal",
    "Blocked Field Goal Touchdown",
    "Extra Point Good",
    "Extra Point Missed",
    "Two-Point Pass",
    "Two-Point Rush",
    "Timeout",
    "Official Timeout",
    "Two-Minute Warning",
    "End Period",
    "End of Half",
    "End of Game",
    "Coin Toss",
}


@dataclass
class GameListing:
    event_id: str
    short_name: str
    state: str  # "pre", "in", "post"
    status_detail: str
    away_id: str
    away_abbr: str
    away_name: str
    away_score: int
    home_id: str
    home_abbr: str
    home_name: str
    home_score: int
    week: Optional[int] = None
    season_year: Optional[int] = None


@dataclass
class GameSnapshot:
    event_id: str
    defense_team_id: str
    defense_abbr: str
    defense_name: str
    opponent_id: str
    opponent_abbr: str
    opponent_name: str
    game_state: str  # "pre", "in", "post"
    status_text: str
    quarter: int
    clock: str
    down_distance: str
    possession_abbr: Optional[str]
    defense_score: int
    opponent_score: int
    last_play_text: str
    stats: DSTStats
    fetched_at_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    play_index: Optional[int] = None


def fetch_scoreboard(week: Optional[int] = None, seasontype: int = 2) -> tuple[list[GameListing], dict]:
    params: dict[str, Any] = {}
    if week is not None:
        params["seasontype"] = seasontype
        params["week"] = week
    resp = requests.get(f"{BASE_URL}/scoreboard", params=params, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    current_week = data.get("week", {}).get("number")
    season_year = data.get("season", {}).get("year")
    meta = {"week": current_week, "season_year": season_year}

    games: list[GameListing] = []
    for ev in data.get("events", []):
        comp = ev.get("competitions", [{}])[0]
        competitors = comp.get("competitors", [])
        home = next((c for c in competitors if c.get("homeAway") == "home"), None)
        away = next((c for c in competitors if c.get("homeAway") == "away"), None)
        if not home or not away:
            continue
        status_type = ev.get("status", {}).get("type", {})
        games.append(
            GameListing(
                event_id=str(ev["id"]),
                short_name=ev.get("shortName", ""),
                state=status_type.get("state", "pre"),
                status_detail=status_type.get("shortDetail", ""),
                away_id=str(away["team"]["id"]),
                away_abbr=away["team"]["abbreviation"],
                away_name=away["team"].get("displayName", away["team"]["abbreviation"]),
                away_score=_to_int(away.get("score", 0)),
                home_id=str(home["team"]["id"]),
                home_abbr=home["team"]["abbreviation"],
                home_name=home["team"].get("displayName", home["team"]["abbreviation"]),
                home_score=_to_int(home.get("score", 0)),
                week=current_week,
                season_year=season_year,
            )
        )
    return games, meta


def fetch_game_summary(event_id: str) -> dict:
    resp = requests.get(
        f"{BASE_URL}/summary",
        params={"event": str(event_id)},
        headers=HEADERS,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def _to_int(val: Any, default: int = 0) -> int:
    try:
        return int(float(str(val).strip()))
    except (ValueError, TypeError):
        return default


def _parse_sacks_from_str(val: str) -> int:
    if not val:
        return 0
    return _to_int(str(val).split("-")[0], 0)


def _abbr_aliases(abbr: str) -> set[str]:
    u = abbr.upper()
    return TEXT_ABBR_ALIASES.get(u, {u})


def _get_teams_from_summary(summary: dict, defense_team_id: str) -> tuple[dict, dict, dict]:
    header_comp = summary.get("header", {}).get("competitions", [{}])[0]
    competitors = header_comp.get("competitors", [])
    def_comp = next((c for c in competitors if str(c["team"]["id"]) == str(defense_team_id)), None)
    opp_comp = next((c for c in competitors if str(c["team"]["id"]) != str(defense_team_id)), None)
    if not def_comp or not opp_comp:
        raise ValueError(f"Team id {defense_team_id} not found in game summary.")
    return def_comp, opp_comp, header_comp


def _all_drives_plays(summary: dict) -> list[tuple[dict, dict]]:
    drives_obj = summary.get("drives", {})
    drives = list(drives_obj.get("previous", []))
    current = drives_obj.get("current")
    if isinstance(current, dict) and current.get("plays"):
        prev_ids = {d.get("id") for d in drives}
        if current.get("id") not in prev_ids:
            drives.append(current)
    out: list[tuple[dict, dict]] = []
    for drive in drives:
        for play in drive.get("plays", []):
            out.append((drive, play))
    return out


def _classify_opponent_scoring_exclusion(play_type: str, text: str) -> tuple[int, Optional[str]]:
    """
    Standard ESPN D/ST rules:
    - Opponent Interception Return TD or offensive Fumble Return TD: -6 from PA (PAT still counts)
    - Opponent Safety while our offense is on the field: -2 from PA
    - Punt/Kickoff/Blocked Kick return TDs DO count against our D/ST (special teams on field)
    """
    pt = (play_type or "").lower()
    tx = (text or "").lower()

    if "interception return" in pt or ("intercepted" in tx and "touchdown" in tx):
        return 6, "Excluded 6 pts: Opponent pick-six (PAT still counts)"

    if "fumble return" in pt and "punt" not in tx and "kick" not in tx and "blocked" not in tx:
        return 6, "Excluded 6 pts: Opponent fumble-return TD vs offense (PAT still counts)"

    if "safety" in pt or ("safety" in tx and "1pt" not in tx and "1-pt" not in tx):
        if "punt" not in tx and "blocked" not in tx:
            return 2, "Excluded 2 pts: Safety conceded by offense"

    return 0, None


def _is_our_dst_td(play_type: str, text: str) -> bool:
    pt = (play_type or "").lower()
    tx = (text or "").lower()
    dst_td_markers = (
        "interception return",
        "fumble return",
        "kickoff return",
        "punt return",
        "blocked punt",
        "blocked field goal",
        "missed field goal return",
    )
    return any(m in pt for m in dst_td_markers) and ("touchdown" in pt or "touchdown" in tx)


def _is_blocked_kick_by_defense(drive_team_id: str, defense_team_id: str, play_type: str, text: str) -> bool:
    if str(drive_team_id) == str(defense_team_id):
        return False
    pt = (play_type or "").lower()
    tx = (text or "").lower()
    if "blocked punt" in pt or "blocked field goal" in pt or "blocked pat" in pt:
        return True
    if "blocked by" in tx and any(k in tx for k in ("punt", "field goal", "extra point", "pat")):
        return True
    return False


def parse_live_game(summary: dict, defense_team_id: str) -> GameSnapshot:
    def_comp, opp_comp, header_comp = _get_teams_from_summary(summary, defense_team_id)
    def_id = str(def_comp["team"]["id"])
    opp_id = str(opp_comp["team"]["id"])
    def_abbr = def_comp["team"]["abbreviation"]
    opp_abbr = opp_comp["team"]["abbreviation"]
    def_name = def_comp["team"].get("displayName", def_abbr)
    opp_name = opp_comp["team"].get("displayName", opp_abbr)

    def_score = _to_int(def_comp.get("score", 0))
    opp_score = _to_int(opp_comp.get("score", 0))

    status_obj = header_comp.get("status", {})
    status_type = status_obj.get("type", {})
    game_state = status_type.get("state", "pre")
    status_text = status_type.get("shortDetail", status_type.get("description", ""))
    quarter = _to_int(status_obj.get("period", 0))
    clock = status_obj.get("displayClock", "0:00")

    opp_stats_map: dict[str, str] = {}
    for team_box in summary.get("boxscore", {}).get("teams", []):
        if str(team_box.get("team", {}).get("id")) == opp_id:
            for s in team_box.get("statistics", []):
                opp_stats_map[s.get("name", "")] = str(s.get("displayValue", ""))

    yards_allowed = _to_int(opp_stats_map.get("totalYards", 0))
    sacks = float(_parse_sacks_from_str(opp_stats_map.get("sacksYardsLost", "0-0")))
    interceptions = _to_int(opp_stats_map.get("interceptions", 0))
    fumble_recoveries = _to_int(opp_stats_map.get("fumblesLost", 0))

    dst_tds = 0
    safeties = 0
    two_pt_returns = 0
    one_pt_safeties = 0
    excluded_pts = 0
    excluded_notes: list[str] = []

    for sp in summary.get("scoringPlays", []):
        sp_team_id = str(sp.get("team", {}).get("id", ""))
        sp_type = sp.get("type", {}).get("text", "")
        sp_scoring_type = sp.get("scoringType", {}).get("name", "")
        sp_text = sp.get("text", "")

        if sp_team_id == def_id:
            if _is_our_dst_td(sp_type, sp_text):
                dst_tds += 1
            elif sp_scoring_type == "safety" or "safety" in sp_type.lower():
                if "1-pt" in sp_text.lower() or "one-point" in sp_text.lower():
                    one_pt_safeties += 1
                else:
                    safeties += 1
            elif "defensive 2" in sp_type.lower() or (
                "defensive" in sp_text.lower() and "two-point" in sp_text.lower()
            ):
                two_pt_returns += 1
        elif sp_team_id == opp_id:
            ex_pts, note = _classify_opponent_scoring_exclusion(sp_type, sp_text)
            if ex_pts > 0:
                excluded_pts += ex_pts
                if note:
                    excluded_notes.append(note)

    blocked_kicks = 0
    all_plays = _all_drives_plays(summary)
    for drive, play in all_plays:
        drive_team_id = str(drive.get("team", {}).get("id", ""))
        if _is_blocked_kick_by_defense(
            drive_team_id,
            def_id,
            play.get("type", {}).get("text", ""),
            play.get("text", ""),
        ):
            blocked_kicks += 1

    down_distance = ""
    possession_abbr: Optional[str] = None
    last_play_text = ""

    if all_plays:
        last_drive, last_play = all_plays[-1]
        last_play_text = last_play.get("text", "")
        end_info = last_play.get("end", {}) or {}
        down_distance = end_info.get("downDistanceText", "") or end_info.get("shortDownDistanceText", "")
        poss_team_id = str(end_info.get("team", {}).get("id") or last_drive.get("team", {}).get("id") or "")
        if poss_team_id == def_id:
            possession_abbr = def_abbr
        elif poss_team_id == opp_id:
            possession_abbr = opp_abbr

    if game_state == "post":
        down_distance = "Final"
        possession_abbr = None
    elif game_state == "pre":
        down_distance = "Pre-game"
        possession_abbr = None

    points_allowed = max(0, opp_score - excluded_pts)

    stats = DSTStats(
        points_allowed=points_allowed,
        yards_allowed=yards_allowed,
        sacks=sacks,
        interceptions=interceptions,
        fumble_recoveries=fumble_recoveries,
        safeties=safeties,
        blocked_kicks=blocked_kicks,
        dst_tds=dst_tds,
        two_pt_returns=two_pt_returns,
        one_pt_safeties=one_pt_safeties,
        raw_opponent_score=opp_score,
        excluded_points_notes=excluded_notes,
    )

    return GameSnapshot(
        event_id=str(header_comp.get("id", "")),
        defense_team_id=def_id,
        defense_abbr=def_abbr,
        defense_name=def_name,
        opponent_id=opp_id,
        opponent_abbr=opp_abbr,
        opponent_name=opp_name,
        game_state=game_state,
        status_text=status_text,
        quarter=quarter,
        clock=clock,
        down_distance=down_distance,
        possession_abbr=possession_abbr,
        defense_score=def_score,
        opponent_score=opp_score,
        last_play_text=last_play_text,
        stats=stats,
    )


def _effective_play_text(text: str) -> str:
    """If a play was reversed on replay, keep only the official post-REVERSED ruling."""
    if not text:
        return ""
    if "REVERSED." in text:
        return text.rsplit("REVERSED.", 1)[1].strip()
    if "REVERSED" in text:
        return text.rsplit("REVERSED", 1)[1].lstrip(". ").strip()
    return text


def _play_was_nullified(text_l: str) -> bool:
    return (
        "no play" in text_l
        or "nullified by penalty" in text_l
        or "offsetting" in text_l
    )


def _parse_scrimmage_yards_from_text(text: str) -> Optional[int]:
    """
    Extracts net offensive scrimmage yards (including laterals and sack losses)
    from the pre-penalty, pre-turnover segment of ESPN play-by-play text.
    """
    # Strip any trailing penalty clause
    base = re.split(r"\bPENALTY\b|\bPenalty on\b", text, maxsplit=1)[0]
    # Strip anything after FUMBLES or INTERCEPTED (return yardage is not offensive yardage)
    base = re.split(r"\bFUMBLES\b|\bINTERCEPTED\b", base, maxsplit=1)[0]

    # Sack loss pattern: "sacked at SEA 42 for -6 yards" or "sacked ... for a loss of 6 yards"
    if "sacked" in base.lower():
        m_neg = re.search(r"for\s+(-?\d+)\s+yard", base, re.IGNORECASE)
        if m_neg:
            val = int(m_neg.group(1))
            return -abs(val)
        m_loss = re.search(r"loss of\s+(\d+)\s+yard", base, re.IGNORECASE)
        if m_loss:
            return -abs(int(m_loss.group(1)))
        if "no gain" in base.lower():
            return 0
        return 0

    # Sum all "for X yard(s)" / "for no gain" segments (handles laterals cleanly)
    matches = re.findall(r"\bfor\s+(?:(-?\d+)\s+yard|no gain)", base, re.IGNORECASE)
    if not matches:
        return None
    total = 0
    for m in matches:
        total += int(m) if m else 0
    return total


def _extract_scrimmage_yards_from_play(play: dict, drive_team_id: str, opp_id: str) -> int:
    """
    Returns net offensive yards gained by the opponent on a single play.
    Handles post-play penalties, strip-sacks, pre-fumble gains, and laterals.
    """
    if str(drive_team_id) != str(opp_id):
        return 0

    ptype = play.get("type", {}).get("text", "")
    text = _effective_play_text(play.get("text", "") or "")
    text_l = text.lower()

    if ptype in NON_SCRIMMAGE_TYPES:
        return 0
    if _play_was_nullified(text_l):
        return 0
    if "intercepted" in text_l:
        return 0
    if ptype == "Safety" and ("punt" in text_l or "blocked" in text_l):
        return 0

    is_pen = bool(play.get("isPenalty"))

    # If ESPN labeled the play "Penalty" without "No Play" (e.g., dead-ball or declined penalty after a gain)
    if ptype == "Penalty":
        if "pass incomplete" in text_l or text_l.lstrip().startswith("penalty"):
            return 0
        if "declined" in text_l or "enforced between downs" in text_l or "enforced at" in text_l:
            # Check if a real rush/pass/sack occurred before the penalty sentence
            pre_pen = re.split(r"\bPENALTY\b|\bPenalty on\b", text, maxsplit=1)[0].lower()
            if any(k in pre_pen for k in ("pass ", "sacked", "scrambles", "up the middle", "left ", "right ", "guard", "tackle", "end ")):
                parsed = _parse_scrimmage_yards_from_text(text)
                if parsed is not None:
                    return parsed
        return 0

    # Strip-sacks, opponent fumble recoveries, lateral plays, or scrimmage plays with post-play penalties:
    # parse directly from the scrimmage portion of the text so penalty/return yards don't skew statYardage.
    if ptype == "Fumble Recovery (Own)" and not is_pen:
        return _to_int(play.get("statYardage", 0))

    if ptype == "Sack Opp Fumble Recovery":
        parsed = _parse_scrimmage_yards_from_text(text)
        if parsed is not None:
            return parsed

    if ptype in ("Fumble Recovery (Opponent)", "Fumble Return Touchdown"):
        if "sacked" in text_l:
            parsed = _parse_scrimmage_yards_from_text(text)
            if parsed is not None:
                return parsed
        return _to_int(play.get("statYardage", 0))

    if is_pen or "lateral to" in text_l:
        parsed = _parse_scrimmage_yards_from_text(text)
        if parsed is not None:
            return parsed

    if ptype in SCRIMMAGE_YARD_TYPES:
        return _to_int(play.get("statYardage", 0))

    return 0


def _count_fumble_recoveries_by_defense(
    play: dict,
    drive_team_id: str,
    def_id: str,
    opp_id: str,
    def_aliases: set[str],
    opp_aliases: set[str],
) -> int:
    """
    Counts fumbles lost by the opponent (recovered by our D/ST) on any play,
    including strip-sacks, muffed punts/kicks, and interception-fumbles.
    """
    text = _effective_play_text(play.get("text", "") or "")
    text_l = text.lower()
    if "fumble" not in text_l or _play_was_nullified(text_l):
        return 0

    # Match every "RECOVERED by TEAM-" occurrence (case-insensitive)
    recs = [m.upper() for m in re.findall(r"recovered by\s+([A-Z]{2,3})-", text, re.IGNORECASE)]
    if not recs:
        return 0

    # Walk possession through the play to verify it was an opponent fumble recovered by defense
    # Normal case on opponent drive: opponent has ball -> fumbles -> defense recovers
    # Special case: interception on opponent drive flips ball to defense first; if defense fumbles,
    # opponent recovers (not a fumble lost by opponent!).
    # Special case on defense drive: defense punts/kicks -> opponent returns & fumbles -> defense recovers!
    # ESPN attaches Kickoffs to the RECEIVING team's drive, and Punts to the PUNTING team's drive.
    # So possession flips on Punts and INTs, but NOT on Kickoffs.
    has_int = "intercepted" in text_l
    is_punt = play.get("type", {}).get("text", "") in (
        "Punt",
        "Blocked Punt",
        "Punt Return Touchdown",
    )
    poss_flipped = has_int or is_punt

    if str(drive_team_id) == str(opp_id):
        holder_is_opp = not poss_flipped
    elif str(drive_team_id) == str(def_id):
        holder_is_opp = poss_flipped
    else:
        return 0

    count = 0
    for r_team in recs:
        r_is_def = r_team in def_aliases
        if holder_is_opp and r_is_def:
            count += 1
        holder_is_opp = not r_is_def
    return count

    return 0


def build_replay_snapshots(summary: dict, defense_team_id: str) -> list[GameSnapshot]:
    """
    Builds a chronological list of GameSnapshots (one per play, plus Kickoff=0)
    so a completed or in-progress game can be scrubbed play-by-play.
    """
    def_comp, opp_comp, header_comp = _get_teams_from_summary(summary, defense_team_id)
    def_id = str(def_comp["team"]["id"])
    opp_id = str(opp_comp["team"]["id"])
    def_abbr = def_comp["team"]["abbreviation"]
    opp_abbr = opp_comp["team"]["abbreviation"]
    def_name = def_comp["team"].get("displayName", def_abbr)
    opp_name = opp_comp["team"].get("displayName", opp_abbr)
    def_is_home = def_comp.get("homeAway") == "home"
    event_id = str(header_comp.get("id", ""))

    def_aliases = _abbr_aliases(def_abbr)
    opp_aliases = _abbr_aliases(opp_abbr)

    scoring_by_id: dict[str, dict] = {
        str(sp.get("id")): sp for sp in summary.get("scoringPlays", []) if sp.get("id")
    }

    snapshots: list[GameSnapshot] = []
    snapshots.append(
        GameSnapshot(
            event_id=event_id,
            defense_team_id=def_id,
            defense_abbr=def_abbr,
            defense_name=def_name,
            opponent_id=opp_id,
            opponent_abbr=opp_abbr,
            opponent_name=opp_name,
            game_state="in",
            status_text="Q1 15:00",
            quarter=1,
            clock="15:00",
            down_distance="Kickoff",
            possession_abbr=None,
            defense_score=0,
            opponent_score=0,
            last_play_text="Game start (0 PA, 0 Yards Allowed -> 10.0 baseline pts)",
            stats=DSTStats(raw_opponent_score=0),
            play_index=0,
        )
    )

    yards = 0
    sacks = 0.0
    ints = 0
    fumble_recs = 0
    safeties = 0
    blocked_kicks = 0
    dst_tds = 0
    two_pt_returns = 0
    one_pt_safeties = 0
    excluded_pts = 0
    excluded_notes: list[str] = []

    all_plays = _all_drives_plays(summary)
    for idx, (drive, play) in enumerate(all_plays, start=1):
        drive_team_id = str(drive.get("team", {}).get("id", ""))
        ptype = play.get("type", {}).get("text", "")
        raw_text = play.get("text", "") or ""
        text = _effective_play_text(raw_text)
        text_l = text.lower()
        nullified = _play_was_nullified(text_l)

        away_sc = _to_int(play.get("awayScore", 0))
        home_sc = _to_int(play.get("homeScore", 0))
        def_sc = home_sc if def_is_home else away_sc
        opp_sc = away_sc if def_is_home else home_sc

        # Yards allowed
        yards += _extract_scrimmage_yards_from_play(play, drive_team_id, opp_id)

        # Sacks against opponent offense
        if drive_team_id == opp_id and not nullified:
            if ptype in ("Sack", "Sack Opp Fumble Recovery") or "sacked" in text_l:
                # Ignore if sacked text appeared inside a nullified/penalty-only play
                if not (ptype == "Penalty" and "declined" not in text_l and "enforced between" not in text_l):
                    sacks += 1.0

        # Interceptions by defense (even if play type changed due to post-INT fumble)
        if drive_team_id == opp_id and not nullified:
            if "interception" in ptype.lower() or "intercepted" in text_l:
                ints += 1

        # Fumble recoveries by defense (handles strip-sacks, muffed punts/kicks, INT-fumbles)
        fumble_recs += _count_fumble_recoveries_by_defense(
            play, drive_team_id, def_id, opp_id, def_aliases, opp_aliases
        )

        # Blocked kicks
        if _is_blocked_kick_by_defense(drive_team_id, def_id, ptype, text):
            blocked_kicks += 1

        # Scoring play checks
        sp = scoring_by_id.get(str(play.get("id", "")))
        if sp:
            sp_team_id = str(sp.get("team", {}).get("id", ""))
            sp_type = sp.get("type", {}).get("text", "")
            sp_scoring_type = sp.get("scoringType", {}).get("name", "")
            sp_text = sp.get("text", "")

            if sp_team_id == def_id:
                if _is_our_dst_td(sp_type, sp_text):
                    dst_tds += 1
                elif sp_scoring_type == "safety" or "safety" in sp_type.lower():
                    if "1-pt" in sp_text.lower() or "one-point" in sp_text.lower():
                        one_pt_safeties += 1
                    else:
                        safeties += 1
                elif "defensive 2" in sp_type.lower():
                    two_pt_returns += 1
            elif sp_team_id == opp_id:
                ex_pts, note = _classify_opponent_scoring_exclusion(sp_type, sp_text)
                if ex_pts > 0:
                    excluded_pts += ex_pts
                    if note:
                        excluded_notes.append(note)

        quarter = _to_int(play.get("period", {}).get("number", 1))
        clock = play.get("clock", {}).get("displayValue", "0:00")
        end_info = play.get("end", {}) or {}
        down_dist = end_info.get("downDistanceText", "") or end_info.get("shortDownDistanceText", "") or ptype
        poss_id = str(end_info.get("team", {}).get("id") or drive_team_id)
        poss_abbr = def_abbr if poss_id == def_id else (opp_abbr if poss_id == opp_id else None)

        snapshots.append(
            GameSnapshot(
                event_id=event_id,
                defense_team_id=def_id,
                defense_abbr=def_abbr,
                defense_name=def_name,
                opponent_id=opp_id,
                opponent_abbr=opp_abbr,
                opponent_name=opp_name,
                game_state="in",
                status_text=f"Q{quarter} {clock}",
                quarter=quarter,
                clock=clock,
                down_distance=down_dist,
                possession_abbr=poss_abbr,
                defense_score=def_sc,
                opponent_score=opp_sc,
                last_play_text=text,
                stats=DSTStats(
                    points_allowed=max(0, opp_sc - excluded_pts),
                    yards_allowed=yards,
                    sacks=sacks,
                    interceptions=ints,
                    fumble_recoveries=fumble_recs,
                    safeties=safeties,
                    blocked_kicks=blocked_kicks,
                    dst_tds=dst_tds,
                    two_pt_returns=two_pt_returns,
                    one_pt_safeties=one_pt_safeties,
                    raw_opponent_score=opp_sc,
                    excluded_points_notes=list(excluded_notes),
                ),
                play_index=idx,
            )
        )

    return snapshots