from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any


OUT_OF_COUNTRY_CONFIRMED_KEYWORDS = (
    "out of country",
    "outside the united states",
    "outside the us",
    "outside u.s.",
    "applicants outside the united states",
    "applicants outside the us",
)
OUT_OF_COUNTRY_POSSIBLE_KEYWORDS = (
    "h-2b",
    "h2b",
    "visa sponsorship",
    "visa sponsor",
    "sponsorship available",
    "visa support",
    "international applicants",
    "international candidates",
    "internationally",
    "international",
    "foreign national",
    "foreign worker",
    "foreign workers",
    "overseas",
    "work authorization",
    "in-country and out of country",
)
IN_COUNTRY_ONLY_KEYWORDS = (
    "us applicants only",
    "u.s. applicants only",
    "united states applicants only",
    "citizens only",
    "must be authorized to work in the united states",
    "local candidates only",
    "within the united states only",
)
OUT_OF_COUNTRY_WEIGHTS = {
    "OUT_OF_COUNTRY_CONFIRMED": 30,
    "OUT_OF_COUNTRY_POSSIBLE": 15,
    "NOT_MENTIONED": 0,
    "IN_COUNTRY_ONLY": -30,
}


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _coerce_number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        cleaned = str(value).replace("$", "").replace(",", "").strip()
        if cleaned.lower() in {"", "n/a", "na"}:
            return None
        return float(cleaned)
    except (TypeError, ValueError):
        return None


def _days_until(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        if isinstance(value, str):
            value = value.split("T", 1)[0]
            value_date = datetime.fromisoformat(value).date()
        elif isinstance(value, datetime):
            value_date = value.date()
        elif isinstance(value, date):
            value_date = value
        else:
            return None
        today = datetime.utcnow().date()
        return (value_date - today).days
    except (TypeError, ValueError):
        return None


def _days_since(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        if isinstance(value, str):
            raw = value.split("T", 1)[0]
            if "/" in raw:
                value_date = datetime.strptime(raw, "%m/%d/%Y").date()
            else:
                value_date = datetime.fromisoformat(raw).date()
        elif isinstance(value, datetime):
            value_date = value.date()
        elif isinstance(value, date):
            value_date = value
        else:
            return None
        today = datetime.utcnow().date()
        return (today - value_date).days
    except (TypeError, ValueError):
        return None


def classify_out_of_country(text: str) -> str:
    normalized = text.casefold()

    if any(keyword in normalized for keyword in IN_COUNTRY_ONLY_KEYWORDS):
        return "IN_COUNTRY_ONLY"
    if any(keyword in normalized for keyword in OUT_OF_COUNTRY_CONFIRMED_KEYWORDS):
        return "OUT_OF_COUNTRY_CONFIRMED"
    if any(keyword in normalized for keyword in OUT_OF_COUNTRY_POSSIBLE_KEYWORDS):
        return "OUT_OF_COUNTRY_POSSIBLE"
    return "NOT_MENTIONED"


def extract_structured_job_facts(job_title: str, description: str | None) -> dict[str, Any]:
    text = f"{job_title or ''} {description or ''}".casefold()
    out_of_country_status = classify_out_of_country(text)

    h2b_relevant = any(token in text for token in (
        "h-2b", "h2b", "out of country", "outside the united states",
        "outside the us", "international applicants", "overseas",
        "visa sponsorship", "foreign worker", "foreign workers"
    ))

    has_accommodation = any(token in text for token in (
        "housing", "lodging", "accommodation", "room and board",
        "housing provided", "accommodation provided"
    ))

    is_hospitality = any(token in text for token in (
        "hotel", "motel", "resort", "housekeeper", "room attendant",
        "housekeeping", "guest service", "laundry", "restaurant", "cook",
        "dishwasher", "server", "front desk", "concierge"
    ))

    is_housekeeping = any(token in text for token in (
        "housekeeper", "housekeeping", "maid", "cleaner", "room attendant",
        "laundry", "public area attendant"
    ))

    is_seasonal = any(token in text for token in (
        "seasonal", "winter", "summer", "temporary", "peak season", "snow"
    ))

    salary_numbers = re.findall(r"\$\s?(\d+(?:\.\d+)?)", text)
    salary_value = float(salary_numbers[0]) if salary_numbers else 0.0

    positions_match = re.search(r"(\d+)\s*(?:positions?|openings?)", text)
    openings = int(positions_match.group(1)) if positions_match else 0

    begin_match = re.search(r"(\d{1,2}/\d{1,2}/\d{4})", text)
    start_date = begin_match.group(1) if begin_match else None

    return {
        "h2b_relevant": h2b_relevant,
        "out_of_country": out_of_country_status in {"OUT_OF_COUNTRY_CONFIRMED", "OUT_OF_COUNTRY_POSSIBLE"},
        "h2b_status": "OPEN" if out_of_country_status == "OUT_OF_COUNTRY_CONFIRMED" else "UNKNOWN",
        "has_accommodation": has_accommodation,
        "is_hospitality": is_hospitality,
        "is_housekeeping": is_housekeeping,
        "is_seasonal": is_seasonal,
        "openings": openings,
        "salary_value": salary_value,
        "begin_date_text": start_date,
        "out_of_country_status": out_of_country_status,
    }


def _detect_h2b_signals(job: dict[str, Any]) -> tuple[bool, bool, str, list[str]]:
    title = _coerce_text(job.get("title") or job.get("job_title"))
    description = _coerce_text(job.get("description") or job.get("job_duties"))
    combined = f"{title} {description}".casefold()
    reasons: list[str] = []

    h2b_relevant = any(
        keyword in combined
        for keyword in (
            "h-2b", "h2b", "visa sponsorship", "visa sponsor",
            "international applicants", "international candidates",
            "out of country", "outside the united states", "outside the us",
            "foreign worker", "foreign workers", "overseas",
        )
    )
    if h2b_relevant:
        reasons.append("H-2B mention; international hiring not confirmed")

    out_of_country_status = classify_out_of_country(combined)
    out_of_country = out_of_country_status in {"OUT_OF_COUNTRY_CONFIRMED", "OUT_OF_COUNTRY_POSSIBLE"}
    if out_of_country_status == "OUT_OF_COUNTRY_CONFIRMED":
        reasons.append("Out-of-country +30")
    elif out_of_country_status == "OUT_OF_COUNTRY_POSSIBLE":
        reasons.append("Out-of-country possible +15")
    elif out_of_country_status == "IN_COUNTRY_ONLY":
        reasons.append("In-country only -30")

    if out_of_country_status == "OUT_OF_COUNTRY_CONFIRMED":
        h2b_status = "OPEN"
    elif out_of_country_status == "IN_COUNTRY_ONLY":
        h2b_status = "FULL"
    else:
        h2b_status = "UNKNOWN"

    return h2b_relevant, out_of_country, h2b_status, reasons


def get_score_reasons(job: dict[str, Any]) -> str:
    reasons: list[str] = []
    title = _coerce_text(job.get("title") or job.get("job_title"))
    description = _coerce_text(job.get("description") or job.get("job_duties"))
    text = f"{title} {description}".casefold()

    h2b_relevant, out_of_country, h2b_status, reason_flags = _detect_h2b_signals(job)
    reasons.extend(reason_flags)

    if any(keyword in text for keyword in ("hotel", "resort", "seasonal", "housekeeper", "groundskeeper")):
        reasons.append("Seasonal hospitality match +30")

    positions = (
        job.get("job_openings")
        or job.get("positions_available")
        or job.get("openings")
        or job.get("number_of_positions")
    )
    try:
        openings = int(positions)
    except (TypeError, ValueError):
        openings = 0
    if openings >= 10:
        reasons.append("10+ openings +10")
    elif openings >= 5:
        reasons.append("5+ openings +5")

    published_date = (
        job.get("published_date")
        or job.get("posted_date")
        or job.get("date_posted")
        or job.get("publication_date")
        or job.get("created_date")
    )
    days_since_posted = _days_since(published_date)
    if days_since_posted is not None:
        if 0 <= days_since_posted <= 2:
            reasons.append("Recently published +30")
        elif 3 <= days_since_posted <= 7:
            reasons.append("Recently published +20")
        elif 8 <= days_since_posted <= 14:
            reasons.append("Published within 2 weeks +10")

    salary_from = _coerce_number(job.get("basic_rate_from"))
    salary_to = _coerce_number(job.get("basic_rate_to"))
    salary_target = max(salary_from or 0.0, salary_to or 0.0)
    if salary_target >= 17.0:
        reasons.append("Strong hourly pay +5")

    if any(keyword in text for keyword in ("housing", "lodging", "accommodation", "room and board")):
        reasons.append("Housing/accommodation +5")

    if any(keyword in text for keyword in ("experience required", "minimum experience", "2 years experience")):
        reasons.append("Experience requirement penalty -15")

    return "; ".join(reasons) if reasons else "No explicit scoring signal" 


def compute_job_score(job: dict[str, Any]) -> int:
    title = _coerce_text(job.get("title") or job.get("job_title"))
    description = _coerce_text(job.get("description") or job.get("job_duties"))
    employer_name = _coerce_text(job.get("employer_trade_name") or job.get("employer_business_name"))
    city = _coerce_text(job.get("worksite_city"))
    state = _coerce_text(job.get("worksite_state"))
    pay_range_desc = _coerce_text(job.get("pay_range_desc"))
    salary_from = _coerce_number(job.get("basic_rate_from"))
    salary_to = _coerce_number(job.get("basic_rate_to"))
    published_date = (
        job.get("published_date")
        or job.get("posted_date")
        or job.get("date_posted")
        or job.get("publication_date")
        or job.get("created_date")
    )
    begin_date = job.get("begin_date")
    h2b_need_date = (
        job.get("first_date_of_need")
        or job.get("date_of_need")
        or job.get("need_date")
        or job.get("need_start_date")
        or begin_date
    )
    days_since_posted = _days_since(published_date)
    days_until_need = _days_until(h2b_need_date)
    positions = (
        job.get("job_openings")
        or job.get("positions_available")
        or job.get("openings")
        or job.get("number_of_positions")
    )
    try:
        openings = int(positions)
    except (TypeError, ValueError):
        openings = 0

    text = f"{title} {description} {employer_name} {city} {state} {pay_range_desc}".casefold()
    score = 0

    h2b_keywords = (
        "ski resort", "resort", "hotel", "housekeeper", "housekeeping",
        "room attendant", "laundry", "restaurant", "food service", "cook",
        "dishwasher", "waiter", "waitress", "kitchen", "warehouse",
        "material handler", "forklift", "landscaping", "landscaper",
        "maintenance", "construction", "camp", "seasonal", "cleaner",
        "cleaning", "amusement", "recreation", "seafood", "seafood processing",
        "public area", "groundskeeper", "housekeeping attendant"
    )
    if title and any(keyword in text for keyword in h2b_keywords):
        score += 30

    if "h-2a" in text or "h2a" in text or "farm" in text or "agriculture" in text:
        score -= 10

    out_of_country_status = classify_out_of_country(text)
    score += OUT_OF_COUNTRY_WEIGHTS.get(out_of_country_status, 0)

    start_days = _days_until(begin_date)
    if start_days is not None and 0 <= start_days <= 180:
        score += 15
    if start_days is not None and 30 <= start_days <= 180:
        score += 10

    if days_since_posted is not None:
        if 0 <= days_since_posted <= 2:
            score += 30
        elif 3 <= days_since_posted <= 7:
            score += 20
        elif 8 <= days_since_posted <= 14:
            score += 10
        elif 15 <= days_since_posted <= 30:
            score += 3
        elif days_since_posted > 30:
            score -= 20

    if days_until_need is not None:
        if 0 <= days_until_need <= 21:
            score += 15
        elif 22 <= days_until_need <= 60:
            score += 10
        elif 61 <= days_until_need <= 180:
            score += 5
        elif days_until_need > 180:
            score -= 10

    if openings >= 10:
        score += 10
    elif openings >= 5:
        score += 5

    no_experience_keywords = (
        "no experience required", "no previous experience required",
        "experience preferred", "no experience needed", "entry level",
        "no experience",
    )
    if any(keyword in text for keyword in no_experience_keywords):
        score += 5

    accommodation_keywords = (
        "housing", "lodging", "accommodation", "room and board",
        "housing provided", "accommodation provided"
    )
    if any(keyword in text for keyword in accommodation_keywords):
        score += 5

    salary_target = max(salary_from or 0.0, salary_to or 0.0)
    if salary_target >= 17.0 or "$18" in pay_range_desc or "$20" in pay_range_desc:
        score += 5

    if "experience required" in text or "2 years experience" in text or "minimum experience" in text:
        score = max(0, score - 15)

    return max(0, min(score, 105))


def get_priority_label(score: int) -> str:
    if score >= 90:
        return "🔥 prioridade máxima"
    if score >= 75:
        return "🟢 prioridade alta"
    if score >= 60:
        return "🟡 prioridade média"
    if score >= 40:
        return "🟠 baixa"
    return "🔴 não enviar"
