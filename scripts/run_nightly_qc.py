"""Run nightly QC: review every triage record not yet checked, against the
raw conversation, and correct or flag anything triage got wrong.

Usage:
    python scripts/run_nightly_qc.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.batch.qc import run
from app.config import get_settings
from app.integrations.monday.stub import StubCrmClient
from app.logging_.conversation_log import ConversationLogStore
from app.logging_.triage_store import TriageStore


def main() -> None:
    settings = get_settings()
    crm = StubCrmClient(settings.crm_store_path)
    log_store = ConversationLogStore(settings.conversations_dir)
    triage_store = TriageStore(settings.triage_store_dir)

    results = run(settings, crm, log_store, triage_store)
    print(f"[run_nightly_qc] reviewed {len(results)} triage record(s)")


if __name__ == "__main__":
    main()
