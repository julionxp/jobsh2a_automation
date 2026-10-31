import argparse
import asyncio
import re
import io
import json
import zipfile
from zoneinfo import ZoneInfo
from datetime import datetime, timedelta
from threading import Thread
from typing import Any

import requests
from playwright.sync_api import Page, Playwright, sync_playwright
from sqlalchemy import select, text

from automation.ia_send_email import identify_job_category
from automation.job_scoring import (
    compute_job_score,
    get_priority_label,
    get_score_reasons,
)
from core.database import DBBaseModel, Session, engine
from models.jobs_automation_model import JobAutomationModel
from schemas.jobs_automation_schema import JobAutomationSchema


BASE_URL = "https://seasonaljobs.dol.gov"
FEED_URL = "https://api.seasonaljobs.dol.gov/datahub-search/sjCaseData/zip/jo/{feed_date}"
EMAIL_PATTERN = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I,)
DEFAULT_SEARCH_TERMS = ["farmworker", "farm laborer", "agricultural worker", "harvest", "crop", "nursery", "greenhouse", "livestock", "ranch", "orchard", "fruit picking", "vegetable", "field worker"]


def resolve_search_terms(search: str | None) -> list[str]:
    if not search or not str(search).strip():
        return DEFAULT_SEARCH_TERMS

    custom_terms = [
        term.strip()
        for term in str(search).split(",")
        if term.strip()
    ]
    return custom_terms or DEFAULT_SEARCH_TERMS


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


def _flatten_record(value: Any) -> dict[str, Any]:
    result = {}
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, dict):
                result.update(_flatten_record(item))
            else:
                result[_normalize_key(key)] = item
    return result


def _pick(record: dict[str, Any], *aliases: str) -> Any:
    for alias in aliases:
        value = record.get(_normalize_key(alias))
        if value not in (None, ""):
            return value
    return None


def _feed_records(payload: Any) -> list[dict[str, Any]]:
    records = []
    if isinstance(payload, list):
        for item in payload:
            records.extend(_feed_records(item))
    elif isinstance(payload, dict):
        flat = _flatten_record(payload)
        if _pick(flat, "case_number", "eta_case_number", "job_order_number", "job_order_case_number", "caseNumber", "jobOrderNumber"):
            records.append(flat)
        else:
            for value in payload.values():
                if isinstance(value, (dict, list)):
                    records.extend(_feed_records(value))
    return records


def _normalize_feed_job(raw: dict[str, Any]) -> dict[str, Any] | None:
    case = _pick(raw, "case_number", "eta_case_number", "job_order_number", "job_order_case_number", "caseNumber", "jobOrderNumber")
    if not case:
        return None
    title = _pick(raw, "job_title", "occupation_title", "soc_title", "jobtitle") or "Agricultural Worker"
    description = _pick(raw, "job_duties", "duties", "job_description", "description") or ""
    employer = _pick(raw, "employer_trade_name", "employer_business_name", "employer_name", "business_name")
    email = _pick(raw, "email_address_to_apply", "email_to_apply", "recruitment_email", "email")
    phone = _pick(raw, "telephone_number_to_apply", "phone_to_apply", "recruitment_phone", "phone")
    duties = str(description)
    if email:
        duties += f"\\nRecruitment email: {email}"
    if phone:
        duties += f"\\nRecruitment phone: {phone}"
    openings = _pick(raw, "job_openings", "number_of_workers_requested", "workers_requested", "positions_available", "openings")
    begin = _pick(raw, "begin_date", "employment_begin_date", "start_date", "first_date_of_need")
    return {
        "title": str(title), "case_number": str(case).strip(),
        "url": f"{BASE_URL}/jobs/{str(case).strip()}",
        "begin_date": begin, "end_date": _pick(raw, "end_date", "employment_end_date"),
        "first_date_of_need": begin,
        "published_date": _pick(raw, "date_posted", "posted_date", "published_date", "date_submitted", "submission_date", "last_updated", "updated_date"),
        "basic_rate_from": _pick(raw, "basic_rate_from", "wage_rate_from", "offered_wage_rate_from", "wage_from"),
        "basic_rate_to": _pick(raw, "basic_rate_to", "wage_rate_to", "offered_wage_rate_to", "wage_to"),
        "pay_range_desc": _pick(raw, "pay_range_desc", "wage_description", "wage_rate"),
        "employer_trade_name": employer, "employer_business_name": employer,
        "worksite_city": _pick(raw, "worksite_city", "city", "place_of_employment_city"),
        "worksite_state": _pick(raw, "worksite_state", "state", "place_of_employment_state"),
        "job_openings": openings, "positions_available": openings,
        "description": duties, "emails": str(email) if email else None,
        "search_term": "H-2A 790/790A feed",
        "job_category": identify_job_category(str(title), duties),
    }


def get_job_links(session: requests.Session, begin_after: str, search: str | None) -> list[dict[str, Any]]:
    """Baixa o feed oficial 790/790A: ordens H-2A enviadas/atualizadas nos últimos 20 dias."""
    print("\\n>>> BAIXANDO FEED OFICIAL H-2A 790/790A...")
    today_et = datetime.now(ZoneInfo("America/New_York")).date()
    response = None
    errors = []
    for offset in range(2):
        day = (today_et - timedelta(days=offset)).isoformat()
        try:
            candidate = session.get(FEED_URL.format(feed_date=day), timeout=90)
            candidate.raise_for_status()
            if not candidate.content:
                raise ValueError("Feed vazio")
            response = candidate
            print(f">>> Feed recebido: {day}")
            break
        except Exception as exc:
            errors.append(f"{day}: {exc}")
    if response is None:
        raise RuntimeError("Falha ao baixar feed H-2A 790/790A: " + " | ".join(errors))
    try:
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            names = [name for name in archive.namelist() if name.lower().endswith(".json")]
            if not names:
                raise ValueError(f"ZIP sem JSON. Conteúdo: {archive.namelist()[:8]}")
            payload = json.loads(archive.read(names[0]).decode("utf-8-sig"))
    except (zipfile.BadZipFile, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError(f"Falha ao interpretar ZIP/JSON do feed: {exc}") from exc
    raw_records = _feed_records(payload)
    print(f">>> Registros identificados no feed: {len(raw_records)}")
    terms = [term.casefold() for term in resolve_search_terms(search)] if search else []
    records, seen = [], set()
    for raw in raw_records:
        item = _normalize_feed_job(raw)
        if not item or item["case_number"] in seen:
            continue
        seen.add(item["case_number"])
        searchable = " ".join(str(item.get(k) or "") for k in ("title", "description", "employer_trade_name", "worksite_city", "worksite_state")).casefold()
        if terms and not any(term in searchable for term in terms):
            continue
        records.append(item)
    print(f">>> ORDENS H-2A NOVAS/ATUALIZADAS: {len(records)}")
    return records



def extract_job(page: Page, url: str, api_job: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Abre uma página individual da vaga e extrai os dados necessários para
    score, seleção de vagas e persistência completa no banco.
    """

    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")

    api_job = api_job or {}
    body_text = page.locator("body").inner_text()

    emails = set()
    for href in page.locator('a[href^="mailto:"]').evaluate_all(
        "links => links.map(link => link.href)"
    ):
        emails.update(EMAIL_PATTERN.findall(href.removeprefix("mailto:")))

    if not emails:
        emails.update(EMAIL_PATTERN.findall(body_text))

    case_match = re.search(r"ETA Case Number:\s*([A-Z0-9-]+)", body_text)

    title = (
        page.locator("h2").first.inner_text()
        if page.locator("h2").count()
        else ""
    ).strip()

    description = ""
    description_heading = page.get_by_role("heading", name="Job Description", exact=True)
    if description_heading.count():
        job_description = description_heading.locator("xpath=..").inner_text()
        match = re.search(
            r"Job Duties:\s*(.*?)(?:\s*Job Classification:|$)",
            job_description,
            re.DOTALL,
        )
        if match:
            description = match.group(1).strip()

    positions_match = re.search(r"(\d+)\s+openings?", body_text, re.I)
    positions_available = int(positions_match.group(1)) if positions_match else None
    published_match = None
    for pattern in [
        r"Posted\s*[:\-]?\s*(\d{1,2}/\d{1,2}/\d{4})",
        r"Date Posted\s*[:\-]?\s*(\d{1,2}/\d{1,2}/\d{4})",
        r"Published\s*[:\-]?\s*(\d{1,2}/\d{1,2}/\d{4})",
    ]:
        published_match = re.search(pattern, body_text, re.I)
        if published_match:
            break
    published_date = (
        api_job.get("published_date")
        or api_job.get("posted_date")
        or api_job.get("date_posted")
        or api_job.get("publication_date")
        or (published_match.group(1) if published_match else None)
    )
    first_date_of_need = (
        api_job.get("first_date_of_need")
        or api_job.get("date_of_need")
        or api_job.get("need_date")
        or api_job.get("need_start_date")
        or api_job.get("begin_date")
    )
    job_openings = (
        api_job.get("job_openings")
        or api_job.get("positions_available")
        or api_job.get("openings")
        or api_job.get("number_of_positions")
        or positions_available
    )

    result = {
        "title": title or api_job.get("title") or "",
        "url": page.url,
        "case_number": case_match.group(1) if case_match else api_job.get("case_number") or "",
        "emails": "; ".join(sorted(emails)),
        "description": description,
        "begin_date": api_job.get("begin_date") or None,
        "end_date": api_job.get("end_date") or None,
        "first_date_of_need": first_date_of_need,
        "published_date": published_date,
        "basic_rate_from": api_job.get("basic_rate_from"),
        "basic_rate_to": api_job.get("basic_rate_to"),
        "pay_range_desc": api_job.get("pay_range_desc") or None,
        "employer_trade_name": api_job.get("employer_trade_name") or None,
        "employer_business_name": api_job.get("employer_business_name") or None,
        "worksite_city": api_job.get("worksite_city") or None,
        "worksite_state": api_job.get("worksite_state") or None,
        "job_openings": job_openings,
        "positions_available": job_openings,
        "search_term": api_job.get("search_term"),
        "job_category": identify_job_category(title or api_job.get("title") or "", description),
    }

    from automation.job_scoring import get_score_reasons
    result["h2a_relevant"] = True
    result["h2b_relevant"] = False
    result["out_of_country"] = False
    result["h2b_status"] = "H2A_ORDER"
    result["score_reasons"] = get_score_reasons(result)
    result["job_score"] = compute_job_score(result)
    result["priority"] = get_priority_label(result["job_score"])
    return result


async def create_tables() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(DBBaseModel.metadata.create_all)
        columns = await connection.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'jobs_automation'
        """))
        column_names = {row[0] for row in columns}

        if "job_description" in column_names and "description" not in column_names:
            await connection.execute(text("""
                ALTER TABLE jobs_automation
                RENAME COLUMN job_description TO description
            """))

        required_columns = {
            "search_term": "ALTER TABLE jobs_automation ADD COLUMN IF NOT EXISTS search_term VARCHAR(255)",
            "job_category": "ALTER TABLE jobs_automation ADD COLUMN IF NOT EXISTS job_category VARCHAR(100)",
            "begin_date": "ALTER TABLE jobs_automation ADD COLUMN IF NOT EXISTS begin_date TIMESTAMP",
            "end_date": "ALTER TABLE jobs_automation ADD COLUMN IF NOT EXISTS end_date TIMESTAMP",
            "first_date_of_need": "ALTER TABLE jobs_automation ADD COLUMN IF NOT EXISTS first_date_of_need TIMESTAMP",
            "published_date": "ALTER TABLE jobs_automation ADD COLUMN IF NOT EXISTS published_date TIMESTAMP",
            "basic_rate_from": "ALTER TABLE jobs_automation ADD COLUMN IF NOT EXISTS basic_rate_from DOUBLE PRECISION",
            "basic_rate_to": "ALTER TABLE jobs_automation ADD COLUMN IF NOT EXISTS basic_rate_to DOUBLE PRECISION",
            "pay_range_desc": "ALTER TABLE jobs_automation ADD COLUMN IF NOT EXISTS pay_range_desc TEXT",
            "employer_trade_name": "ALTER TABLE jobs_automation ADD COLUMN IF NOT EXISTS employer_trade_name VARCHAR(255)",
            "employer_business_name": "ALTER TABLE jobs_automation ADD COLUMN IF NOT EXISTS employer_business_name VARCHAR(255)",
            "worksite_city": "ALTER TABLE jobs_automation ADD COLUMN IF NOT EXISTS worksite_city VARCHAR(255)",
            "worksite_state": "ALTER TABLE jobs_automation ADD COLUMN IF NOT EXISTS worksite_state VARCHAR(100)",
            "positions_available": "ALTER TABLE jobs_automation ADD COLUMN IF NOT EXISTS positions_available INTEGER",
            "job_openings": "ALTER TABLE jobs_automation ADD COLUMN IF NOT EXISTS job_openings INTEGER",
            "h2b_relevant": "ALTER TABLE jobs_automation ADD COLUMN IF NOT EXISTS h2b_relevant BOOLEAN",
            "h2a_relevant": "ALTER TABLE jobs_automation ADD COLUMN IF NOT EXISTS h2a_relevant BOOLEAN",
            "out_of_country": "ALTER TABLE jobs_automation ADD COLUMN IF NOT EXISTS out_of_country BOOLEAN",
            "h2b_status": "ALTER TABLE jobs_automation ADD COLUMN IF NOT EXISTS h2b_status VARCHAR(50)",
            "job_score": "ALTER TABLE jobs_automation ADD COLUMN IF NOT EXISTS job_score INTEGER",
            "priority": "ALTER TABLE jobs_automation ADD COLUMN IF NOT EXISTS priority VARCHAR(50)",
            "score_reasons": "ALTER TABLE jobs_automation ADD COLUMN IF NOT EXISTS score_reasons TEXT",
        }

        for column_name, alter_sql in required_columns.items():
            if column_name not in column_names:
                await connection.execute(text(alter_sql))


async def save_job(row: dict[str, str]) -> None:
    """Persiste uma vaga e atualiza registros existentes pelo case_number."""
    if isinstance(row.get("emails"), str):
        row["emails"] = row["emails"].strip() or None
    if isinstance(row.get("description"), str):
        row["description"] = row["description"].strip() or None

    row["job_category"] = row.get("job_category") or identify_job_category(
        row.get("title") or "",
        row.get("description"),
    )

    row["h2a_relevant"] = True
    row["h2b_relevant"] = False
    row["out_of_country"] = False
    row["h2b_status"] = "H2A_ORDER"
    row["score_reasons"] = get_score_reasons(row)
    row["job_score"] = compute_job_score(row)
    row["priority"] = get_priority_label(row["job_score"])

    job_data = JobAutomationSchema.model_validate(row)

    async with Session() as session:
        result = await session.execute(
            select(JobAutomationModel).where(
                JobAutomationModel.case_number == job_data.case_number
            )
        )
        job = result.scalar_one_or_none()

        if job is None:
            session.add(JobAutomationModel(**job_data.model_dump()))
        else:
            for field, value in job_data.model_dump().items():
                # Preserve dados anteriores quando a extração atual não encontrou o campo.
                if value is not None:
                    setattr(job, field, value)

        await session.commit()


def run(playwright: Playwright, search: str, begin_after: str, headless: bool,) -> None:

    print("\n========================================")
    print("       SEASONALJOBS AUTOMATION")
    print("========================================")

    # --------------------------------------------------
    # HTTP SESSION
    # --------------------------------------------------

    session = requests.Session()

    session.headers.update(
        {
            "User-Agent": (
                "cv-process-automation/1.0"
            )
        }
    )

    # --------------------------------------------------
    # BUSCAR VAGAS
    # --------------------------------------------------

    all_job_links: list[dict[str, Any]] = []
    seen_case_numbers: set[str] = set()

    for search_term in ([search] if search else [None]):
        job_links = get_job_links(
            session=session,
            begin_after=begin_after,
            search=search_term,
        )
        for job in job_links:
            case_number = str(job.get("case_number") or "").strip()
            if not case_number or case_number in seen_case_numbers:
                continue
            seen_case_numbers.add(case_number)
            job["search_term"] = search_term
            all_job_links.append(job)

    job_links = all_job_links
    print(
        f"\n>>> VAGAS ENCONTRADAS: "
        f"{len(job_links)}"
    )

    if not job_links:

        print(
            ">>> Nenhuma vaga encontrada."
        )

        return

    # --------------------------------------------------
    # PLAYWRIGHT
    # --------------------------------------------------

    browser = playwright.chromium.launch(
        headless=headless
    )

    context = browser.new_context()

    page = context.new_page()

    database_loop = asyncio.new_event_loop()
    database_thread = Thread(
        target=database_loop.run_forever,
        daemon=True,
    )
    database_thread.start()

    try:
        database_future = asyncio.run_coroutine_threadsafe(
            create_tables(),
            database_loop,
        )
        database_future.result()

        # --------------------------------------------------
        # EXTRAÇÃO E PERSISTÊNCIA
        # --------------------------------------------------

        for index, job_data in enumerate(
            job_links,
            start=1,
        ):

            url = job_data["url"]
            print(
                f"\n>>> INICIANDO VAGA "
                f"{index}/{len(job_links)}"
            )

            print(f">>> URL: {url}")

            try:

                try:
                    row = extract_job(page, url, job_data)
                except Exception as page_error:
                    print(f">>> Página indisponível; usando dados do feed: {page_error}")
                    row = dict(job_data)
                    row.setdefault("emails", None)
                    row["h2a_relevant"] = True
                    row["h2b_relevant"] = False
                    row["out_of_country"] = False
                    row["h2b_status"] = "H2A_ORDER"
                    row["score_reasons"] = get_score_reasons(row)
                    row["job_score"] = compute_job_score(row)
                    row["priority"] = get_priority_label(row["job_score"])

                if not row["case_number"]:
                    print(f"[{index}/{len(job_links)}] Vaga ignorada: case_number ausente")
                    continue

                database_future = asyncio.run_coroutine_threadsafe(
                    save_job(row),
                    database_loop,
                )
                database_future.result()

                print(
                    f"[{index}/{len(job_links)}] "
                    f"{row['title']} - {row['job_score']} ({row['priority']}) - "
                    f"{row['emails'] or 'sem e-mail'}"
                )

                print(
                    f">>> SALVOU VAGA NO POSTGRESQL "
                    f"{index}/{len(job_links)}"
                )

            except Exception as error:

                print(
                    f"[{index}/{len(job_links)}] "
                    f"ERRO em {url}: "
                    f"{error}"
                )

    finally:
        database_future = asyncio.run_coroutine_threadsafe(
            engine.dispose(),
            database_loop,
        )
        database_future.result()
        database_loop.call_soon_threadsafe(database_loop.stop)
        database_thread.join()

    # --------------------------------------------------
    # ENCERRAMENTO
    # --------------------------------------------------

    context.close()

    browser.close()

    session.close()

    print("\n========================================")
    print("          AUTOMAÇÃO FINALIZADA")
    print("========================================")


def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description=(
            "Extrai informações das vagas "
            "do SeasonalJobs."
        )
    )

    parser.add_argument(
        "--search",
        default=None,
        help=(
            "Termo da vaga, empresa ou ocupação. "
            "Se não informado, usa uma lista estratégica de termos H-2A agricultural jobs."
        ),
    )

    parser.add_argument(
        "--begin-after",
        default="09/01",
        help=(
            "Data de referência da janela de busca no formato MM/DD. "
            "A automação usa este ponto como âncora e considera os próximos 180 dias, "
            "em vez de um filtro rígido do tipo 10/01."
        ),
    )

    parser.add_argument(
        "--headless",
        action="store_true",
        help="Executa o navegador sem interface gráfica",
    )

    parser.add_argument(
        "--send",
        action="store_true",
        help="Autoriza o envio real dos emails após a extração.",
    )

    return parser.parse_args()


def main() -> None:

    args = parse_args()

    with sync_playwright() as playwright:

        run(
            playwright=playwright,
            search=args.search,
            begin_after=args.begin_after,
            headless=args.headless,
        )
