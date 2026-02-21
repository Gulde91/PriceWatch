import tempfile
import unittest
from pathlib import Path

from pricewatch import (
    JsonStore,
    _format_price_change,
    _normalize_price,
    build_daily_report,
    extract_price,
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
        self.assertEqual(_format_price_change(None, 100.0), "ingen sammenligning (første måling)")
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


if __name__ == "__main__":
    unittest.main()
