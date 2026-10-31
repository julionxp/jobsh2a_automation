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

    if args.send:
        print("\n>>> EXTRAÇÃO CONCLUÍDA. ENVIANDO EMAILS AUTORIZADOS...")
    else:
        print("\n>>> EXTRAÇÃO CONCLUÍDA. MODO PREVIEW: nenhum email será enviado.")
    asyncio.run(send_pending_emails(send=args.send))


if __name__ == "__main__":
    main()
