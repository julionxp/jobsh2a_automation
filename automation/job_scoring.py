from __future__ import annotations
import re
from datetime import date, datetime
from typing import Any

AGRICULTURE_KEYWORDS = ("farmworker", "farm worker", "farm laborer", "agricultural", "agriculture", "harvest", "crop", "orchard", "greenhouse", "nursery", "field worker", "fruit", "vegetable", "livestock", "ranch", "cattle", "dairy", "poultry", "tractor", "irrigation", "packing house", "farm labor")

def _text(job: dict[str, Any]) -> str:
    return " ".join(str(job.get(k) or "") for k in ("title", "job_title", "description", "job_duties", "employer_trade_name", "employer_business_name")).casefold()

def _number(value: Any) -> float | None:
    if value in (None, ""): return None
    try: return float(re.sub(r"[^0-9.]", "", str(value)))
    except (TypeError, ValueError): return None

def _date(value: Any) -> date | None:
    if value in (None, ""): return None
    if isinstance(value, datetime): return value.date()
    if isinstance(value, date): return value
    raw = str(value).strip().split("T", 1)[0]
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try: return datetime.strptime(raw, fmt).date()
        except ValueError: pass
    return None

def _days_since(value: Any) -> int | None:
    parsed = _date(value)
    return (date.today() - parsed).days if parsed else None

def _days_until(value: Any) -> int | None:
    parsed = _date(value)
    return (parsed - date.today()).days if parsed else None

def _detect_h2b_signals(job: dict[str, Any]) -> tuple[bool, bool, str, list[str]]:
    return False, False, "H2A_ORDER", ["Official H-2A 790/790A job order"]

def get_score_reasons(job: dict[str, Any]) -> str:
    text = _text(job)
    reasons = ["H-2A order from official DOL feed"]
    if any(term in text for term in AGRICULTURE_KEYWORDS): reasons.append("Agricultural job match +30")
    openings = _number(job.get("job_openings") or job.get("positions_available"))
    if openings and openings >= 10: reasons.append("10+ openings +10")
    elif openings and openings >= 5: reasons.append("5+ openings +5")
    age = _days_since(job.get("published_date"))
    if age is not None and 0 <= age <= 2: reasons.append("Recently posted/updated +30")
    elif age is not None and age <= 7: reasons.append("Updated within 7 days +20")
    elif age is not None and age <= 14: reasons.append("Updated within 14 days +10")
    wage = max(_number(job.get("basic_rate_from")) or 0, _number(job.get("basic_rate_to")) or 0)
    if wage >= 18: reasons.append("Hourly wage $18+ +10")
    elif wage >= 16: reasons.append("Hourly wage $16+ +5")
    if any(w in text for w in ("housing", "lodging", "accommodation", "room and board")): reasons.append("Housing mentioned +5")
    if "no experience" in text or "entry level" in text: reasons.append("No experience/entry level +5")
    if any(w in text for w in ("experience required", "months of experience", "years of experience")): reasons.append("Experience requirement -10")
    return "; ".join(reasons)

def compute_job_score(job: dict[str, Any]) -> int:
    text = _text(job)
    score = 30 if any(term in text for term in AGRICULTURE_KEYWORDS) else 0
    age = _days_since(job.get("published_date"))
    if age is not None:
        if 0 <= age <= 2: score += 30
        elif age <= 7: score += 20
        elif age <= 14: score += 10
        elif age > 20: score -= 10
    days = _days_until(job.get("first_date_of_need") or job.get("begin_date"))
    if days is not None:
        if 0 <= days <= 30: score += 15
        elif days <= 90: score += 10
        elif days <= 180: score += 5
        elif days < 0: score -= 20
    openings = _number(job.get("job_openings") or job.get("positions_available"))
    if openings and openings >= 10: score += 10
    elif openings and openings >= 5: score += 5
    wage = max(_number(job.get("basic_rate_from")) or 0, _number(job.get("basic_rate_to")) or 0)
    if wage >= 18: score += 10
    elif wage >= 16: score += 5
    if any(w in text for w in ("housing", "lodging", "accommodation", "room and board")): score += 5
    if "no experience" in text or "entry level" in text: score += 5
    if any(w in text for w in ("experience required", "months of experience", "years of experience")): score -= 10
    return max(0, min(score, 100))

def get_priority_label(score: int) -> str:
    if score >= 80: return "🔥 prioridade máxima"
    if score >= 65: return "🟢 prioridade alta"
    if score >= 50: return "🟡 prioridade média"
    if score >= 35: return "🟠 baixa"
    return "🔴 não enviar"
