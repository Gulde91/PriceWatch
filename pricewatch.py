#!/usr/bin/env python3
"""PriceWatch MVP

Simple internal tool to monitor product URLs and alert on price drops.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

DB_PATH = Path("pricewatch.db")
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


@dataclass
class Product:
    id: int
    name: str
    url: str
    target_price: float | None
    last_alert_at: str | None


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            url TEXT NOT NULL UNIQUE,
            target_price REAL,
            created_at TEXT NOT NULL,
            last_alert_at TEXT
        );

        CREATE TABLE IF NOT EXISTS price_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            checked_at TEXT NOT NULL,
            price REAL,
            currency TEXT,
            status TEXT NOT NULL,
            message TEXT,
            FOREIGN KEY (product_id) REFERENCES products(id)
        );
        """
    )
    conn.commit()


def add_product(conn: sqlite3.Connection, name: str, url: str, target_price: float | None) -> None:
    now = dt.datetime.now(dt.UTC).isoformat()
    conn.execute(
        "INSERT INTO products(name, url, target_price, created_at) VALUES(?, ?, ?, ?)",
        (name, url, target_price, now),
    )
    conn.commit()


def list_products(conn: sqlite3.Connection) -> list[Product]:
    rows = conn.execute(
        "SELECT id, name, url, target_price, last_alert_at FROM products ORDER BY id"
    ).fetchall()
    return [Product(**dict(r)) for r in rows]


def fetch_html(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return raw.decode("utf-8", errors="ignore")


def _normalize_price(text: str) -> float | None:
    cleaned = text.strip().replace("\xa0", " ")
    cleaned = re.sub(r"[^0-9,\. ]", "", cleaned)
    cleaned = cleaned.strip()
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
        return float(cleaned)
    except ValueError:
        return None


def extract_price_candidates(html: str) -> Iterable[float]:
    patterns = [
        r'<meta[^>]+property=["\']product:price:amount["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+itemprop=["\']price["\'][^>]+content=["\']([^"\']+)["\']',
        r'"price"\s*:\s*"?([0-9][0-9\., ]+)"?',
        r'([0-9]{1,3}(?:[\. ]?[0-9]{3})*(?:,[0-9]{2})?)\s*(?:kr\.?|DKK|€|EUR|\$)',
    ]
    for pat in patterns:
        for match in re.finditer(pat, html, flags=re.IGNORECASE):
            value = _normalize_price(match.group(1))
            if value is not None and value > 0:
                yield value


def extract_price(html: str) -> float | None:
    candidates = list(extract_price_candidates(html))
    if not candidates:
        return None
    # Prefer the lowest valid value to catch common "current + old" price pages.
    return min(candidates)


def save_check(
    conn: sqlite3.Connection,
    product_id: int,
    status: str,
    price: float | None = None,
    currency: str | None = "DKK",
    message: str | None = None,
) -> None:
    now = dt.datetime.now(dt.UTC).isoformat()
    conn.execute(
        """
        INSERT INTO price_checks(product_id, checked_at, price, currency, status, message)
        VALUES(?, ?, ?, ?, ?, ?)
        """,
        (product_id, now, price, currency, status, message),
    )
    conn.commit()


def last_successful_price(conn: sqlite3.Connection, product_id: int) -> float | None:
    row = conn.execute(
        """
        SELECT price FROM price_checks
        WHERE product_id = ? AND status = 'ok' AND price IS NOT NULL
        ORDER BY id DESC LIMIT 1 OFFSET 1
        """,
        (product_id,),
    ).fetchone()
    return row[0] if row else None


def should_alert(product: Product, new_price: float, previous_price: float | None, cooldown_h: int) -> bool:
    if previous_price is not None and new_price < previous_price:
        pass_drop = True
    else:
        pass_drop = False

    pass_target = product.target_price is not None and new_price <= product.target_price

    if not (pass_drop or pass_target):
        return False

    if product.last_alert_at:
        last = dt.datetime.fromisoformat(product.last_alert_at)
        if dt.datetime.now(dt.UTC) - last < dt.timedelta(hours=cooldown_h):
            return False
    return True


def mark_alert_sent(conn: sqlite3.Connection, product_id: int) -> None:
    now = dt.datetime.now(dt.UTC).isoformat()
    conn.execute("UPDATE products SET last_alert_at = ? WHERE id = ?", (now, product_id))
    conn.commit()


def notify(product: Product, new_price: float, previous_price: float | None) -> None:
    delta = ""
    if previous_price is not None:
        delta = f" (før: {previous_price:.2f} DKK)"
    print(f"🔔 Prisalarm: {product.name} nu {new_price:.2f} DKK{delta} -> {product.url}")


def check_product(conn: sqlite3.Connection, product: Product, cooldown_h: int = 24) -> None:
    try:
        html = fetch_html(product.url)
        price = extract_price(html)
        if price is None:
            save_check(conn, product.id, status="error", message="No price found")
            print(f"⚠️  Ingen pris fundet for {product.name}")
            return

        save_check(conn, product.id, status="ok", price=price)
        prev = last_successful_price(conn, product.id)

        print(f"✅ {product.name}: {price:.2f} DKK")
        if should_alert(product, price, prev, cooldown_h=cooldown_h):
            notify(product, price, prev)
            mark_alert_sent(conn, product.id)

    except urllib.error.URLError as exc:
        save_check(conn, product.id, status="error", message=str(exc))
        print(f"❌ Fejl ved hentning af {product.name}: {exc}")


def cmd_add(args: argparse.Namespace) -> None:
    conn = connect(Path(args.db))
    init_db(conn)
    add_product(conn, args.name, args.url, args.target)
    print("Tilføjet produkt.")


def cmd_list(args: argparse.Namespace) -> None:
    conn = connect(Path(args.db))
    init_db(conn)
    products = list_products(conn)
    if not products:
        print("Ingen produkter endnu.")
        return
    for p in products:
        target = f" mål={p.target_price:.2f} DKK" if p.target_price is not None else ""
        print(f"[{p.id}] {p.name}{target}\n  {p.url}")


def cmd_check(args: argparse.Namespace) -> None:
    conn = connect(Path(args.db))
    init_db(conn)
    products = list_products(conn)
    if not products:
        print("Ingen produkter at tjekke.")
        return
    for p in products:
        check_product(conn, p, cooldown_h=args.cooldown_h)


def cmd_watch(args: argparse.Namespace) -> None:
    while True:
        cmd_check(args)
        print(f"Venter {args.interval_min} minutter...\n")
        time.sleep(args.interval_min * 60)


def cmd_history(args: argparse.Namespace) -> None:
    conn = connect(Path(args.db))
    init_db(conn)
    rows = conn.execute(
        """
        SELECT p.name, c.checked_at, c.price, c.status, c.message
        FROM price_checks c
        JOIN products p ON p.id = c.product_id
        ORDER BY c.id DESC
        LIMIT ?
        """,
        (args.limit,),
    ).fetchall()
    if not rows:
        print("Ingen historik.")
        return
    for r in rows:
        extra = f" - {r['message']}" if r["message"] else ""
        price = f"{r['price']:.2f} DKK" if r["price"] is not None else "-"
        print(f"{r['checked_at']} | {r['name']} | {r['status']} | {price}{extra}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PriceWatch MVP")
    parser.add_argument("--db", default=str(DB_PATH), help="Path to sqlite DB")

    sub = parser.add_subparsers(dest="cmd", required=True)

    add = sub.add_parser("add", help="Tilføj produkt")
    add.add_argument("--name", required=True)
    add.add_argument("--url", required=True)
    add.add_argument("--target", type=float, default=None, help="Målpris")
    add.set_defaults(func=cmd_add)

    lst = sub.add_parser("list", help="Vis produkter")
    lst.set_defaults(func=cmd_list)

    chk = sub.add_parser("check", help="Tjek alle produkter")
    chk.add_argument("--cooldown-h", type=int, default=24)
    chk.set_defaults(func=cmd_check)

    watch = sub.add_parser("watch", help="Kør tjek i loop")
    watch.add_argument("--interval-min", type=int, default=60)
    watch.add_argument("--cooldown-h", type=int, default=24)
    watch.set_defaults(func=cmd_watch)

    hist = sub.add_parser("history", help="Vis historik")
    hist.add_argument("--limit", type=int, default=20)
    hist.set_defaults(func=cmd_history)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
