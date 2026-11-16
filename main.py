import asyncio
import os

from automation.jobs_automation import parse_args, run, sync_playwright
from automation.send_pending_emails import send_pending_emails


def main() -> None:
    args = parse_args()
    if not args.headless and not os.environ.get("DISPLAY"):
        args.headless = True

    with sync_playwright() as playwright:
        run(
            playwright=playwright,
            search=args.search,
            begin_after=args.begin_after,
            headless=args.headless,
        )

    print("\n>>> EXTRAÇÃO CONCLUÍDA. INICIANDO ENVIO DE EMAILS...")
    asyncio.run(send_pending_emails(send=True))


if __name__ == "__main__":
    main()
