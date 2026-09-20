from __future__ import annotations

from app.config import Settings
from app.integrations.monday.base import CrmClient
from app.integrations.monday.client import MondayCrmClient
from app.integrations.monday.stub import StubCrmClient


def build_crm_client(settings: Settings) -> CrmClient:
    """The stub by default; the real Monday board when CRM_BACKEND=monday."""
    if settings.crm_backend == "monday":
        print(f"[crm] using the real Monday.com board {settings.monday_board_id}")
        return MondayCrmClient(settings.monday_api_token, settings.monday_board_id, settings.monday_api_version)
    if settings.crm_backend != "stub":
        raise ValueError(f"CRM_BACKEND must be 'stub' or 'monday', got {settings.crm_backend!r}")
    return StubCrmClient(settings.crm_store_path)
