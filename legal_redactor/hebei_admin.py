"""Hebei-specific administrative division detector."""

from __future__ import annotations

from .admin_division import ADDRESS_CONTEXT_MARKERS, AdminDivisionDetector


class HebeiAdminDivisionDetector(AdminDivisionDetector):
    def __init__(self, db_path: str | object = "data/hebei_admin_divisions.sqlite") -> None:
        super().__init__(
            db_path,
            source="hebei_admin_db",
            region_label="河北省行政区划/基层组织",
        )


__all__ = ["ADDRESS_CONTEXT_MARKERS", "AdminDivisionDetector", "HebeiAdminDivisionDetector"]