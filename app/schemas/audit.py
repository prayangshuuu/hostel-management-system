"""Audit log response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

__all__ = [
    "AuditLogRead",
]


class AuditLogRead(BaseModel):
    """Representation of an immutable audit trail entry."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    actor_id: UUID | None = None
    action: str
    entity: str
    entity_id: UUID
    payload: dict[str, Any]
    created_at: datetime
    actor_name: str | None = None
    actor_email: str | None = None

    @model_validator(mode="before")
    @classmethod
    def populate_enriched_fields(cls, data: Any) -> Any:
        """Extract enriched contextual details from actor relationship if present."""
        if isinstance(data, dict):
            return data

        actor = getattr(data, "actor", None)

        return {
            "id": getattr(data, "id", None),
            "actor_id": getattr(data, "actor_id", None),
            "action": getattr(data, "action", None),
            "entity": getattr(data, "entity", None),
            "entity_id": getattr(data, "entity_id", None),
            "payload": getattr(data, "payload", {}) or {},
            "created_at": getattr(data, "created_at", None),
            "actor_name": getattr(actor, "full_name", getattr(data, "actor_name", None)),
            "actor_email": getattr(actor, "email", getattr(data, "actor_email", None)),
        }
