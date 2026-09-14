"""Run nightly triage: classify every lead with new SMS/call activity since
the last run, and write the classification to the CRM.

Usage:
    python scripts/run_nightly_triage.py
    python scripts/run_nightly_triage.py --since-hours 24   # override the cursor
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Allow running as `python scripts/run_nightly_triage.py` (not just `-m`) by
# putting the project root on sys.path before importing `app`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.batch.state import BatchStateStore
from app.batch.triage import run
from app.config import get_settings
from app.integrations.monday.stub import StubCrmClient
from app.integrations.quo.stub import StubQuoClient
from app.logging_.conversation_log import ConversationLogStore
from app.logging_.triage_store import TriageStore

JOB_NAME = "triage"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--since-hours",
        type=float,
        default=None,
        help="Process activity from this many hours ago, ignoring the saved cursor",
    )
    args = parser.parse_args()

    settings = get_settings()
    state = BatchStateStore(settings.batch_state_path)
    crm = StubCrmClient(settings.crm_store_path)
    quo = StubQuoClient(settings.stub_calls_path)
    log_store = ConversationLogStore(settings.conversations_dir)
    triage_store = TriageStore(settings.triage_store_dir)

    now = datetime.now(timezone.utc)
    if args.since_hours is not None:
        since = now - timedelta(hours=args.since_hours)
    else:
        since = state.get_last_run(JOB_NAME) or (now - timedelta(hours=24))

    print(f"[run_nightly_triage] processing activity since {since.isoformat()}")
    records = run(settings, crm, quo, log_store, triage_store, since)
    print(f"[run_nightly_triage] triaged {len(records)} lead(s)")

    state.set_last_run(JOB_NAME, now)


if __name__ == "__main__":
    main()
