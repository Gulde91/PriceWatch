import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from pricewatch import (
    JsonStore,
    _format_price_change,
    _normalize_price,
    build_daily_report,
    report_text_to_html,
    extract_price,
    fetch_html,
    should_alert,
)


class PriceWatchTests(unittest.TestCase):
    def test_normalize_danish_price(self):
        self.assertEqual(_normalize_price("1.299,95 kr"), 1299.95)

    def test_extract_from_meta(self):
        html = '<meta itemprop="price" content="4999.00">'
        self.assertEqual(extract_price(html), 4999.0)

    def test_extract_prefers_lowest_candidate(self):
        html = 'Før 1.299,00 kr Nu 999,00 kr'
        self.assertEqual(extract_price(html), 999.0)


    def test_extract_variant_price_from_url_query(self):
        html = '\n'.join([
            '{"id":34364359475259,"title":"3-pack","price":"69900"}',
            '{"id":999,"title":"1-pack","price":"25000"}',
        ])
        # URL variant skal vinde over laveste globale kandidat
        self.assertEqual(
            extract_price(html + ' Før 250,00 kr Nu 699,00 kr', 'https://example.com/p?variant=34364359475259'),
            699.0,
        )

    def test_extract_variant_price_handles_decimal_price(self):
        html = '{"variantId":"34364359475259","price":"699.00"}'
        self.assertEqual(extract_price(html, 'https://example.com/p?variant=34364359475259'), 699.0)

    def test_should_alert_on_drop(self):
        self.assertTrue(should_alert(None, 24, 1000.0, 950.0))
        self.assertFalse(should_alert(None, 24, 1000.0, 1000.0))

    def test_can_group_multiple_links_on_same_product(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "data.json"
            store = JsonStore(db)
            product = store.add_product("Sovepose")
            store.add_link(product.id, "https://example.com/a")
            store.add_link(product.id, "https://example.com/b")

            links = store.links_for_product(product.id)
            self.assertEqual(len(links), 2)

    def test_daily_change_text(self):
        self.assertEqual(
            _format_price_change(None, 100.0),
            "ingen sammenligning (ingen tidligere pris fra en tidligere dag)",
        )
        self.assertEqual(_format_price_change(100.0, 100.0), "uændret (0.00 DKK, i går: 100.00 DKK)")
        self.assertEqual(_format_price_change(100.0, 95.0), "ændring: -5.00 DKK (i går: 100.00 DKK)")

    def test_daily_report_contains_price_and_delta(self):
        report = build_daily_report(
            [
                {
                    "product_name": "Sovepose",
                    "url": "https://example.com/a",
                    "status": "ok",
                    "price": 499.0,
                    "change_text": "ændring: -10.00 DKK (i går: 509.00 DKK)",
                }
            ]
        )
        self.assertIn("Pris i dag: 499.00 DKK", report)
        self.assertIn("ændring: -10.00 DKK", report)



    def test_report_text_to_html_replaces_url_with_clickable_link(self):
        html_report = report_text_to_html("Link: https://example.com/a?x=1&y=2")
        self.assertIn('href="https://example.com/a?x=1&amp;y=2"', html_report)
        self.assertIn('>Åbn link<', html_report)

    def test_report_text_to_html_preserves_closing_parenthesis_after_url(self):
        html_report = report_text_to_html("Classic merinould vandrestrømper (https://example.com/a) 390.00 DKK")
        self.assertIn('href="https://example.com/a"', html_report)
        self.assertIn('Åbn link</a>) 390.00 DKK', html_report)

    def test_fetch_html_retries_and_returns_clear_403_message(self):
        with mock.patch("pricewatch.time.sleep"):
            with mock.patch("pricewatch.urllib.request.urlopen", side_effect=urllib.error.HTTPError(
                url="https://example.com",
                code=403,
                msg="Forbidden",
                hdrs=None,
                fp=None,
            )):
                with self.assertRaises(urllib.error.URLError) as exc:
                    fetch_html("https://example.com", retries=1)

        self.assertIn("HTTP 403", str(exc.exception))
        self.assertIn("blokerer", str(exc.exception))

    def test_fetch_html_maps_tunnel_403_to_clear_message(self):
        tunnel_error = urllib.error.URLError("Tunnel connection failed: 403 Forbidden")
        with mock.patch("pricewatch.time.sleep"):
            with mock.patch("pricewatch.urllib.request.urlopen", side_effect=tunnel_error):
                with self.assertRaises(urllib.error.URLError) as exc:
                    fetch_html("https://example.com", retries=1)

        self.assertIn("HTTP 403", str(exc.exception))
        self.assertIn("blokerer", str(exc.exception))

    def test_previous_ok_price_before_date_ignores_same_day_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "data.json"
            store = JsonStore(db)
            store.save_check(1, 1, "https://example.com/a", "ok", 100.0, checked_at="2026-01-10T08:00:00+00:00")
            store.save_check(1, 1, "https://example.com/a", "ok", 95.0, checked_at="2026-01-11T08:00:00+00:00")
            store.save_check(1, 1, "https://example.com/a", "ok", 90.0, checked_at="2026-01-11T14:00:00+00:00")
            previous = store.previous_ok_price_before_date(1, "2026-01-11T14:00:00+00:00")
            self.assertEqual(previous, 100.0)


    def test_save_check_history_file_contains_compact_fields_without_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "data.json"
            store = JsonStore(db)
            product = store.add_product("Sovepose")
            store.save_check(product.id, 2, "https://example.com/a", "ok", 123.45, checked_at="2026-01-10T08:00:00+00:00")

            history_file = Path(tmp) / "price_history" / "sovepose__1.txt"
            line = history_file.read_text(encoding="utf-8").strip()
            self.assertEqual(line, "2026-01-10T08:00:00+00:00\t2\tok\t123.450000")

    def test_error_status_and_message_are_persisted_in_compact_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "data.json"
            store = JsonStore(db)
            product = store.add_product("Sovepose")
            store.save_check(
                product.id,
                2,
                "https://example.com/a",
                "error",
                None,
                message="No price found",
                checked_at="2026-01-10T09:00:00+00:00",
            )

            rows = store.history.read_product(product.id, product.name)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["status"], "error")
            self.assertEqual(rows[0]["message"], "No price found")
            self.assertIsNone(rows[0]["price"])
            self.assertIsNone(rows[0]["url"])

    def test_save_check_writes_separate_product_history_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "data.json"
            store = JsonStore(db)
            product = store.add_product("Sovepose")
            store.save_check(product.id, 2, "https://example.com/a", "ok", 123.45, checked_at="2026-01-10T08:00:00+00:00")

            history_file = Path(tmp) / "price_history" / "sovepose__1.txt"
            self.assertTrue(history_file.exists())
            self.assertIn("2026-01-10T08:00:00+00:00", history_file.read_text(encoding="utf-8"))

    def test_remove_product_removes_product_and_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "data.json"
            store = JsonStore(db)
            product = store.add_product("Sovepose")
            store.add_link(product.id, "https://example.com/a")
            store.add_link(product.id, "https://example.com/b")

            removed_product, removed_links_count = store.remove_product(product.id)

            self.assertEqual(removed_product["name"], "Sovepose")
            self.assertEqual(removed_links_count, 2)
            self.assertEqual(store.products(), [])
            self.assertEqual(store.links_for_product(product.id), [])

    def test_remove_product_history_deletes_history_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "data.json"
            store = JsonStore(db)
            product = store.add_product("Sovepose")
            store.save_check(product.id, 2, "https://example.com/a", "ok", 123.45, checked_at="2026-01-10T08:00:00+00:00")
            history_file = Path(tmp) / "price_history" / "sovepose__1.txt"
            self.assertTrue(history_file.exists())

            deleted_files_count = store.history.delete_product_history(product.id)

            self.assertEqual(deleted_files_count, 1)
            self.assertFalse(history_file.exists())


if __name__ == "__main__":
    unittest.main()
