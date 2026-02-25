#!/usr/bin/env python3
"""Send PriceWatch output as email.

Configuration is loaded from environment variables and/or an untracked
`send_mail.local.json` file (see `send_mail.local.example.json`).
"""

import json
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path
from subprocess import check_output

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
DEFAULT_PROJECT_DIR = Path("/home/alex/PriceWatch")
DEFAULT_PYTHON_BIN = "/usr/bin/python3"
LOCAL_CONFIG_PATH = Path(__file__).with_name("send_mail.local.json")


class ConfigError(RuntimeError):
    """Raised when required config values are missing."""


def _load_local_config() -> dict[str, str]:
    if not LOCAL_CONFIG_PATH.exists():
        return {}

    with LOCAL_CONFIG_PATH.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if not isinstance(data, dict):
        raise ConfigError("send_mail.local.json skal indeholde et JSON-objekt.")

    return {str(key): str(value) for key, value in data.items()}


def _get_setting(local_config: dict[str, str], env_name: str, *, required: bool = False, default: str | None = None) -> str:
    value = os.getenv(env_name)
    if value is None:
        value = local_config.get(env_name, default)

    if required and (value is None or not str(value).strip()):
        raise ConfigError(f"Manglende konfiguration: {env_name}")

    return "" if value is None else str(value)


def main() -> None:
    local_config = _load_local_config()

    sender = _get_setting(local_config, "PRICEWATCH_SENDER", required=True)
    app_password = _get_setting(local_config, "PRICEWATCH_APP_PASSWORD", required=True)
    recipient = _get_setting(local_config, "PRICEWATCH_RECIPIENT", required=True)
    project_dir = Path(_get_setting(local_config, "PRICEWATCH_PROJECT_DIR", default=str(DEFAULT_PROJECT_DIR)))
    python_bin = _get_setting(local_config, "PRICEWATCH_PYTHON_BIN", default=DEFAULT_PYTHON_BIN)

    output = check_output(
        [
            python_bin,
            str(project_dir / "pricewatch.py"),
            "check",
        ],
        text=True,
    )

    if not output.strip():
        return

    msg = EmailMessage()
    msg["Subject"] = "PriceWatch"
    msg["From"] = sender
    msg["To"] = recipient
    msg.set_content(output)

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.login(sender, app_password)
        smtp.send_message(msg)


if __name__ == "__main__":
    main()
