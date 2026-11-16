from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.database import DBBaseModel


class JobAutomationModel(DBBaseModel):
    __tablename__ = "jobs_automation"

    id: Mapped[int] = mapped_column(primary_key=True)

    title: Mapped[str] = mapped_column(String(255))
    case_number: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    emails: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str] = mapped_column(String(500))
    search_term: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    job_category: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)

    begin_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    end_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    first_date_of_need: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    published_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    basic_rate_from: Mapped[float | None] = mapped_column(Float, nullable=True)
    basic_rate_to: Mapped[float | None] = mapped_column(Float, nullable=True)
    pay_range_desc: Mapped[str | None] = mapped_column(Text, nullable=True)
    employer_trade_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    employer_business_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    worksite_city: Mapped[str | None] = mapped_column(String(255), nullable=True)
    worksite_state: Mapped[str | None] = mapped_column(String(100), nullable=True)
    positions_available: Mapped[int | None] = mapped_column(Integer, nullable=True)
    job_openings: Mapped[int | None] = mapped_column(Integer, nullable=True)
    h2b_relevant: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)
    out_of_country: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)
    h2b_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    job_score: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    priority: Mapped[str | None] = mapped_column(String(50), nullable=True)
    score_reasons: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )