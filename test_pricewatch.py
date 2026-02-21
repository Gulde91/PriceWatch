import unittest

from pricewatch import _normalize_price, extract_price


class PriceParsingTests(unittest.TestCase):
    def test_normalize_danish_price(self):
        self.assertEqual(_normalize_price("1.299,95 kr"), 1299.95)

    def test_extract_from_meta(self):
        html = '<meta itemprop="price" content="4999.00">'
        self.assertEqual(extract_price(html), 4999.0)

    def test_extract_prefers_lowest_candidate(self):
        html = 'Før 1.299,00 kr Nu 999,00 kr'
        self.assertEqual(extract_price(html), 999.0)


if __name__ == "__main__":
    unittest.main()
