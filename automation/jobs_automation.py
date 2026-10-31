import argparse
import asyncio
import re
from datetime import datetime, timedelta
from threading import Thread
from typing import Any

import requests
from playwright.sync_api import Page, Playwright, sync_playwright
from sqlalchemy import select, text

from automation.ia_send_email import identify_job_category
from automation.job_scoring import compute_job_score, get_priority_label
from core.database import Base, Session, engine
from models.jobs_automation_model import JobAutomationModel
from schemas.jobs_automation_schema import JobAutomationSchema


BASE_URL = "https://seasonaljobs.dol.gov"
API_URL = ("https://api.seasonaljobs.dol.gov/""datahub/search?api-version=2020-06-30")
EMAIL_PATTERN = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I,)
DEFAULT_SEARCH_TERMS = [
    "housekeeper",
    "hotel",
    "resort",
    "ski resort",
    "landscaping",
    "cook",
    "dishwasher",
    "restaurant",
    "server",
    "warehouse",
    "material handler",
    "seafood",
    "maintenance",
    "groundskeeper",
]


def resolve_search_terms(search: str | None) -> list[str]:
    if not search or not str(search).strip():
        return DEFAULT_SEARCH_TERMS

    custom_terms = [
        term.strip()
        for term in str(search).split(",")
        if term.strip()
    ]
    return custom_terms or DEFAULT_SEARCH_TERMS


def get_job_links(session: requests.Session, begin_after: str, search: str,) -> list[dict[str, Any]]:
    """
    Busca vagas em uma janela dinâmica de até 180 dias e retorna os registros
    completos para persistência e ranking. A data de início é apenas uma âncora;
    a priorização real vem da recência e da janela H-2B.
    """

    print("\n>>> BUSCANDO VAGAS PELA API...")

    today = datetime.utcnow().date()
    try:
        request_date = datetime.strptime(begin_after, "%m/%d").date()
    except ValueError:
        raise ValueError("A data deve estar no formato MM/DD. Exemplo: 10/01")

    anchor_date = max(today, request_date.replace(year=today.year))
    window_start = anchor_date
    window_end = anchor_date + timedelta(days=180)

    filter_prefix = "active eq true and display eq true "
    filter_expr = (
        f"{filter_prefix}"
        f"and begin_date ge {window_start.strftime('%Y-%m-%dT00:00:00.000Z')} "
        f"and begin_date le {window_end.strftime('%Y-%m-%dT00:00:00.000Z')}"
    )

    top = 40
    skip = 0
    all_jobs = []

    while True:
        payload = {
            "search": search,
            "searchFields": (
                "job_title, job_duties, soc_code_id, soc_title, "
                "case_number, worksite_city, worksite_state, "
                "employer_business_name, employer_trade_name"
            ),
            "filter": filter_expr,
            "orderby": "search.score() desc",
            "top": top,
            "skip": skip,
            "select": (
                "active,case_number,job_title,begin_date,end_date,"
                "basic_rate_from,basic_rate_to,pay_range_desc,"
                "employer_trade_name,employer_business_name,"
                "worksite_city,worksite_state"
            ),
            "count": True,
            "facets": [
                "job_title, count:4, sort:count"
            ],
        }

        print(f">>> Buscando vagas {skip + 1} até {skip + top}...")

        response = session.post(API_URL, json=payload, timeout=30,)
        response.raise_for_status()

        data = response.json()
        total = data.get("@odata.count", 0)
        jobs = data.get("value", [])

        print(f">>> API retornou {len(jobs)} vagas (total disponível: {total})")
        all_jobs.extend(jobs)

        if not jobs:
            break

        skip += top
        if skip >= total:
            break

    print(f"\n>>> TOTAL DE VAGAS COLETADAS: {len(all_jobs)}")

    records: list[dict[str, Any]] = []
    seen: set[str] = set()

    for job in all_jobs:
        case_number = job.get("case_number")
        if not case_number:
            continue

        normalized = str(case_number).strip()
        if normalized in seen:
            continue
        seen.add(normalized)

        records.append({
            "title": job.get("job_title") or "",
            "case_number": normalized,
            "url": f"{BASE_URL}/jobs/{normalized}",
            "begin_date": job.get("begin_date"),
            "end_date": job.get("end_date"),
            "first_date_of_need": job.get("first_date_of_need") or job.get("date_of_need") or job.get("need_date") or job.get("need_start_date") or job.get("begin_date"),
            "published_date": job.get("published_date") or job.get("posted_date") or job.get("date_posted") or job.get("publication_date") or job.get("created_date"),
            "basic_rate_from": job.get("basic_rate_from"),
            "basic_rate_to": job.get("basic_rate_to"),
            "pay_range_desc": job.get("pay_range_desc"),
            "employer_trade_name": job.get("employer_trade_name"),
            "employer_business_name": job.get("employer_business_name"),
            "worksite_city": job.get("worksite_city"),
            "worksite_state": job.get("worksite_state"),
            "job_openings": job.get("job_openings") or job.get("positions_available") or job.get("openings") or job.get("number_of_positions"),
            "positions_available": job.get("job_openings") or job.get("positions_available") or job.get("openings") or job.get("number_of_positions"),
            "search_term": job.get("search_term"),
        })

    print(f">>> TOTAL DE REGISTROS GERADOS: {len(records)}")
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

    h2b_relevant, out_of_country, h2b_status, _ = (lambda: (
        (False, False, "UNKNOWN", [])
    ))()
    try:
        from automation.job_scoring import _detect_h2b_signals, get_score_reasons
        h2b_relevant, out_of_country, h2b_status, _ = _detect_h2b_signals(result)
        result["score_reasons"] = get_score_reasons(result)
    except Exception:
        result["score_reasons"] = "No scoring breakdown available"
    result["h2b_relevant"] = h2b_relevant
    result["out_of_country"] = out_of_country
    result["h2b_status"] = h2b_status
    result["job_score"] = compute_job_score(result)
    result["priority"] = get_priority_label(result["job_score"])
    return result


async def create_tables() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
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

    row["job_category"] = row.get("job_category") or identify_job_category(
        row.get("title") or "",
        row.get("description"),
    )

    h2b_relevant, out_of_country, h2b_status, _ = __import__(
        "automation.job_scoring",
        fromlist=["_detect_h2b_signals"],
    )._detect_h2b_signals(row)
    row["h2b_relevant"] = h2b_relevant
    row["out_of_country"] = out_of_country
    row["h2b_status"] = h2b_status
    row["score_reasons"] = __import__(
        "automation.job_scoring",
        fromlist=["get_score_reasons"],
    ).get_score_reasons(row)
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

    for search_term in resolve_search_terms(search):
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

                row = extract_job(
                    page,
                    url,
                    job_data,
                )

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
            "Se não informado, usa uma lista estratégica de termos H-2B/Hospitality/Warehouse."
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
