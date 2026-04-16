#!/usr/bin/env python3
"""PriceWatch - simpelt link-baseret prisovervågning med JSON-lagring."""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import smtplib
import time
import urllib.error
import urllib.request
import urllib.parse
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = Path("pricewatch_data.json")
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "da-DK,da;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


@dataclass
class Product:
    id: int
    name: str
    created_at: str


@dataclass
class ProductLink:
    id: int
    product_id: int
    url: str
    created_at: str


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


class JsonStore:
    def __init__(self, path: Path):
        self.path = path
        self.history = ProductHistoryStore(self.path.parent / "price_history")
        self.data = self._load()

    def _empty(self) -> dict[str, Any]:
        return {
            "products": [],
            "links": [],
            "meta": {"next_product_id": 1, "next_link_id": 1},
        }

    def _normalize_loaded(self, raw: dict[str, Any]) -> dict[str, Any]:
        data = self._empty()
        data["products"] = list(raw.get("products", []))
        data["links"] = list(raw.get("links", []))
        raw_meta = raw.get("meta", {}) if isinstance(raw.get("meta", {}), dict) else {}
        data["meta"]["next_product_id"] = int(raw_meta.get("next_product_id", 1))
        data["meta"]["next_link_id"] = int(raw_meta.get("next_link_id", 1))
        return data

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("JSON root must be object")
            return self._normalize_loaded(raw)
        except Exception:
            backup = self.path.with_suffix(self.path.suffix + ".corrupt")
            self.path.replace(backup)
            print(f"⚠️  Datafil var ugyldig JSON. Backup gemt som {backup.name}. Ny fil oprettes.")
            return self._empty()

    def save(self) -> None:
        self.path.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")

    def add_product(self, name: str) -> Product:
        pid = int(self.data["meta"]["next_product_id"])
        self.data["meta"]["next_product_id"] = pid + 1
        item = {"id": pid, "name": name, "created_at": utc_now(), "last_alert_at": None}
        self.data["products"].append(item)
        self.save()
        return Product(id=item["id"], name=item["name"], created_at=item["created_at"])

    def add_link(self, product_id: int, url: str) -> ProductLink:
        if not any(p["id"] == product_id for p in self.data["products"]):
            raise ValueError(f"Produkt med id={product_id} findes ikke")
        if any(l["url"] == url for l in self.data["links"]):
            raise ValueError("Link findes allerede")
        lid = int(self.data["meta"]["next_link_id"])
        self.data["meta"]["next_link_id"] = lid + 1
        item = {"id": lid, "product_id": product_id, "url": url, "created_at": utc_now()}
        self.data["links"].append(item)
        self.save()
        return ProductLink(id=item["id"], product_id=item["product_id"], url=item["url"], created_at=item["created_at"])

    def remove_product(self, product_id: int) -> tuple[dict[str, Any], int]:
        product = self.product_by_id(product_id)
        if product is None:
            raise ValueError(f"Produkt med id={product_id} findes ikke")
        removed_links = [l for l in self.data["links"] if l["product_id"] == product_id]
        self.data["products"] = [p for p in self.data["products"] if p["id"] != product_id]
        self.data["links"] = [l for l in self.data["links"] if l["product_id"] != product_id]
        self.save()
        return product, len(removed_links)

    def products(self) -> list[dict[str, Any]]:
        return list(self.data["products"])

    def links_for_product(self, product_id: int) -> list[dict[str, Any]]:
        return [l for l in self.data["links"] if l["product_id"] == product_id]

    def save_check(
        self,
        product_id: int,
        link_id: int,
        url: str,
        status: str,
        price: float | None,
        message: str | None = None,
        checked_at: str | None = None,
    ) -> str:
        checked_at = checked_at or utc_now()
        product = self.product_by_id(product_id)
        product_name = str(product["name"]) if product else f"product_{product_id}"
        self.history.append(
            product_id=product_id,
            product_name=product_name,
            checked_at=checked_at,
            link_id=link_id,
            url=url,
            status=status,
            price=price,
            message=message,
        )
        return checked_at

    def previous_ok_price(self, link_id: int) -> float | None:
        product_id = self.product_id_for_link(link_id)
        ok_rows = [
            c
            for c in self.history.read_all()
            if c["status"] == "ok"
            and c["price"] is not None
            and (
                c.get("link_id") == link_id
                or (c.get("link_id") is None and (product_id is None or c["product_id"] == product_id))
            )
        ]
        if len(ok_rows) < 2:
            return None
        return float(ok_rows[-2]["price"])

    def previous_ok_price_before_date(self, link_id: int, current_checked_at: str) -> float | None:
        current_date = dt.datetime.fromisoformat(current_checked_at).date()
        product_id = self.product_id_for_link(link_id)
        best: float | None = None
        best_dt: dt.datetime | None = None
        for row in self.history.read_all():
            same_link = row.get("link_id") == link_id
            same_product_row = row.get("link_id") is None and (product_id is None or row.get("product_id") == product_id)
            if (not same_link and not same_product_row) or row.get("status") != "ok" or row.get("price") is None:
                continue
            checked_at_raw = row.get("checked_at")
            if not isinstance(checked_at_raw, str):
                continue
            checked_at = dt.datetime.fromisoformat(checked_at_raw)
            if checked_at.date() >= current_date:
                continue
            if best_dt is None or checked_at > best_dt:
                best_dt = checked_at
                best = float(row["price"])
        return best

    def product_id_for_link(self, link_id: int) -> int | None:
        for link in self.data["links"]:
            if link["id"] == link_id:
                return int(link["product_id"])
        return None

    def mark_alert_sent(self, product_id: int) -> None:
        for p in self.data["products"]:
            if p["id"] == product_id:
                p["last_alert_at"] = utc_now()
                self.save()
                return

    def product_by_id(self, product_id: int) -> dict[str, Any] | None:
        for p in self.data["products"]:
            if p["id"] == product_id:
                return p
        return None



class ProductHistoryStore:
    def __init__(self, directory: Path):
        self.directory = directory

    def _slugify_product_name(self, product_name: str) -> str:
        slug = re.sub(r"[^\w\-]+", "_", product_name.strip().lower(), flags=re.UNICODE)
        slug = slug.strip("_")
        return slug or "product"

    def _path_for_product(self, product_id: int, product_name: str | None = None) -> Path:
        if product_name:
            slug = self._slugify_product_name(product_name)
            return self.directory / f"{slug}__{product_id}.txt"
        return self.directory / f"product_{product_id}.txt"

    def _find_existing_path_for_product(self, product_id: int, product_name: str | None = None) -> Path:
        preferred = self._path_for_product(product_id, product_name)
        if preferred.exists():
            return preferred

        legacy = self._path_for_product(product_id)
        if legacy.exists():
            return legacy

        matches = sorted(self.directory.glob(f"*__{product_id}.txt")) if self.directory.exists() else []
        if matches:
            return matches[0]
        return preferred

    def append(
        self,
        product_id: int,
        product_name: str,
        checked_at: str,
        link_id: int,
        url: str,
        status: str,
        price: float | None,
        message: str | None,
    ) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        price_text = "" if price is None else f"{price:.6f}"
        safe_message = (message or "").replace("\t", " ").replace("\n", " ").strip()
        line = f"{checked_at}\t{link_id}\t{status}\t{price_text}\t{safe_message}\n"
        path = self._find_existing_path_for_product(product_id, product_name)
        if path.name.startswith("product_"):
            path = self._path_for_product(product_id, product_name)
            if self._path_for_product(product_id).exists():
                self._path_for_product(product_id).replace(path)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)

    def read_product(self, product_id: int, product_name: str | None = None) -> list[dict[str, Any]]:
        path = self._find_existing_path_for_product(product_id, product_name)
        if not path.exists():
            return []

        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            parts = line.split("\t")
            if len(parts) == 2:
                checked_at, price_text = parts
                rows.append(
                    {
                        "checked_at": checked_at,
                        "product_id": product_id,
                        "link_id": None,
                        "url": None,
                        "status": "ok",
                        "price": float(price_text) if price_text else None,
                        "message": None,
                    }
                )
                continue

            if len(parts) >= 6:
                checked_at, link_id, status, price_text, url, message_text = parts[:6]
                rows.append(
                    {
                        "checked_at": checked_at,
                        "product_id": product_id,
                        "link_id": int(link_id),
                        "url": url,
                        "status": status,
                        "price": float(price_text) if price_text else None,
                        "message": message_text or None,
                    }
                )
                continue

            if len(parts) >= 5:
                checked_at, link_id, status, price_text, message_text = parts[:5]
                rows.append(
                    {
                        "checked_at": checked_at,
                        "product_id": product_id,
                        "link_id": int(link_id),
                        "url": None,
                        "status": status,
                        "price": float(price_text) if price_text else None,
                        "message": message_text or None,
                    }
                )
        return rows

    def read_all(self) -> list[dict[str, Any]]:
        if not self.directory.exists():
            return []

        rows: list[dict[str, Any]] = []
        for path in sorted(self.directory.glob("*.txt")):
            match = re.search(r"__(\d+)$", path.stem)
            if match:
                product_id = int(match.group(1))
            elif path.stem.startswith("product_"):
                product_id = int(path.stem.split("_")[-1])
            else:
                continue
            rows.extend(self.read_product(product_id))
        return rows

    def delete_product_history(self, product_id: int) -> int:
        if not self.directory.exists():
            return 0

        deleted = 0
        candidates = [self.directory / f"product_{product_id}.txt", *self.directory.glob(f"*__{product_id}.txt")]
        seen: set[Path] = set()
        for path in candidates:
            if path in seen:
                continue
            seen.add(path)
            if path.exists():
                path.unlink()
                deleted += 1
        return deleted

def fetch_html(url: str, timeout: int = 20, retries: int = 2) -> str:
    req = urllib.request.Request(url, headers=DEFAULT_HEADERS)

    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                body = response.read()
            return body.decode("utf-8", errors="ignore")
        except urllib.error.HTTPError as exc:
            if exc.code == 403:
                if attempt < retries:
                    time.sleep(1 + attempt)
                    continue
                raise urllib.error.URLError(
                    "HTTP 403 (forbidden). Sitet blokerer sandsynligvis automatiske requests; "
                    "prøv et andet link (fx direkte produktside uden bot-beskyttelse)."
                ) from exc
            raise
        except urllib.error.URLError as exc:
            reason = str(getattr(exc, "reason", exc))
            if "403" in reason and "forbidden" in reason.lower():
                if attempt < retries:
                    time.sleep(1 + attempt)
                    continue
                raise urllib.error.URLError(
                    "HTTP 403 (forbidden). Sitet blokerer sandsynligvis automatiske requests; "
                    "prøv et andet link (fx direkte produktside uden bot-beskyttelse)."
                ) from exc
            raise


def is_probably_blocked_page(html: str) -> bool:
    lowered = html.lower()
    block_markers = [
        "captcha",
        "cloudflare",
        "attention required",
        "verify you are human",
        "adgang nægtet",
        "access denied",
        "robot check",
        "bot protection",
    ]
    return any(marker in lowered for marker in block_markers)


def _normalize_price(text: str) -> float | None:
    cleaned = text.strip().replace("\xa0", " ")
    cleaned = re.sub(r"[^0-9,\. ]", "", cleaned).strip()
    if not cleaned:
        return None
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    else:
        cleaned = cleaned.replace(" ", "")

    try:
        value = float(cleaned)
    except ValueError:
        return None
    return value if value > 0 else None




def _extract_variant_price(html: str, url: str) -> float | None:
    variant_id = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("variant", [None])[0]
    if not variant_id:
        return None

    escaped_variant_id = re.escape(str(variant_id))
    patterns = [
        rf'"id"\s*:\s*{escaped_variant_id}[^{{}}]*?"price"\s*:\s*"?([0-9][0-9\., ]+)"?',
        rf'"variantId"\s*:\s*"?{escaped_variant_id}"?[^{{}}]*?"price"\s*:\s*"?([0-9][0-9\., ]+)"?',
    ]

    for pattern in patterns:
        match = re.search(pattern, html, flags=re.IGNORECASE)
        if not match:
            continue
        value = _normalize_price(match.group(1))
        if value is not None:
            # Shopify JSON bruger ofte "price" i øre/cents
            if value >= 10000 and value.is_integer():
                return value / 100
            return value
    return None


def extract_price(html: str, url: str | None = None) -> float | None:
    if url:
        variant_price = _extract_variant_price(html, url)
        if variant_price is not None:
            return variant_price

    structured_patterns = [
        r'<meta[^>]+property=["\']product:price:amount["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+itemprop=["\']price["\'][^>]+content=["\']([^"\']+)["\']',
        r'"offers"\s*:\s*\{[^{}]*?"price"\s*:\s*"?([0-9][0-9\., ]+)"?',
        r'"price"\s*:\s*"?([0-9][0-9\., ]+)"?',
    ]

    for pattern in structured_patterns:
        for match in re.finditer(pattern, html, flags=re.IGNORECASE):
            candidate = _normalize_price(match.group(1))
            if candidate is not None:
                return candidate

    now_price_match = re.search(
        r'før\s*([0-9]{1,3}(?:[\. ]?[0-9]{3})*(?:,[0-9]{2})?)\s*(?:kr\.?|DKK|€|EUR|\$)[^\n]{0,80}?nu\s*([0-9]{1,3}(?:[\. ]?[0-9]{3})*(?:,[0-9]{2})?)\s*(?:kr\.?|DKK|€|EUR|\$)',
        html,
        flags=re.IGNORECASE,
    )
    if now_price_match:
        now_price = _normalize_price(now_price_match.group(2))
        if now_price is not None:
            return now_price

    fallback_pattern = r'([0-9]{1,3}(?:[\. ]?[0-9]{3})*(?:,[0-9]{2})?)\s*(?:kr\.?|DKK|€|EUR|\$)'
    for match in re.finditer(fallback_pattern, html, flags=re.IGNORECASE):
        candidate = _normalize_price(match.group(1))
        if candidate is not None:
            return candidate

    return None


def should_alert(last_alert_at: str | None, cooldown_h: int, previous_price: float | None, new_price: float) -> bool:
    if previous_price is None or new_price >= previous_price:
        return False

    if last_alert_at:
        last = dt.datetime.fromisoformat(last_alert_at)
        if dt.datetime.now(dt.UTC) - last < dt.timedelta(hours=cooldown_h):
            return False
    return True


def send_email_alert(smtp_host: str, smtp_port: int, smtp_user: str, smtp_password: str, to_email: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = to_email
    msg.set_content(body)
    msg.add_alternative(report_text_to_html(body), subtype="html")

    with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(msg)


def report_text_to_html(report_text: str) -> str:
    url_pattern = re.compile(r"https?://[^\s]+")
    trailing_url_punctuation = ".,;:!?)]"
    html_lines: list[str] = []

    for line in report_text.splitlines():
        parts: list[str] = []
        last_index = 0
        for match in url_pattern.finditer(line):
            parts.append(html.escape(line[last_index:match.start()]))
            matched_url = match.group(0)
            url = matched_url.rstrip(trailing_url_punctuation)
            trailing_text = matched_url[len(url):]
            parts.append(f'<a href="{html.escape(url, quote=True)}">Åbn link</a>')
            parts.append(html.escape(trailing_text))
            last_index = match.end()
        parts.append(html.escape(line[last_index:]))
        html_lines.append("".join(parts))

    body_html = "<br>\n".join(html_lines)
    return (
        "<html><body>"
        f"<p style=\"font-family:Arial,sans-serif;white-space:pre-wrap;\">{body_html}</p>"
        "</body></html>"
    )


def _format_price_change(previous: float | None, current: float) -> str:
    if previous is None:
        return "ingen sammenligning (ingen tidligere pris fra en tidligere dag)"
    change = current - previous
    if change == 0:
        return f"uændret (0.00 DKK, i går: {previous:.2f} DKK)"
    sign = "+" if change > 0 else ""
    return f"ændring: {sign}{change:.2f} DKK (i går: {previous:.2f} DKK)"


def build_daily_report(check_rows: list[dict[str, Any]]) -> str:
    lines = [
        f"PriceWatch daglig rapport ({dt.datetime.now(dt.UTC).date().isoformat()})",
        "",
    ]
    if not check_rows:
        lines.append("Ingen links blev tjekket i dag.")
        return "\n".join(lines)

    for row in check_rows:
        if row["status"] == "ok":
            lines.append(
                f"- {row['product_name']}\n"
                f"  Link: {row['url']}\n"
                f"  Pris i dag: {row['price']:.2f} DKK\n"
                f"  {row['change_text']}"
            )
        else:
            lines.append(
                f"- {row['product_name']}\n"
                f"  Link: {row['url']}\n"
                f"  Status: FEJL ({row['message']})"
            )
    return "\n".join(lines)


def check_all(
    store: JsonStore,
    cooldown_h: int,
    email: str | None,
    smtp_host: str | None,
    smtp_port: int,
    smtp_user: str | None,
    smtp_password: str | None,
) -> None:
    products = store.products()
    if not products:
        print("Ingen produkter. Tilføj med 'add-product' først.")
        return

    daily_rows: list[dict[str, Any]] = []

    for p in products:
        links = store.links_for_product(p["id"])
        if not links:
            print(f"⚠️  {p['name']} har ingen links")
            continue

        for link in links:
            try:
                html = fetch_html(link["url"])
                if is_probably_blocked_page(html):
                    msg = "Mulig bot-beskyttelse/captcha-side i stedet for produktside"
                    store.save_check(p["id"], link["id"], link["url"], "error", None, msg)
                    print(f"⚠️  Blokeret side opdaget: {p['name']} | {link['url']}")
                    daily_rows.append(
                        {
                            "product_name": p["name"],
                            "url": link["url"],
                            "status": "error",
                            "message": msg,
                        }
                    )
                    continue
                price = extract_price(html, link["url"])
                if price is None:
                    store.save_check(p["id"], link["id"], link["url"], "error", None, "No price found")
                    print(f"⚠️  Ingen pris fundet: {p['name']} | {link['url']}")
                    daily_rows.append(
                        {
                            "product_name": p["name"],
                            "url": link["url"],
                            "status": "error",
                            "message": "No price found",
                        }
                    )
                    continue

                checked_at = store.save_check(p["id"], link["id"], link["url"], "ok", price)
                previous_for_drop = store.previous_ok_price(link["id"])
                previous_for_report = store.previous_ok_price_before_date(link["id"], checked_at)
                print(f"✅ {p['name']} ({link['url']}): {price:.2f} DKK")
                daily_rows.append(
                    {
                        "product_name": p["name"],
                        "url": link["url"],
                        "status": "ok",
                        "price": price,
                        "change_text": _format_price_change(previous_for_report, price),
                    }
                )

                if should_alert(p.get("last_alert_at"), cooldown_h, previous_for_drop, price):
                    text = f"Prisen er faldet for {p['name']}\nLink: {link['url']}\nFør: {previous_for_drop:.2f} DKK\nNu: {price:.2f} DKK"
                    print(f"🔔 {text}")
                    store.mark_alert_sent(p["id"])
            except urllib.error.URLError as exc:
                store.save_check(p["id"], link["id"], link["url"], "error", None, str(exc))
                print(f"❌ Fejl ved hentning: {p['name']} | {exc}")
                daily_rows.append(
                    {
                        "product_name": p["name"],
                        "url": link["url"],
                        "status": "error",
                        "message": str(exc),
                    }
                )

    if email and smtp_host and smtp_user and smtp_password:
        subject = f"PriceWatch daglig rapport ({dt.datetime.now(dt.UTC).date().isoformat()})"
        body = build_daily_report(daily_rows)
        try:
            send_email_alert(smtp_host, smtp_port, smtp_user, smtp_password, email, subject, body)
            print(f"📧 Daglig rapport sendt til {email}")
        except Exception as exc:  # runtime-only smtp errors
            print(f"❌ Kunne ikke sende daglig email: {exc}")


def cmd_add_product(args: argparse.Namespace) -> None:
    store = JsonStore(Path(args.db))
    created = store.add_product(args.name)
    print(f"Tilføjet produkt [{created.id}] {created.name}")


def cmd_add_link(args: argparse.Namespace) -> None:
    store = JsonStore(Path(args.db))
    try:
        link = store.add_link(args.product_id, args.url)
    except ValueError as exc:
        print(f"❌ {exc}")
        return
    print(f"Tilføjet link [{link.id}] til produkt {link.product_id}")


def cmd_list(args: argparse.Namespace) -> None:
    store = JsonStore(Path(args.db))
    products = store.products()
    if not products:
        print("Ingen produkter endnu.")
        return

    for p in products:
        print(f"[{p['id']}] {p['name']}")
        links = store.links_for_product(p["id"])
        if not links:
            print("  - (ingen links)")
        for l in links:
            print(f"  - [{l['id']}] {l['url']}")


def cmd_remove_product(args: argparse.Namespace) -> None:
    store = JsonStore(Path(args.db))
    try:
        product, removed_links_count = store.remove_product(args.product_id)
    except ValueError as exc:
        print(f"❌ {exc}")
        return
    deleted_history_files = store.history.delete_product_history(args.product_id)
    print(
        "Fjernet produkt "
        f"[{product['id']}] {product['name']} "
        f"(links fjernet: {removed_links_count}, historikfiler slettet: {deleted_history_files})"
    )


def cmd_check(args: argparse.Namespace) -> None:
    store = JsonStore(Path(args.db))
    check_all(store, args.cooldown_h, args.email, args.smtp_host, args.smtp_port, args.smtp_user, args.smtp_password)


def cmd_watch(args: argparse.Namespace) -> None:
    while True:
        cmd_check(args)
        print(f"Venter {args.interval_min} minutter...\n")
        time.sleep(args.interval_min * 60)


def cmd_history(args: argparse.Namespace) -> None:
    store = JsonStore(Path(args.db))
    rows = sorted(store.history.read_all(), key=lambda r: r["checked_at"], reverse=True)[: args.limit]
    if not rows:
        print("Ingen historik.")
        return

    for row in rows:
        price_str = f"{row['price']:.2f} DKK" if row["price"] is not None else "-"
        extra = f" - {row['message']}" if row.get("message") else ""
        product = store.product_by_id(row["product_id"])
        product_name = product["name"] if product else f"product_id={row['product_id']}"
        print(f"{row['checked_at']} | {product_name} | link={row['link_id']} | {row['status']} | {price_str}{extra}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PriceWatch (simpel script + tekstfil)")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Path til JSON datafil")

    sub = parser.add_subparsers(dest="command", required=True)

    add_product = sub.add_parser("add-product", help="Tilføj et nyt produkt (gruppe)")
    add_product.add_argument("--name", required=True, help="Produktnavn")
    add_product.set_defaults(func=cmd_add_product)

    add_link = sub.add_parser("add-link", help="Tilføj et link til et eksisterende produkt")
    add_link.add_argument("--product-id", required=True, type=int)
    add_link.add_argument("--url", required=True)
    add_link.set_defaults(func=cmd_add_link)

    remove_product = sub.add_parser("remove-product", help="Fjern et produkt inkl. links og historik")
    remove_product.add_argument("--product-id", required=True, type=int)
    remove_product.set_defaults(func=cmd_remove_product)

    show_list = sub.add_parser("list", help="Vis produkter og links")
    show_list.set_defaults(func=cmd_list)

    check = sub.add_parser("check", help="Kør ét pristjek")
    check.add_argument("--cooldown-h", type=int, default=24)
    check.add_argument("--email", default=None, help="Modtager-email for notifikationer")
    check.add_argument("--smtp-host", default=None)
    check.add_argument("--smtp-port", type=int, default=587)
    check.add_argument("--smtp-user", default=None)
    check.add_argument("--smtp-password", default=None)
    check.set_defaults(func=cmd_check)

    watch = sub.add_parser("watch", help="Kør i loop (default: dagligt)")
    watch.add_argument("--interval-min", type=int, default=1440, help="Minutter mellem checks")
    watch.add_argument("--cooldown-h", type=int, default=24)
    watch.add_argument("--email", default=None)
    watch.add_argument("--smtp-host", default=None)
    watch.add_argument("--smtp-port", type=int, default=587)
    watch.add_argument("--smtp-user", default=None)
    watch.add_argument("--smtp-password", default=None)
    watch.set_defaults(func=cmd_watch)

    history = sub.add_parser("history", help="Vis pris-historik")
    history.add_argument("--limit", type=int, default=20)
    history.set_defaults(func=cmd_history)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
