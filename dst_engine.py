from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# Standard ESPN D/ST Scoring Tiers
# (min_val, max_val, fantasy_pts, label)  -- None means unbounded
PA_TIERS: list[tuple[Optional[int], Optional[int], int, str]] = [
    (0, 0, 5, "0 PA"),
    (1, 6, 4, "1-6 PA"),
    (7, 13, 3, "7-13 PA"),
    (14, 17, 1, "14-17 PA"),
    (18, 27, 0, "18-27 PA"),
    (28, 34, -1, "28-34 PA"),
    (35, 45, -3, "35-45 PA"),
    (46, None, -5, "46+ PA"),
]

YA_TIERS: list[tuple[Optional[int], Optional[int], int, str]] = [
    (None, 99, 5, "<100 Yds"),
    (100, 199, 3, "100-199 Yds"),
    (200, 299, 2, "200-299 Yds"),
    (300, 349, 0, "300-349 Yds"),
    (350, 399, -1, "350-399 Yds"),
    (400, 449, -3, "400-449 Yds"),
    (450, 499, -5, "450-499 Yds"),
    (500, 549, -6, "500-549 Yds"),
    (550, None, -7, "550+ Yds"),
]

EVENT_WEIGHTS: dict[str, tuple[float, str]] = {
    "sacks": (1.0, "Sacks"),
    "interceptions": (2.0, "Interceptions"),
    "fumble_recoveries": (2.0, "Fumble Rec"),
    "blocked_kicks": (2.0, "Blocked Kicks"),
    "safeties": (2.0, "Safeties"),
    "dst_tds": (6.0, "D/ST TDs"),
    "two_pt_returns": (2.0, "2-Pt Returns"),
    "one_pt_safeties": (1.0, "1-Pt Safety"),
}


@dataclass
class DSTStats:
    points_allowed: int = 0
    yards_allowed: int = 0
    sacks: float = 0.0
    interceptions: int = 0
    fumble_recoveries: int = 0
    safeties: int = 0
    blocked_kicks: int = 0
    dst_tds: int = 0
    two_pt_returns: int = 0
    one_pt_safeties: int = 0
    raw_opponent_score: Optional[int] = None
    excluded_points_notes: list[str] = field(default_factory=list)


@dataclass
class YardTierStatus:
    current_yards: int
    current_tier_label: str
    current_tier_pts: int
    tier_min: int
    tier_max: Optional[int]
    next_threshold_yards: Optional[int]
    yards_to_next_tier: Optional[int]
    next_tier_pts: Optional[int]
    next_tier_delta: int
    prev_threshold_yards: Optional[int]
    yards_to_prev_tier: Optional[int]
    prev_tier_pts: Optional[int]
    prev_tier_delta: int


@dataclass
class PointsTierStatus:
    current_pa: int
    current_tier_label: str
    current_tier_pts: int
    next_threshold_pa: Optional[int]
    pts_to_next_tier: Optional[int]
    next_tier_pts: Optional[int]
    next_tier_delta: int


@dataclass
class DSTEvaluation:
    stats: DSTStats
    total_fantasy_points: float
    pa_points: int
    ya_points: int
    event_points: float
    yard_status: YardTierStatus
    points_status: PointsTierStatus
    ledger: list[dict]


def _find_tier(value: int, tiers: list[tuple[Optional[int], Optional[int], int, str]]) -> int:
    for idx, (lo, hi, _, _) in enumerate(tiers):
        lo_ok = True if lo is None else value >= lo
        hi_ok = True if hi is None else value <= hi
        if lo_ok and hi_ok:
            return idx
    return len(tiers) - 1


def score_points_allowed(pa: int) -> tuple[int, str, int]:
    clamped = max(0, int(pa))
    idx = _find_tier(clamped, PA_TIERS)
    _, _, pts, label = PA_TIERS[idx]
    return pts, label, idx


def score_yards_allowed(ya: int) -> tuple[int, str, int]:
    idx = _find_tier(int(ya), YA_TIERS)
    _, _, pts, label = YA_TIERS[idx]
    return pts, label, idx


def evaluate_dst(stats: DSTStats) -> DSTEvaluation:
    pa = max(0, int(stats.points_allowed))
    ya = int(stats.yards_allowed)

    pa_pts, pa_label, pa_idx = score_points_allowed(pa)
    ya_pts, ya_label, ya_idx = score_yards_allowed(ya)

    event_points = 0.0
    ledger: list[dict] = []
    for attr, (weight, label) in EVENT_WEIGHTS.items():
        val = getattr(stats, attr)
        pts = round(val * weight, 2)
        event_points += pts
        ledger.append(
            {
                "key": attr,
                "label": label,
                "weight": weight,
                "count": val,
                "points": pts,
            }
        )

    total = round(pa_pts + ya_pts + event_points, 2)

    lo, hi, _, _ = YA_TIERS[ya_idx]
    tier_min = 0 if lo is None else lo

    if ya_idx + 1 < len(YA_TIERS):
        next_lo, _, next_pts, _ = YA_TIERS[ya_idx + 1]
        assert next_lo is not None
        yards_to_next = next_lo - ya
        next_delta = next_pts - ya_pts
    else:
        next_lo = None
        next_pts = None
        yards_to_next = None
        next_delta = 0

    if ya_idx > 0:
        _, prev_hi, prev_pts, _ = YA_TIERS[ya_idx - 1]
        assert prev_hi is not None
        yards_to_prev = ya - prev_hi
        prev_delta = prev_pts - ya_pts
    else:
        prev_hi = None
        prev_pts = None
        yards_to_prev = None
        prev_delta = 0

    yard_status = YardTierStatus(
        current_yards=ya,
        current_tier_label=ya_label,
        current_tier_pts=ya_pts,
        tier_min=tier_min,
        tier_max=hi,
        next_threshold_yards=next_lo,
        yards_to_next_tier=yards_to_next,
        next_tier_pts=next_pts,
        next_tier_delta=next_delta,
        prev_threshold_yards=prev_hi,
        yards_to_prev_tier=yards_to_prev,
        prev_tier_pts=prev_pts,
        prev_tier_delta=prev_delta,
    )

    if pa_idx + 1 < len(PA_TIERS):
        next_pa_lo, _, next_pa_pts, _ = PA_TIERS[pa_idx + 1]
        assert next_pa_lo is not None
        pts_to_next_pa = next_pa_lo - pa
        next_pa_delta = next_pa_pts - pa_pts
    else:
        next_pa_lo = None
        next_pa_pts = None
        pts_to_next_pa = None
        next_pa_delta = 0

    points_status = PointsTierStatus(
        current_pa=pa,
        current_tier_label=pa_label,
        current_tier_pts=pa_pts,
        next_threshold_pa=next_pa_lo,
        pts_to_next_tier=pts_to_next_pa,
        next_tier_pts=next_pa_pts,
        next_tier_delta=next_pa_delta,
    )

    return DSTEvaluation(
        stats=stats,
        total_fantasy_points=total,
        pa_points=pa_pts,
        ya_points=ya_pts,
        event_points=round(event_points, 2),
        yard_status=yard_status,
        points_status=points_status,
        ledger=ledger,
    )