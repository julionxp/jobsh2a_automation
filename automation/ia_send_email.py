import base64
import mimetypes
import os
import re
import time
from email.message import EmailMessage
from pathlib import Path

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google import genai
from google.genai.errors import ServerError
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


load_dotenv(override=True)
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
PROJECT_ROOT = Path(__file__).resolve().parents[1]


JOB_CATEGORIES = {
    "ski_resort": (
        "ski resort", "ski instructor", "ski lift", "snow operations",
        "resort operations", "mountain resort",
    ),
    "hotel_resort": (
        "hotel", "motel", "resort", "front desk", "concierge",
        "guest service", "housekeeping", "room attendant", "laundry attendant",
        "janitor", "public area attendant",
    ),
    "housekeeping": (
        "housekeeper", "housekeeping", "maid", "cleaner", "cleaning",
        "laundry", "room attendant", "housekeeping attendant",
    ),
    "restaurant_food_service": (
        "restaurant", "food service", "server", "waiter", "waitress",
        "cook", "kitchen", "dishwasher", "food preparation", "cafe",
        "catering", "banquet", "line cook", "prep cook",
    ),
    "landscaping": (
        "landscaping", "landscaper", "groundskeeper", "garden", "golf course",
        "lawn care", "horticulture", "irrigation",
    ),
    "construction": (
        "construction", "carpenter", "mason", "painter", "laborer",
        "general labor", "framer", "maintenance worker", "site worker",
    ),
    "seafood_processing": (
        "seafood processing", "seafood", "processing plant", "fish processing",
        "shellfish", "canner", "production worker",
    ),
    "amusement_recreation": (
        "amusement", "recreation", "theme park", "camp", "recreation attendant",
        "lifeguard", "park attendant", "outdoor recreation", "trail crew",
    ),
    "maintenance": (
        "maintenance", "maintenance worker", "facility maintenance",
        "building maintenance", "repair", "grounds maintenance",
    ),
    "warehouse": (
        "warehouse", "material handler", "order picker", "picker",
        "packer", "shipping", "receiving", "forklift", "distribution",
        "inventory", "stock clerk",
    ),
    "cleaning": (
        "cleaning", "cleaner", "janitor", "porter", "sanitation",
        "custodial", "building cleaner",
    ),
    "farm_agriculture": (
        "farm", "farmer", "farmworker", "farm worker", "agricultural", "agriculture", "harvest",
        "orchard", "packing house", "packing", "nursery", "greenhouse",
        "livestock", "ranch", "field worker", "crop production",
    ),
}

DOCUMENT_CATEGORY_MAP = {
    "hospitality": "hospitality",
    "ski_resort": "hospitality",
    "hotel_resort": "hospitality",
    "housekeeping": "hospitality",
    "amusement_recreation": "hospitality",
    "food_service": "food_service",
    "restaurant_food_service": "food_service",
    "general_labor": "general_labor",
    "outdoor": "general_labor",
    "landscaping": "general_labor",
    "construction": "general_labor",
    "seafood_processing": "general_labor",
    "farm_agriculture": "general_labor",
    "maintenance": "maintenance",
    "cleaning": "maintenance",
    "warehouse": "warehouse",
}

DOCUMENT_FILE_NAMES = {
    "hospitality": (
        "Julio_Cezar_Resume_Hospitality.pdf",
        "Julio_Cezar_Cover_Letter_Hospitality.pdf",
    ),
    "general_labor": (
        "Julio_Cezar_Resume_General_Labor.pdf",
        "Julio_Cezar_Cover_Letter_General_Labor.pdf",
    ),
    "warehouse": (
        "Julio_Cezar_Resume_Warehouse.pdf",
        "Julio_Cezar_Cover_Letter_Warehouse.pdf",
    ),
    "maintenance": (
        "Julio_Cezar_Resume_Maintenance.pdf",
        "Julio_Cezar_Cover_Letter_Maintenance.pdf",
    ),
    "food_service": (
        "Julio_Cezar_Resume_Food_Service.pdf",
        "Julio_Cezar_Cover_Letter_Food_Service.pdf",
    ),
}


def project_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def identify_job_category(job_title: str, description: str | None) -> str:
    title_text = (job_title or "").casefold()
    description_text = (description or "").casefold()

    # Categorias específicas vêm antes das categorias mais genéricas.
    category_priority = [
        "ski_resort", "housekeeping", "restaurant_food_service",
        "landscaping", "construction", "seafood_processing",
        "amusement_recreation", "maintenance", "warehouse",
        "cleaning", "farm_agriculture", "hotel_resort",
    ]
    scores: dict[str, int] = {}
    for category in category_priority:
        score = 0
        for keyword in JOB_CATEGORIES[category]:
            pattern = rf"(?<!\w){re.escape(keyword)}(?!\w)"
            if re.search(pattern, title_text):
                score += 3
            if re.search(pattern, description_text):
                score += 1
        scores[category] = score

    best_category = max(category_priority, key=lambda category: scores[category])
    if scores[best_category] == 0:
        return "general agricultural or seasonal work"
    return best_category


def select_application_documents(job_category: str | None) -> tuple[Path, Path]:
    normalized_category = (job_category or "").strip().casefold()
    document_category = DOCUMENT_CATEGORY_MAP.get(
        normalized_category,
        "general_labor",
    )
    resume_name, cover_letter_name = DOCUMENT_FILE_NAMES[document_category]

    resume_file = project_path(os.getenv("RESUME_FILE", "")).resolve() if os.getenv("RESUME_FILE") else PROJECT_ROOT / "assets" / "resumes" / resume_name
    cover_letter_file = project_path(os.getenv("COVER_LETTER_FILE", "")).resolve() if os.getenv("COVER_LETTER_FILE") else PROJECT_ROOT / "assets" / "cover_letters" / cover_letter_name
    return resume_file, cover_letter_file




def generate_email(job_title: str, description: str | None) -> tuple[str, str]:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY não configurada no arquivo .env.")

    applicant_name = os.getenv("SENDER_NAME", "Júlio Cezar")
    job_category = identify_job_category(job_title, description)
    employer_name = os.getenv("EMPLOYER_NAME", "Hiring Manager")
    location = os.getenv("LOCATION", "United States")

    prompt = f"""You are writing a short job application email for a real person applying for a H-2A agricultural seasonal job in the United States.

Your goal is to write a natural, simple, professional email that sounds like it was written by a real applicant — NOT by an AI, recruiter, marketing professional, or corporate communications team.

## IMPORTANT STYLE RULES

- Write natural American English.
- Keep the email short: 70–100 words whenever possible.
- Use simple and direct language.
- Sound polite, interested, and confident, but not overly enthusiastic.
- Do not try to "sell" the applicant or describe competencies.
- Do not use corporate, promotional, or overly polished language.
- Do not repeat the job description.
- Do not list several job duties from the posting.
- At most, mention ONE specific detail about the position if it fits naturally.
- Do not use unnecessary adjectives.
- Do not use clichés or generic motivational phrases.
- Do not sound desperate.
- Do not mention sponsorship, immigration problems, financial need, or desperation.
- The applicant is currently based in Brazil. Mention this naturally when relevant.
- The applicant is interested in H-2A agricultural seasonal work in the United States.
- Never invent experience, skills, qualifications, certifications, availability, or personal information that was not provided. Do not claim the employer sponsors or accepts overseas applicants unless the listing explicitly confirms it.
- Never claim the applicant has experience simply because the job description requires it.
- Do not say "I am the perfect candidate", "I would be an excellent fit", or similar phrases.

## PHRASES TO AVOID
Do not use:
  - "I take pride in..."
  - "I look forward to..."
  - "I am thrilled to..."
  - "I am excited to bring my..."
  - "I am passionate about..."
  - "I am confident that..."
  - "I would be honored to..."
  - "I am eager to leverage..."
  - "maintaining pristine..."
  - "providing exceptional..."
  - "contributing to your continued success..."
  - "discuss my application further" (too formal)
  - "actively seeking" + "very interested" (repetitive)

## PREFERRED LANGUAGE
Use simple, direct phrases like:
  - "I am writing to apply for..."
  - "I am currently based in Brazil and looking for seasonal opportunities..."
  - "I am particularly interested in..." (mention job category if relevant)
  - "Please let me know if you need any additional information." (simple closing)

## PERSONALIZATION
Use the job information to understand what position the applicant is applying for.

You may naturally mention ONE relevant detail from the job, but do not copy or paraphrase the job description.

The email should still sound natural if the employer reads it alongside the job posting.

## STRUCTURE
Use this general structure:

1. Greeting: "Dear Hiring Manager,"
2. First paragraph: Clearly state the position the applicant is applying for.
3. Second paragraph: Mention that the applicant is based in Brazil and looking for seasonal opportunities in the United States.
4. Final paragraph: Mention that the resume and cover letter are attached and invite contact if needed.
5. Closing: "Sincerely," followed by the applicant's name.

## OUTPUT RULES

- Return ONLY the email body (no subject line).
- Do not include explanations or commentary.
- Do not use markdown, bullet points, or HTML.
- Do not add placeholders unless the required information is missing.
- Do not exceed 120 words.
- Prefer 70–100 words.
- Use normal paragraph spacing.

## JOB INFORMATION
Job title: {job_title}
Job category: {job_category}
Job description: {description or 'Not provided'}
Location: {location}

## APPLICANT INFORMATION
Name: {applicant_name}
Current location: Brazil
Documents attached: Resume and cover letter
"""

    with genai.Client(api_key=api_key) as client:
        response = client.models.generate_content(
            model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
            contents=prompt,
        )
        body = response.text.strip()

    return f"Application - {job_title}", body


def generate_email_with_retry(job_title: str, description: str | None, max_retries: int = 4):
    """Retry graceful on transient Gemini 503/server failures without blocking the whole automation."""
    last_error = None
    for attempt in range(max_retries):
        try:
            return generate_email(job_title, description)
        except ServerError as exc:
            last_error = exc
            if attempt == max_retries - 1:
                raise

            wait_seconds = 2 ** attempt
            print(
                f"Gemini indisponível para '{job_title}'. "
                f"Tentativa {attempt + 1}/{max_retries}. "
                f"Aguardando {wait_seconds}s..."
            )
            time.sleep(wait_seconds)
        except Exception:
            raise

    if last_error is not None:
        raise last_error


def get_gmail_service():
    credentials_file = project_path(
        os.getenv("GMAIL_CREDENTIALS_FILE", "credentials.json")
    )
    token_file = project_path(
        os.getenv("GMAIL_TOKEN_FILE", "token.json")
    )
    credentials = None

    if token_file.exists():
        credentials = Credentials.from_authorized_user_file(
            str(token_file),
            GMAIL_SCOPES,
        )

    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            if not credentials_file.exists():
                raise FileNotFoundError(
                    f"Arquivo de credenciais Gmail não encontrado: {credentials_file}"
                )
            credentials = InstalledAppFlow.from_client_secrets_file(
                str(credentials_file),
                GMAIL_SCOPES,
            ).run_local_server(port=0)
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(credentials.to_json(), encoding="utf-8")

    return build("gmail", "v1", credentials=credentials)


def send_email(
    service,
    recipient: str,
    subject: str,
    body: str,
    job_category: str | None = None,
) -> None:
    resume_file, cover_letter_file = select_application_documents(job_category)
    if not resume_file.exists():
        raise FileNotFoundError(f"Currículo não encontrado: {resume_file}")
    if not cover_letter_file.exists():
        raise FileNotFoundError(
            f"Cover letter não encontrada: {cover_letter_file}"
        )

    message = EmailMessage()
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)

    for attachment in (resume_file, cover_letter_file):
        content_type, _ = mimetypes.guess_type(attachment.name)
        maintype, subtype = (content_type or "application/pdf").split("/", 1)
        message.add_attachment(
            attachment.read_bytes(),
            maintype=maintype,
            subtype=subtype,
            filename=attachment.name,
        )

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    service.users().messages().send(
        userId="me",
        body={"raw": raw},
    ).execute()
