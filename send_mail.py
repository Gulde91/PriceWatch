#!/usr/bin/env python3
"""Send PriceWatch output as email (funny_dates-style wrapper)."""

import smtplib
from email.message import EmailMessage
from pathlib import Path
from subprocess import check_output

SENDER = "min_mail@gmail.com"
APP_PASSWORD = "app_kode"
RECIPIENT = "min_mail@gmail.com"
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
PROJECT_DIR = Path("/home/alex/PriceWatch")
PYTHON_BIN = "/usr/bin/python3"


def main() -> None:
    output = check_output(
        [
            PYTHON_BIN,
            str(PROJECT_DIR / "pricewatch.py"),
            "check",
        ],
        text=True,
    )

    if not output.strip():
        return

    msg = EmailMessage()
    msg["Subject"] = "PriceWatch"
    msg["From"] = SENDER
    msg["To"] = RECIPIENT
    msg.set_content(output)

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.login(SENDER, APP_PASSWORD)
        smtp.send_message(msg)


if __name__ == "__main__":
    main()
