from __future__ import annotations

from datetime import datetime
import html
import time
from typing import Optional

import streamlit as st

from dst_engine import (
    DSTStats,
    DSTEvaluation,
    PA_TIERS,
    YA_TIERS,
    evaluate_dst,
)
from espn_feed import (
    GameListing,
    GameSnapshot,
    build_replay_snapshots,
    fetch_game_summary,
    fetch_scoreboard,
    parse_live_game,
)

st.set_page_config(
    page_title="D/ST Live Tracker",
    page_icon="🏈",
    layout="centered",
    initial_sidebar_state="collapsed",
)

TIER_COLORS: dict[int, str] = {
    5: "#059669",
    4: "#10b981",
    3: "#14b8a6",
    2: "#0284c7",
    1: "#38bdf8",
    0: "#475569",
    -1: "#d97706",
    -3: "#ea580c",
    -5: "#dc2626",
    -6: "#b91c1c",
    -7: "#991b1b",
}

# Balanced widths summing to 100% for Points Allowed tiers
PA_SEGMENT_WIDTHS: list[float] = [9.0, 12.5, 13.0, 11.0, 15.0, 13.0, 15.0, 11.5]
PA_AXIS_LABELS: list[str] = ["0", "1–6", "7–13", "14–17", "18–27", "28–34", "35–45", "46+"]

# Proportional widths on a 0–600 yd scale (100-yd bands = 16.6667%, 50-yd bands = 8.3333%)
YA_SCALE_MAX = 600.0
YA_SEGMENT_WIDTHS: list[float] = [
    100 / 6.0,
    100 / 6.0,
    100 / 6.0,
    50 / 6.0,
    50 / 6.0,
    50 / 6.0,
    50 / 6.0,
    50 / 6.0,
    50 / 6.0,
]
YA_BOUNDARY_TICKS: list[tuple[str, float, str]] = [
    ("0", 0.0, "left"),
    ("100", 100 / 6.0, "center"),
    ("200", 200 / 6.0, "center"),
    ("300", 300 / 6.0, "center"),
    ("350", 350 / 6.0, "center"),
    ("400", 400 / 6.0, "center"),
    ("450", 450 / 6.0, "center"),
    ("500", 500 / 6.0, "center"),
    ("550+", 550 / 6.0, "center"),
]


def render_html(markup: str) -> None:
    cleaned = "\n".join(line.lstrip() for line in markup.splitlines() if line.strip())
    st.markdown(cleaned, unsafe_allow_html=True)


def inject_styles() -> None:
    render_html(
        """
        <style>
        .block-container {
            max-width: 740px;
            padding-top: 2.2rem;
            padding-bottom: 2.5rem;
            padding-left: 0.85rem;
            padding-right: 0.85rem;
        }
        header[data-testid="stHeader"] {
            background: transparent;
            pointer-events: none;
        }
        header[data-testid="stHeader"] button,
        header[data-testid="stHeader"] a {
            pointer-events: auto;
        }
        div[data-testid="stButtonGroup"] {
            width: 100%;
        }
        div[data-testid="stButtonGroup"] > div {
            width: 100%;
            display: flex;
            gap: 6px;
        }
        div[data-testid="stButtonGroup"] button {
            flex: 1 1 0;
            min-height: 44px;
            font-size: 0.9rem;
            font-weight: 700;
            cursor: pointer;
            touch-action: manipulation;
        }
        div[data-testid="stRadio"] label {
            padding: 6px 10px;
            cursor: pointer;
            touch-action: manipulation;
        }
        .dst-card {
            background: #111827;
            border: 1px solid #1f2937;
            border-radius: 14px;
            padding: 14px 16px;
            margin-bottom: 12px;
            color: #f9fafb;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        }
        .dst-top-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 12px;
        }
        .dst-title {
            font-size: 1.15rem;
            font-weight: 800;
            letter-spacing: -0.01em;
            color: #f9fafb;
            line-height: 1.2;
        }
        .dst-sub {
            font-size: 0.84rem;
            color: #9ca3af;
            margin-top: 3px;
        }
        .dst-total-box {
            text-align: right;
            background: #0b1220;
            border: 1px solid #263248;
            border-radius: 12px;
            padding: 8px 13px;
            min-width: 108px;
        }
        .dst-total-val {
            font-size: 1.7rem;
            font-weight: 800;
            line-height: 1.05;
            color: #38bdf8;
        }
        .dst-total-lbl {
            font-size: 0.68rem;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            color: #94a3b8;
            margin-top: 2px;
        }
        .dst-status-strip {
            margin-top: 11px;
            padding-top: 10px;
            border-top: 1px solid #1f2937;
            display: flex;
            flex-wrap: wrap;
            justify-content: space-between;
            align-items: center;
            gap: 6px 12px;
            font-size: 0.8rem;
            color: #d1d5db;
        }
        .dst-pill {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 999px;
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.03em;
        }
        .pill-live { background: #7f1d1d; color: #fecaca; border: 1px solid #ef4444; }
        .pill-final { background: #1e293b; color: #cbd5e1; border: 1px solid #475569; }
        .pill-pre { background: #1e3a5f; color: #bae6fd; border: 1px solid #38bdf8; }
        .pill-replay { background: #312e81; color: #c7d2fe; border: 1px solid #6366f1; }
        .pill-sandbox { background: #064e3b; color: #a7f3d0; border: 1px solid #10b981; }
        .dst-section-head {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 8px;
            margin-bottom: 6px;
        }
        .dst-section-label {
            font-size: 0.74rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.07em;
            color: #94a3b8;
        }
        .dst-tier-badge {
            font-size: 0.78rem;
            font-weight: 700;
            color: #e2e8f0;
            background: #1e293b;
            padding: 3px 9px;
            border-radius: 999px;
        }
        .dst-stat-summary {
            display: flex;
            align-items: baseline;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: 4px 12px;
            margin-bottom: 6px;
        }
        .dst-big-num {
            font-size: 1.65rem;
            font-weight: 800;
            color: #ffffff;
            line-height: 1.1;
        }
        .dst-margin-line {
            font-size: 0.82rem;
            color: #cbd5e1;
        }
        .dst-margin-down { color: #fca5a5; font-weight: 700; }
        .dst-margin-up { color: #6ee7b7; font-weight: 700; }
        .dst-excl-note {
            margin-top: 4px;
            margin-bottom: 4px;
            font-size: 0.76rem;
            color: #fcd34d;
        }
        /* Unified Full-Spectrum Tier Axis */
        .axis-scroll {
            overflow-x: auto;
            padding-top: 2px;
            padding-bottom: 2px;
        }
        .axis-inner {
            min-width: 320px;
        }
        .axis-pin-row {
            position: relative;
            height: 26px;
            margin-top: 4px;
        }
        .axis-pin-badge {
            position: absolute;
            top: 0;
            transform: translateX(-50%);
            background: #f8fafc;
            color: #0f172a;
            font-size: 0.74rem;
            font-weight: 800;
            padding: 2px 8px;
            border-radius: 999px;
            white-space: nowrap;
            box-shadow: 0 2px 6px rgba(0, 0, 0, 0.45);
            z-index: 4;
        }
        .axis-pin-caret {
            position: absolute;
            bottom: 0;
            transform: translateX(-50%);
            width: 0;
            height: 0;
            border-left: 5px solid transparent;
            border-right: 5px solid transparent;
            border-top: 6px solid #f8fafc;
            z-index: 4;
        }
        .axis-bar-wrap {
            position: relative;
            width: 100%;
        }
        .axis-bar {
            display: flex;
            width: 100%;
            height: 36px;
            border-radius: 9px;
            overflow: hidden;
            background: #0b1220;
            border: 1px solid #334155;
        }
        .axis-seg {
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 0.78rem;
            font-weight: 800;
            color: #ffffff;
            border-right: 1px solid rgba(15, 23, 42, 0.75);
            opacity: 0.45;
            user-select: none;
            box-sizing: border-box;
        }
        .axis-seg:last-child {
            border-right: none;
        }
        .axis-seg.active {
            opacity: 1.0;
            box-shadow: inset 0 0 0 2px #ffffff;
        }
        .axis-needle {
            position: absolute;
            top: -2px;
            bottom: -4px;
            width: 3px;
            transform: translateX(-50%);
            background: #ffffff;
            border-radius: 2px;
            box-shadow: 0 0 0 1px #0f172a, 0 0 8px rgba(255, 255, 255, 0.8);
            z-index: 5;
            pointer-events: none;
        }
        .axis-ticks-rel {
            position: relative;
            height: 22px;
            margin-top: 3px;
        }
        .axis-tick {
            position: absolute;
            top: 0;
            display: flex;
            flex-direction: column;
            align-items: center;
            font-size: 0.67rem;
            font-weight: 600;
            color: #94a3b8;
            white-space: nowrap;
        }
        .axis-tick.align-center { transform: translateX(-50%); }
        .axis-tick.align-left { transform: translateX(0); align-items: flex-start; }
        .axis-tick-mark {
            width: 1px;
            height: 4px;
            background: #64748b;
            margin-bottom: 2px;
        }
        .axis-labels-flex {
            display: flex;
            width: 100%;
            margin-top: 5px;
        }
        .axis-lbl-cell {
            text-align: center;
            font-size: 0.67rem;
            font-weight: 600;
            color: #94a3b8;
            white-space: nowrap;
            overflow: hidden;
        }
        .axis-lbl-cell.active {
            color: #ffffff;
            font-weight: 800;
        }
        /* Full Plays Grid */
        .plays-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 8px;
            margin-top: 8px;
        }
        @media (max-width: 560px) {
            .plays-grid {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
            .axis-seg {
                font-size: 0.68rem;
            }
            .axis-tick, .axis-lbl-cell {
                font-size: 0.6rem;
            }
        }
        .play-tile {
            background: #0b1220;
            border: 1px solid #1f2937;
            border-radius: 10px;
            padding: 8px 10px;
        }
        .play-tile.has-points {
            background: #0f1c33;
            border-color: #38bdf8;
        }
        .play-tile-top {
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            gap: 4px;
        }
        .play-tile-name {
            font-size: 0.74rem;
            font-weight: 700;
            color: #cbd5e1;
        }
        .play-tile.has-points .play-tile-name {
            color: #f8fafc;
        }
        .play-tile-rate {
            font-size: 0.66rem;
            font-weight: 700;
            color: #64748b;
            white-space: nowrap;
        }
        .play-tile.has-points .play-tile-rate {
            color: #93c5fd;
        }
        .play-tile-bottom {
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            margin-top: 4px;
        }
        .play-tile-count {
            font-size: 1.15rem;
            font-weight: 800;
            color: #475569;
        }
        .play-tile.has-points .play-tile-count {
            color: #ffffff;
        }
        .play-tile-pts {
            font-size: 0.78rem;
            font-weight: 700;
            color: #475569;
        }
        .play-tile.has-points .play-tile-pts {
            color: #38bdf8;
        }
        .dst-play-box {
            margin-top: 9px;
            padding: 8px 10px;
            background: #0b1220;
            border-left: 3px solid #38bdf8;
            border-radius: 6px;
            font-size: 0.8rem;
            color: #cbd5e1;
        }
        </style>
        """
    )


@st.cache_data(ttl=25, show_spinner=False)
def cached_scoreboard(week: Optional[int] = None) -> tuple[list[GameListing], dict]:
    return fetch_scoreboard(week=week)


@st.cache_data(ttl=12, show_spinner=False)
def cached_live_summary(event_id: str) -> tuple[dict, float]:
    return fetch_game_summary(event_id), time.time()


@st.cache_data(ttl=600, show_spinner=False)
def cached_replay_summary(event_id: str) -> dict:
    return fetch_game_summary(event_id)


def _fmt_pts(val: float) -> str:
    return f"{val:g}" if float(val).is_integer() else f"{val:.1f}"


def _fmt_signed(val: float) -> str:
    s = _fmt_pts(val)
    return f"+{s}" if val > 0 else s


def _compute_pa_pin_pct(pa: int) -> tuple[float, int]:
    """Maps Points Allowed onto the 0–100% piecewise-linear PA axis."""
    clamped = max(0, int(pa))
    cum = 0.0
    for idx, (lo, hi, _, _) in enumerate(PA_TIERS):
        w = PA_SEGMENT_WIDTHS[idx]
        lo_ok = True if lo is None else clamped >= lo
        hi_ok = True if hi is None else clamped <= hi
        if lo_ok and hi_ok:
            if lo == hi:
                frac = 0.5
            elif hi is not None and lo is not None:
                frac = (clamped - lo + 0.5) / float(hi - lo + 1)
            else:
                # 46+ tail: map 46..60 across the final segment
                frac = min(0.95, (clamped - 46 + 0.5) / 15.0)
            return cum + w * frac, idx
        cum += w
    return 98.0, len(PA_TIERS) - 1


def _compute_ya_pin_pct(ya: int) -> tuple[float, int]:
    """Maps Net Yards Allowed proportionally onto the 0–600 yd axis."""
    active_idx = len(YA_TIERS) - 1
    for idx, (lo, hi, _, _) in enumerate(YA_TIERS):
        lo_ok = True if lo is None else ya >= lo
        hi_ok = True if hi is None else ya <= hi
        if lo_ok and hi_ok:
            active_idx = idx
            break
    pct = max(0.5, min(99.5, (ya / YA_SCALE_MAX) * 100.0))
    return pct, active_idx


def render_tracker_view(
    snapshot: GameSnapshot,
    ev: DSTEvaluation,
    mode_tag: str,
    updated_ts: Optional[float] = None,
) -> None:
    # 1. Header Card
    if mode_tag == "live":
        if snapshot.game_state == "in":
            badge_cls, badge_txt = "pill-live", "LIVE"
        elif snapshot.game_state == "post":
            badge_cls, badge_txt = "pill-final", "FINAL"
        else:
            badge_cls, badge_txt = "pill-pre", "PRE-GAME"
    elif mode_tag == "replay":
        badge_cls, badge_txt = "pill-replay", "REPLAY"
    else:
        badge_cls, badge_txt = "pill-sandbox", "SANDBOX"

    situation_parts: list[str] = []
    if snapshot.status_text:
        situation_parts.append(snapshot.status_text)
    if snapshot.down_distance and snapshot.down_distance not in (snapshot.status_text,):
        situation_parts.append(snapshot.down_distance)
    if snapshot.possession_abbr:
        if snapshot.possession_abbr == snapshot.opponent_abbr:
            situation_parts.append(f"Ball: {snapshot.opponent_abbr} (D/ST on field)")
        else:
            situation_parts.append(f"Ball: {snapshot.defense_abbr} (D/ST resting)")
    situation_str = " • ".join(situation_parts) if situation_parts else "Ready"

    freshness_str = ""
    if updated_ts is not None:
        age = max(0, int(time.time() - updated_ts))
        local_time = datetime.fromtimestamp(updated_ts).strftime("%I:%M:%S %p").lstrip("0")
        freshness_str = f"Synced {local_time} ({age}s ago)"
    elif mode_tag == "replay" and snapshot.play_index is not None:
        freshness_str = f"Play #{snapshot.play_index}"
    elif mode_tag == "sandbox":
        freshness_str = "Manual simulation"

    score_line = (
        f"{snapshot.defense_abbr} {snapshot.defense_score} – {snapshot.opponent_score} {snapshot.opponent_abbr}"
        if mode_tag != "sandbox"
        else f"Simulated D/ST • {ev.stats.points_allowed} PA • {ev.stats.yards_allowed} Net Yds"
    )
    breakdown_line = f"PA {_fmt_signed(ev.pa_points)} | YA {_fmt_signed(ev.ya_points)} | Plays {_fmt_signed(ev.event_points)}"

    play_html = ""
    if snapshot.last_play_text:
        play_html = f'<div class="dst-play-box"><strong>Last Play:</strong> {html.escape(snapshot.last_play_text)}</div>'

    render_html(
        f"""
        <div class="dst-card">
            <div class="dst-top-row">
                <div>
                    <div class="dst-title">{html.escape(snapshot.defense_abbr)} D/ST vs {html.escape(snapshot.opponent_abbr)}</div>
                    <div class="dst-sub">{html.escape(score_line)}</div>
                    <div class="dst-sub">{html.escape(breakdown_line)}</div>
                </div>
                <div class="dst-total-box">
                    <div class="dst-total-val">{_fmt_pts(ev.total_fantasy_points)}</div>
                    <div class="dst-total-lbl">ESPN D/ST PTS</div>
                </div>
            </div>
            <div class="dst-status-strip">
                <div><span class="dst-pill {badge_cls}">{badge_txt}</span> &nbsp;{html.escape(situation_str)}</div>
                <div style="color:#94a3b8;">{html.escape(freshness_str)}</div>
            </div>
            {play_html}
        </div>
        """
    )

    # 2. Net Yards Allowed — Unified Full-Spectrum Bar & Axis
    ys = ev.yard_status
    ya_pin_pct, ya_active_idx = _compute_ya_pin_pct(ys.current_yards)
    ya_badge_pct = max(7.0, min(93.0, ya_pin_pct))

    ya_margin_bits: list[str] = []
    if ys.yards_to_next_tier is not None:
        ya_margin_bits.append(
            f'<span class="dst-margin-down">{ys.yards_to_next_tier} yds</span> to {ys.next_tier_delta} pt ({ys.next_threshold_yards} yds)'
        )
    else:
        ya_margin_bits.append("Floor tier reached (-7 pts)")
    if ys.yards_to_prev_tier is not None:
        ya_margin_bits.append(
            f'<span class="dst-margin-up">-{ys.yards_to_prev_tier} yds</span> to +{ys.prev_tier_delta} pt (≤{ys.prev_threshold_yards} yds)'
        )
    ya_margin_html = " &nbsp;•&nbsp; ".join(ya_margin_bits)

    ya_segments_html: list[str] = []
    for idx, (_, _, pts, _) in enumerate(YA_TIERS):
        w = YA_SEGMENT_WIDTHS[idx]
        color = TIER_COLORS.get(pts, "#475569")
        cls = "axis-seg active" if idx == ya_active_idx else "axis-seg"
        ya_segments_html.append(
            f'<div class="{cls}" style="width:{w:.4f}%;background:{color};">{_fmt_signed(pts)}</div>'
        )

    ya_ticks_html: list[str] = []
    for lbl, pos_pct, align in YA_BOUNDARY_TICKS:
        align_cls = "align-left" if align == "left" else "align-center"
        ya_ticks_html.append(
            f'<div class="axis-tick {align_cls}" style="left:{pos_pct:.4f}%;"><div class="axis-tick-mark"></div>{lbl}</div>'
        )

    render_html(
        f"""
        <div class="dst-card">
            <div class="dst-section-head">
                <div class="dst-section-label">Net Yards Allowed</div>
                <div class="dst-tier-badge">{html.escape(ys.current_tier_label)} ({_fmt_signed(ys.current_tier_pts)} pts)</div>
            </div>
            <div class="dst-stat-summary">
                <div class="dst-big-num">{ys.current_yards} yds</div>
                <div class="dst-margin-line">{ya_margin_html}</div>
            </div>
            <div class="axis-scroll">
                <div class="axis-inner">
                    <div class="axis-pin-row">
                        <div class="axis-pin-badge" style="left:{ya_badge_pct:.2f}%;">{ys.current_yards} yds</div>
                        <div class="axis-pin-caret" style="left:{ya_pin_pct:.2f}%;"></div>
                    </div>
                    <div class="axis-bar-wrap">
                        <div class="axis-bar">{"".join(ya_segments_html)}</div>
                        <div class="axis-needle" style="left:{ya_pin_pct:.2f}%;"></div>
                    </div>
                    <div class="axis-ticks-rel">{"".join(ya_ticks_html)}</div>
                </div>
            </div>
        </div>
        """
    )

    # 3. Points Allowed — Unified Full-Spectrum Bar & Axis
    ps = ev.points_status
    pa_pin_pct, pa_active_idx = _compute_pa_pin_pct(ps.current_pa)
    pa_badge_pct = max(7.0, min(93.0, pa_pin_pct))

    if ps.pts_to_next_tier is not None:
        pa_margin_html = (
            f'<span class="dst-margin-down">{ps.pts_to_next_tier} more PA</span> '
            f'to {ps.next_tier_delta} pt ({ps.next_threshold_pa} PA)'
        )
    else:
        pa_margin_html = "Floor tier reached (-5 pts)"

    excl_html = ""
    if ev.stats.excluded_points_notes:
        notes_joined = "; ".join(ev.stats.excluded_points_notes)
        excl_html = (
            f'<div class="dst-excl-note">Scoreboard: {ev.stats.raw_opponent_score} pts | '
            f'Counts vs D/ST: {ev.stats.points_allowed} PA ({html.escape(notes_joined)})</div>'
        )

    pa_segments_html: list[str] = []
    pa_labels_html: list[str] = []
    for idx, (_, _, pts, _) in enumerate(PA_TIERS):
        w = PA_SEGMENT_WIDTHS[idx]
        color = TIER_COLORS.get(pts, "#475569")
        seg_cls = "axis-seg active" if idx == pa_active_idx else "axis-seg"
        lbl_cls = "axis-lbl-cell active" if idx == pa_active_idx else "axis-lbl-cell"
        pa_segments_html.append(
            f'<div class="{seg_cls}" style="width:{w:.2f}%;background:{color};">{_fmt_signed(pts)}</div>'
        )
        pa_labels_html.append(
            f'<div class="{lbl_cls}" style="width:{w:.2f}%;">{PA_AXIS_LABELS[idx]}</div>'
        )

    render_html(
        f"""
        <div class="dst-card">
            <div class="dst-section-head">
                <div class="dst-section-label">Points Allowed</div>
                <div class="dst-tier-badge">{html.escape(ps.current_tier_label)} ({_fmt_signed(ps.current_tier_pts)} pts)</div>
            </div>
            <div class="dst-stat-summary">
                <div class="dst-big-num">{ps.current_pa} PA</div>
                <div class="dst-margin-line">{pa_margin_html}</div>
            </div>
            {excl_html}
            <div class="axis-scroll">
                <div class="axis-inner">
                    <div class="axis-pin-row">
                        <div class="axis-pin-badge" style="left:{pa_badge_pct:.2f}%;">{ps.current_pa} PA</div>
                        <div class="axis-pin-caret" style="left:{pa_pin_pct:.2f}%;"></div>
                    </div>
                    <div class="axis-bar-wrap">
                        <div class="axis-bar">{"".join(pa_segments_html)}</div>
                        <div class="axis-needle" style="left:{pa_pin_pct:.2f}%;"></div>
                    </div>
                    <div class="axis-labels-flex">{"".join(pa_labels_html)}</div>
                </div>
            </div>
        </div>
        """
    )

    # 4. Defensive & Special Teams Plays — Always Show All Plays (Including 0)
    tile_parts: list[str] = []
    for item in ev.ledger:
        count = item["count"]
        pts = item["points"]
        weight = item["weight"]
        active_cls = "play-tile has-points" if count > 0 else "play-tile"
        pts_str = f"{_fmt_signed(pts)} pts" if count > 0 else "0 pts"
        tile_parts.append(
            f"""
            <div class="{active_cls}">
                <div class="play-tile-top">
                    <div class="play-tile-name">{html.escape(item["label"])}</div>
                    <div class="play-tile-rate">+{_fmt_pts(weight)}/ea</div>
                </div>
                <div class="play-tile-bottom">
                    <div class="play-tile-count">{_fmt_pts(count)}</div>
                    <div class="play-tile-pts">{pts_str}</div>
                </div>
            </div>
            """
        )

    render_html(
        f"""
        <div class="dst-card">
            <div class="dst-section-head">
                <div class="dst-section-label">Defensive &amp; Special Teams Plays</div>
                <div class="dst-tier-badge">Plays Total: {_fmt_signed(ev.event_points)} pts</div>
            </div>
            <div class="plays-grid">{"".join(tile_parts)}</div>
        </div>
        """
    )


def _send_to_sandbox(stats: DSTStats, label: str) -> None:
    st.session_state["sb_pa"] = int(stats.points_allowed)
    st.session_state["sb_ya"] = int(stats.yards_allowed)
    st.session_state["sb_sacks"] = int(stats.sacks)
    st.session_state["sb_ints"] = int(stats.interceptions)
    st.session_state["sb_fr"] = int(stats.fumble_recoveries)
    st.session_state["sb_sf"] = int(stats.safeties)
    st.session_state["sb_blk"] = int(stats.blocked_kicks)
    st.session_state["sb_tds"] = int(stats.dst_tds)
    st.session_state["sb_label"] = label
    st.session_state["pending_mode"] = "Sandbox"


def _init_sandbox_state() -> None:
    defaults = {
        "sb_pa": 14,
        "sb_ya": 284,
        "sb_sacks": 2,
        "sb_ints": 1,
        "sb_fr": 0,
        "sb_sf": 0,
        "sb_blk": 0,
        "sb_tds": 0,
        "sb_label": "Custom D/ST",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def render_live_mode() -> None:
    try:
        games, meta = cached_scoreboard()
    except Exception as exc:
        st.error(f"Could not reach ESPN scoreboard: {exc}")
        return

    if not games:
        st.info("No NFL games found on the current scoreboard.")
        return

    order = {"in": 0, "pre": 1, "post": 2}
    games_sorted = sorted(games, key=lambda g: (order.get(g.state, 9), g.short_name))

    def _game_label(g: GameListing) -> str:
        tag = "LIVE" if g.state == "in" else ("FINAL" if g.state == "post" else "PRE")
        if g.state == "pre":
            return f"[{tag}] {g.short_name} — {g.status_detail}"
        return f"[{tag}] {g.away_abbr} {g.away_score} @ {g.home_abbr} {g.home_score} ({g.status_detail})"

    c1, c2 = st.columns([2.2, 1.0])
    with c1:
        selected_game = st.selectbox(
            f"Week {meta.get('week', '')} Game",
            games_sorted,
            format_func=_game_label,
            key="live_game_select",
        )
    with c2:
        team_choices = [
            (selected_game.away_id, f"{selected_game.away_abbr} D/ST"),
            (selected_game.home_id, f"{selected_game.home_abbr} D/ST"),
        ]
        chosen_team = st.radio(
            "Defense",
            team_choices,
            format_func=lambda x: x[1],
            horizontal=True,
            key="live_team_select",
        )

    c_ref1, c_ref2, c_ref3 = st.columns([1.2, 1.0, 1.3])
    with c_ref1:
        auto_refresh = st.toggle(
            "Auto-refresh (15s)",
            value=(selected_game.state == "in"),
            key="live_auto_refresh",
        )
    with c_ref2:
        if st.button("Refresh Now", use_container_width=True):
            cached_live_summary.clear()
            cached_scoreboard.clear()
            st.rerun()

    def _render_live_body() -> Optional[GameSnapshot]:
        try:
            summary, fetched_ts = cached_live_summary(selected_game.event_id)
            snap = parse_live_game(summary, chosen_team[0])
            ev = evaluate_dst(snap.stats)
            render_tracker_view(snap, ev, mode_tag="live", updated_ts=fetched_ts)
            return snap
        except Exception as exc:
            st.error(f"Error loading game data: {exc}")
            return None

    if hasattr(st, "fragment") and auto_refresh:
        @st.fragment(run_every=15)
        def _live_poller() -> None:
            _render_live_body()

        _live_poller()
        snap_for_sb = None
        try:
            summary_sb, _ = cached_live_summary(selected_game.event_id)
            snap_for_sb = parse_live_game(summary_sb, chosen_team[0])
        except Exception:
            pass
    else:
        snap_for_sb = _render_live_body()

    with c_ref3:
        if snap_for_sb and st.button("Test in Sandbox", use_container_width=True):
            _send_to_sandbox(
                snap_for_sb.stats,
                f"{snap_for_sb.defense_abbr} vs {snap_for_sb.opponent_abbr}",
            )
            st.rerun()


def render_replay_mode() -> None:
    try:
        _, curr_meta = cached_scoreboard()
        default_week = int(curr_meta.get("week") or 10)
    except Exception:
        default_week = 10

    c1, c2 = st.columns([0.9, 2.3])
    with c1:
        week = st.number_input(
            "NFL Week",
            min_value=1,
            max_value=18,
            value=default_week,
            step=1,
            key="replay_week",
        )

    try:
        games, _ = cached_scoreboard(week=int(week))
    except Exception as exc:
        st.error(f"Could not fetch Week {week} games: {exc}")
        return

    playable = [g for g in games if g.state in ("post", "in")]
    if not playable:
        st.info(
            f"No started or completed games yet in Week {week}. "
            f"Try an earlier week (e.g., Week {max(1, int(week) - 1)})."
        )
        return

    with c2:
        selected_game = st.selectbox(
            "Completed / Active Game to Replay",
            playable,
            format_func=lambda g: f"{g.away_abbr} {g.away_score} @ {g.home_abbr} {g.home_score} ({g.status_detail})",
            key="replay_game_select",
        )

    team_choices = [
        (selected_game.away_id, f"{selected_game.away_abbr} D/ST"),
        (selected_game.home_id, f"{selected_game.home_abbr} D/ST"),
    ]
    chosen_team = st.radio(
        "Defense to Track",
        team_choices,
        format_func=lambda x: x[1],
        horizontal=True,
        key="replay_team_select",
    )

    try:
        summary = cached_replay_summary(selected_game.event_id)
        snapshots = build_replay_snapshots(summary, chosen_team[0])
    except Exception as exc:
        st.error(f"Could not build play-by-play replay: {exc}")
        return

    max_idx = len(snapshots) - 1
    slider_key = f"replay_idx_{selected_game.event_id}_{chosen_team[0]}"
    if slider_key not in st.session_state:
        st.session_state[slider_key] = max_idx
    else:
        st.session_state[slider_key] = max(0, min(max_idx, st.session_state[slider_key]))

    def _set_idx(new_val: int) -> None:
        st.session_state[slider_key] = max(0, min(max_idx, new_val))

    curr_idx = st.session_state[slider_key]
    b1, b2, b3, b4, b5, b6 = st.columns(6)
    with b1:
        st.button("Start", on_click=_set_idx, args=(0,), use_container_width=True)
    with b2:
        st.button("-10", on_click=_set_idx, args=(curr_idx - 10,), use_container_width=True)
    with b3:
        st.button("-1", on_click=_set_idx, args=(curr_idx - 1,), use_container_width=True)
    with b4:
        st.button("+1", on_click=_set_idx, args=(curr_idx + 1,), use_container_width=True)
    with b5:
        st.button("+10", on_click=_set_idx, args=(curr_idx + 10,), use_container_width=True)
    with b6:
        st.button("Final", on_click=_set_idx, args=(max_idx,), use_container_width=True)

    if max_idx > 0:
        idx = st.slider(
            f"Play Scrubber (0 = Kickoff, {max_idx} = Final)",
            min_value=0,
            max_value=max_idx,
            key=slider_key,
        )
    else:
        idx = 0

    snap = snapshots[idx]
    ev = evaluate_dst(snap.stats)
    render_tracker_view(snap, ev, mode_tag="replay")

    if st.button("Send This Snap to Sandbox", use_container_width=True):
        _send_to_sandbox(
            snap.stats,
            f"{snap.defense_abbr} vs {snap.opponent_abbr} ({snap.status_text})",
        )
        st.rerun()


def render_sandbox_mode() -> None:
    _init_sandbox_state()

    st.caption("Simulate the next play or dial in any exact game state.")

    q1, q2, q3, q4 = st.columns(4)
    with q1:
        if st.button("+10 Yds", use_container_width=True):
            st.session_state["sb_ya"] += 10
            st.rerun()
    with q2:
        if st.button("+25 Yds", use_container_width=True):
            st.session_state["sb_ya"] += 25
            st.rerun()
    with q3:
        if st.button("Sack (-7 Yds)", use_container_width=True):
            st.session_state["sb_sacks"] += 1
            st.session_state["sb_ya"] -= 7
            st.rerun()
    with q4:
        if st.button("INT (+2)", use_container_width=True):
            st.session_state["sb_ints"] += 1
            st.rerun()

    q5, q6, q7, q8 = st.columns(4)
    with q5:
        if st.button("Allow FG (+3)", use_container_width=True):
            st.session_state["sb_pa"] += 3
            st.rerun()
    with q6:
        if st.button("Allow TD+XP (+7)", use_container_width=True):
            st.session_state["sb_pa"] += 7
            st.rerun()
    with q7:
        if st.button("D/ST TD (+6)", use_container_width=True):
            st.session_state["sb_tds"] += 1
            st.rerun()
    with q8:
        if st.button("Kickoff Reset", use_container_width=True):
            st.session_state["sb_pa"] = 0
            st.session_state["sb_ya"] = 0
            st.session_state["sb_sacks"] = 0
            st.session_state["sb_ints"] = 0
            st.session_state["sb_fr"] = 0
            st.session_state["sb_sf"] = 0
            st.session_state["sb_blk"] = 0
            st.session_state["sb_tds"] = 0
            st.session_state["sb_label"] = "Kickoff Baseline"
            st.rerun()

    stats = DSTStats(
        points_allowed=int(st.session_state["sb_pa"]),
        yards_allowed=int(st.session_state["sb_ya"]),
        sacks=float(st.session_state["sb_sacks"]),
        interceptions=int(st.session_state["sb_ints"]),
        fumble_recoveries=int(st.session_state["sb_fr"]),
        safeties=int(st.session_state["sb_sf"]),
        blocked_kicks=int(st.session_state["sb_blk"]),
        dst_tds=int(st.session_state["sb_tds"]),
        raw_opponent_score=int(st.session_state["sb_pa"]),
    )
    ev = evaluate_dst(stats)
    snap = GameSnapshot(
        event_id="sandbox",
        defense_team_id="sb",
        defense_abbr=st.session_state.get("sb_label", "Custom"),
        defense_name="Sandbox D/ST",
        opponent_id="opp",
        opponent_abbr="OPP",
        opponent_name="Opponent",
        game_state="in",
        status_text="What-If Sandbox",
        quarter=4,
        clock="--:--",
        down_distance="",
        possession_abbr=None,
        defense_score=0,
        opponent_score=stats.points_allowed,
        last_play_text="",
        stats=stats,
    )
    render_tracker_view(snap, ev, mode_tag="sandbox")

    with st.expander("Fine-tune exact stats"):
        c1, c2 = st.columns(2)
        with c1:
            st.number_input("Points Allowed (PA)", min_value=0, max_value=99, key="sb_pa")
            st.number_input("Sacks (+1)", min_value=0, max_value=20, key="sb_sacks")
            st.number_input("Fumble Recoveries (+2)", min_value=0, max_value=15, key="sb_fr")
            st.number_input("Blocked Kicks (+2)", min_value=0, max_value=10, key="sb_blk")
        with c2:
            st.number_input("Net Yards Allowed", min_value=-50, max_value=900, key="sb_ya")
            st.number_input("Interceptions (+2)", min_value=0, max_value=15, key="sb_ints")
            st.number_input("Safeties (+2)", min_value=0, max_value=5, key="sb_sf")
            st.number_input("D/ST TDs (+6)", min_value=0, max_value=10, key="sb_tds")


def render_scoring_reference() -> None:
    with st.expander("ESPN D/ST Scoring Rules & Edge Cases"):
        st.caption(
            "Opponent pick-sixes, offensive fumble-return TDs, and offensive safeties do not count against "
            "D/ST Points Allowed (PATs and special teams return TDs still count). "
            "Net yards allowed subtracts sack yardage from passing + rushing yards."
        )


def main() -> None:
    inject_styles()

    modes = ["Live Game", "Game Replay", "Sandbox"]
    if "last_valid_mode" not in st.session_state:
        st.session_state["last_valid_mode"] = "Live Game"

    if "pending_mode" in st.session_state:
        target = st.session_state.pop("pending_mode")
        st.session_state["active_mode"] = target
        st.session_state["last_valid_mode"] = target
    elif st.session_state.get("active_mode") not in modes:
        st.session_state["active_mode"] = st.session_state["last_valid_mode"]

    if hasattr(st, "segmented_control"):
        mode = st.segmented_control(
            "Mode",
            modes,
            selection_mode="single",
            label_visibility="collapsed",
            key="active_mode",
        )
        if mode is None:
            st.session_state["pending_mode"] = st.session_state["last_valid_mode"]
            st.rerun()
    else:
        mode = st.radio(
            "Mode",
            modes,
            horizontal=True,
            label_visibility="collapsed",
            key="active_mode",
        )

    st.session_state["last_valid_mode"] = mode

    if mode == "Live Game":
        render_live_mode()
    elif mode == "Game Replay":
        render_replay_mode()
    else:
        render_sandbox_mode()

    render_scoring_reference()


if __name__ == "__main__":
    main()