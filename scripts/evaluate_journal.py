"""Roz ek baar chalayein (Task Scheduler): purane signals ka asal natija nikalta hai."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from psx import journal  # noqa: E402

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print("Resolved signals:", journal.evaluate_open())
    print("Live stats:", journal.live_stats())
    print("Live stats (confidence >= 60):", journal.live_stats(60))
