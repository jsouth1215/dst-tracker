# D/ST Live Tracker

Real-time ESPN standard Fantasy Football D/ST tracker with unified Yards Allowed and Points Allowed tier axes, live play-by-play status, historical game replay, and a next-play sandbox.

## Run Locally

    pip install -r requirements.txt
    python -m streamlit run app.py

## Features
- **Live Game:** Polls ESPN's public scoreboard & game summary feeds every 15 seconds with live clock, down/distance, possession, and sync timestamp.
- **Unified Tier Axes:** Full-spectrum visual bars for both Net Yards Allowed and Points Allowed showing every scoring bracket and exact current position.
- **Edge-Case Handling:** Uses official net yards (sack yardage subtracted) and excludes opponent pick-sixes, offensive fumble-return TDs, and offensive safeties from Points Allowed (while still counting PATs and special teams return TDs).
- **Game Replay & Sandbox:** Scrub any completed NFL game play-by-play or simulate next-play outcomes.