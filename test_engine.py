import unittest

from dst_engine import (
    DSTStats,
    EVENT_WEIGHTS,
    evaluate_dst,
    score_points_allowed,
    score_yards_allowed,
)
from espn_feed import build_replay_snapshots, fetch_game_summary, parse_live_game


class TestDSTEngine(unittest.TestCase):
    def test_kickoff_baseline_is_10_points(self):
        ev = evaluate_dst(DSTStats(points_allowed=0, yards_allowed=0))
        self.assertEqual(ev.total_fantasy_points, 10.0)
        self.assertEqual(ev.pa_points, 5)
        self.assertEqual(ev.ya_points, 5)
        self.assertEqual(ev.yard_status.yards_to_next_tier, 100)
        self.assertEqual(ev.yard_status.next_tier_delta, -2)
        self.assertEqual(len(ev.ledger), len(EVENT_WEIGHTS))

    def test_points_allowed_boundaries(self):
        cases = [
            (0, 5), (1, 4), (6, 4), (7, 3), (13, 3),
            (14, 1), (17, 1), (18, 0), (27, 0),
            (28, -1), (34, -1), (35, -3), (45, -3), (46, -5), (70, -5),
        ]
        for pa, expected in cases:
            pts, _, _ = score_points_allowed(pa)
            self.assertEqual(pts, expected, f"PA={pa}")

    def test_yards_allowed_boundaries(self):
        cases = [
            (-5, 5), (0, 5), (99, 5), (100, 3), (199, 3),
            (200, 2), (299, 2), (300, 0), (349, 0),
            (350, -1), (399, -1), (400, -3), (449, -3),
            (450, -5), (499, -5), (500, -6), (549, -6),
            (550, -7), (650, -7),
        ]
        for ya, expected in cases:
            pts, _, _ = score_yards_allowed(ya)
            self.assertEqual(pts, expected, f"YA={ya}")

    def test_tier_margins_both_directions(self):
        ev = evaluate_dst(DSTStats(points_allowed=14, yards_allowed=284, sacks=2, interceptions=1))
        self.assertEqual(ev.total_fantasy_points, 7.0)
        self.assertEqual(ev.yard_status.next_threshold_yards, 300)
        self.assertEqual(ev.yard_status.yards_to_next_tier, 16)
        self.assertEqual(ev.yard_status.next_tier_delta, -2)
        self.assertEqual(ev.yard_status.prev_threshold_yards, 199)
        self.assertEqual(ev.yard_status.yards_to_prev_tier, 85)
        self.assertEqual(ev.points_status.next_threshold_pa, 18)
        self.assertEqual(ev.points_status.pts_to_next_tier, 4)

    def test_sack_recovery_at_boundary(self):
        ev = evaluate_dst(DSTStats(points_allowed=10, yards_allowed=300))
        self.assertEqual(ev.ya_points, 0)
        self.assertEqual(ev.yard_status.yards_to_prev_tier, 1)
        self.assertEqual(ev.yard_status.prev_tier_delta, 2)


def verify_live_game(event_id: str = "401873066"):
    print(f"\n=== LIVE RECONCILIATION CHECK: GAME {event_id} ===")
    summary = fetch_game_summary(event_id)
    competitors = summary["header"]["competitions"][0]["competitors"]
    for comp in competitors:
        tid = str(comp["team"]["id"])
        abbr = comp["team"]["abbreviation"]
        live = parse_live_game(summary, tid)
        live_ev = evaluate_dst(live.stats)
        replay = build_replay_snapshots(summary, tid)
        final_replay = replay[-1]
        rep_ev = evaluate_dst(final_replay.stats)
        print(
            f"  [{abbr} vs {live.opponent_abbr}] "
            f"BOX={live_ev.total_fantasy_points} pts (PA={live.stats.points_allowed}, YA={live.stats.yards_allowed}) | "
            f"REPLAY={rep_ev.total_fantasy_points} pts (PA={final_replay.stats.points_allowed}, YA={final_replay.stats.yards_allowed})"
        )


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestDSTEngine)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    verify_live_game("401873066")
    raise SystemExit(0 if result.wasSuccessful() else 1)