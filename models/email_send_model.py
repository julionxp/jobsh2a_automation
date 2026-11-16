from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.database import DBBaseModel


class EmailSendModel(DBBaseModel):
    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("job_id", "recipient", name="uq_application_job_recipient"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs_automation.id"), index=True)
    recipient: Mapped[str] = mapped_column(String(320), index=True)
    status: Mapped[str] = mapped_column(String(50), default="PENDING", index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    response_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    response_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    response_type: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    last_contact_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    follow_up_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    follow_up_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    follow_up_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    interview_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    @property
    def is_active(self) -> bool:
        return self.status not in {
            "REJECTED",
            "POSITION_FILLED",
            "H2B_FULL",
            "HIRED",
            "CLOSED",
            "NO_RESPONSE",
        } or self.status == "AI_ERROR"


APPLICATION_STATUSES = {
    "PENDING",
    "SENT",
    "AUTO_REPLY",
    "FOLLOW_UP",
    "REPLIED",
    "INTERVIEW",
    "WAITING_RESPONSE",
    "REQUESTED_INFO",
    "AI_ERROR",
    "NO_RESPONSE",
    "REJECTED",
    "POSITION_FILLED",
    "H2B_FULL",
    "HIRED",
    "CLOSED",
}


def status_summary(status: str | None) -> str:
    return (status or "PENDING").upper()