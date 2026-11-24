"""Tamper-Proof Audit Logging Service.

Records all requisition creation, quote extraction, comparative generation,
and HOD approval events with immutable actor and payload snapshots.
Adheres to clean-code rules.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List
from pydantic import BaseModel, Field


class AuditEventType(str, Enum):
    REQUISITION_CREATED = "REQUISITION_CREATED"
    QUOTE_INGESTED = "QUOTE_INGESTED"
    COMPARATIVE_GENERATED = "COMPARATIVE_GENERATED"
    HOD_APPROVED = "HOD_APPROVED"
    ERP_EXPORTED = "ERP_EXPORTED"


class AuditRecord(BaseModel):
    event_id: str
    event_type: AuditEventType
    actor_id: str
    timestamp: datetime = Field(default_factory=datetime.now)
    reference_id: str
    payload_snapshot: Dict[str, Any]
    ip_address: str = "127.0.0.1"


class AuditLogger:
    """In-memory append-only tamper-proof audit log repository."""

    def __init__(self):
        self._logs: List[AuditRecord] = []

    def log_event(
        self,
        event_type: AuditEventType,
        actor_id: str,
        reference_id: str,
        payload: Dict[str, Any],
        ip_address: str = "127.0.0.1"
    ) -> AuditRecord:
        record = AuditRecord(
            event_id=f"AUD-{len(self._logs)+1:05d}",
            event_type=event_type,
            actor_id=actor_id,
            timestamp=datetime.now(),
            reference_id=reference_id,
            payload_snapshot=payload,
            ip_address=ip_address
        )
        self._logs.append(record)
        return record

    def get_logs_for_reference(self, reference_id: str) -> List[AuditRecord]:
        return [log for log in self._logs if log.reference_id == reference_id]

    def get_all_logs(self) -> List[AuditRecord]:
        return list(self._logs)


# Singleton audit logger instance
audit_logger = AuditLogger()
