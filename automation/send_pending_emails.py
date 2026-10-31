import argparse
import asyncio
import os
from datetime import datetime, time

from sqlalchemy import func, select

from automation.ia_send_email import (
    generate_email_with_retry,
    get_gmail_service,
    identify_job_category,
    send_email,
)
from core.database import DBBaseModel, Session, engine
from models.email_send_model import EmailSendModel
from models.jobs_automation_model import JobAutomationModel


async def send_pending_emails(send: bool) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(DBBaseModel.metadata.create_all)

    daily_limit = int(os.getenv("DAILY_EMAIL_LIMIT", "400"))
    today_start = datetime.combine(datetime.now().date(), time.min)
    gmail = get_gmail_service() if send else None

    async with Session() as session:
        sent_today = await session.scalar(
            select(func.count(EmailSendModel.id)).where(
                EmailSendModel.sent_at >= today_start,
            )
        ) or 0
        remaining = max(daily_limit - sent_today, 0)
        jobs = (await session.scalars(
            select(JobAutomationModel).where(
                JobAutomationModel.emails.is_not(None),
                JobAutomationModel.job_score.is_not(None),
                JobAutomationModel.job_score >= 40,
            ).order_by(JobAutomationModel.job_score.desc(), JobAutomationModel.id.desc())
        )).all()

        retryable_statuses = {"PENDING", "AI_ERROR"}

        if not send:
            print("PREVIEW: nenhum email será gerado ou enviado.")

        sent_count = 0
        for job in jobs:
            for recipient in {
                email.strip()
                for email in (job.emails or "").split(";")
                if email.strip()
            }:
                if sent_count >= remaining:
                    break

                existing = await session.scalar(
                    select(EmailSendModel).where(
                        EmailSendModel.job_id == job.id,
                        EmailSendModel.recipient == recipient,
                    )
                )
                if existing and existing.sent_at:
                    continue
                if existing and existing.status not in retryable_statuses:
                    continue

                if not send:
                    print(f"PENDENTE: {recipient} | {job.title} | score={job.job_score} | {job.priority}")
                    continue

                record = existing or EmailSendModel(
                    job_id=job.id,
                    recipient=recipient,
                )
                record.status = "PENDING"
                record.error = None
                session.add(record)
                await session.commit()

                try:
                    subject, body = generate_email_with_retry(job.title, job.description)
                    job_category = job.job_category or identify_job_category(
                        job.title,
                        job.description,
                    )
                    send_email(gmail, recipient, subject, body, job_category)
                    record.status = "SENT"
                    record.sent_at = datetime.utcnow()
                    record.last_contact_at = record.sent_at
                    record.error = None
                    session.add(record)
                    await session.commit()
                    sent_count += 1
                    print(f"Enviado: {recipient} | {job.title} | score={job.job_score} | {job.priority}")
                except Exception as error:
                    record.status = "AI_ERROR"
                    record.error = str(error)[:2000]
                    session.add(record)
                    await session.commit()
                    print(f"Erro de IA/envio: {recipient} | {job.title} | {error}")

            if sent_count >= remaining:
                break

        print(f"Enviados nesta execução: {sent_count}")
        print(f"Limite diário: {daily_limit}; já enviados hoje: {sent_today}")


async def send_test_email(recipient: str) -> None:
    """Envia uma única vaga para o endereço de teste sem registrá-la como enviada."""
    async with engine.begin() as connection:
        await connection.run_sync(DBBaseModel.metadata.create_all)

    async with Session() as session:
        job = await session.scalar(
            select(JobAutomationModel).where(
                JobAutomationModel.emails.is_not(None),
                JobAutomationModel.job_score.is_not(None),
                JobAutomationModel.job_score >= 40,
            ).order_by(JobAutomationModel.job_score.desc(), JobAutomationModel.id.desc()).limit(1)
        )

    if job is None:
        raise RuntimeError("Nenhuma vaga com email foi encontrada no banco.")

    subject, body = generate_email_with_retry(job.title, job.description)
    job_category = job.job_category or identify_job_category(
        job.title,
        job.description,
    )
    send_email(get_gmail_service(), recipient, subject, body, job_category)
    print(f"Email de teste enviado para {recipient}: {job.title}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Envia candidaturas pendentes.")
    parser.add_argument(
        "--send",
        action="store_true",
        help="Envia de verdade; sem esta opção apenas mostra pendências.",
    )
    parser.add_argument(
        "--test-recipient",
        help="Envia uma única vaga para este email sem marcá-la como enviada.",
    )
    args = parser.parse_args()
    if args.test_recipient:
        asyncio.run(send_test_email(args.test_recipient))
    else:
        asyncio.run(send_pending_emails(send=args.send))
