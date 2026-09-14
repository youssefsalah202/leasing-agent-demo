"""Run automated follow-up: send a nudge to every eligible lead who hasn't
been contacted in a while.

Usage:
    python scripts/run_follow_up.py
    python scripts/run_follow_up.py --after-hours 1   # override the threshold
"""

from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.batch.follow_up import run
from app.config import get_settings
from app.integrations.monday.stub import StubCrmClient
from app.integrations.quo.stub import StubQuoClient
from app.logging_.conversation_log import ConversationLogStore


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--after-hours",
        type=float,
        default=None,
        help="Follow up on leads not contacted in this many hours, overriding FOLLOW_UP_AFTER_HOURS",
    )
    args = parser.parse_args()

    settings = get_settings()
    crm = StubCrmClient(settings.crm_store_path)
    quo = StubQuoClient(settings.stub_calls_path)
    log_store = ConversationLogStore(settings.conversations_dir)

    after = timedelta(hours=args.after_hours) if args.after_hours is not None else None
    sent = run(settings, crm, quo, log_store, after=after)
    print(f"[run_follow_up] sent {len(sent)} follow-up message(s)")


if __name__ == "__main__":
    main()
