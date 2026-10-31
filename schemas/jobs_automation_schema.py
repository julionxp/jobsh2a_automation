from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


class JobAutomationSchema(BaseModel):
    title: str
    case_number: str
    emails: str | None = None
    description: str | None = None
    url: str
    search_term: str | None = None
    job_category: str | None = None

    begin_date: datetime | None = None
    end_date: datetime | None = None
    first_date_of_need: datetime | None = None
    published_date: datetime | None = None

    basic_rate_from: float | int | None = None
    basic_rate_to: float | int | None = None
    pay_range_desc: str | None = None
    employer_trade_name: str | None = None
    employer_business_name: str | None = None
    worksite_city: str | None = None
    worksite_state: str | None = None
    positions_available: int | None = None
    job_openings: int | None = None
    h2a_relevant: bool | None = True
    h2b_relevant: bool | None = None
    out_of_country: bool | None = None
    h2b_status: str | None = None
    job_score: int | None = None
    priority: str | None = None
    score_reasons: str | None = None

    @field_validator(
        "begin_date",
        "end_date",
        "first_date_of_need",
        "published_date",
        mode="before",
    )
    @classmethod
    def normalize_dates(cls, value):
        if value in (None, ""):
            return None

        if isinstance(value, datetime):
            return value

        if isinstance(value, str):
            value = value.strip()

            # ISO 8601:
            # 2026-10-01T00:00:00Z
            try:
                return datetime.fromisoformat(
                    value.replace("Z", "+00:00")
                ).replace(tzinfo=None)
            except ValueError:
                pass

            # Formato da API:
            # 7/27/2026
            for fmt in ("%m/%d/%Y", "%m/%d/%y"):
                try:
                    return datetime.strptime(value, fmt)
                except ValueError:
                    pass

        return value

    model_config = ConfigDict(from_attributes=True)