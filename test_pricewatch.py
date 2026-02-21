import tempfile
import unittest
from pathlib import Path

from pricewatch import JsonStore, _normalize_price, extract_price, should_alert


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


if __name__ == "__main__":
    unittest.main()
