# PriceWatch

Et simpelt internt værktøj (MVP) til at overvåge priser på specifikke produktlinks.

## Features (MVP)
- Tilføj produkter manuelt med navn + URL.
- Gem prishistorik i SQLite.
- Tjek priser én gang (`check`) eller løbende (`watch`).
- Giv alarm ved prisfald eller når målpris rammes.
- Cooldown på alarmer (default: max 1 alarm per produkt per 24 timer).

## Kom i gang

```bash
python3 pricewatch.py add --name "iPhone 15" --url "https://example.com/product" --target 6999
python3 pricewatch.py list
python3 pricewatch.py check
python3 pricewatch.py history --limit 10
```

Løbende overvågning (hver time):

```bash
python3 pricewatch.py watch --interval-min 60
```

## Noter
- Prisudtræk er generisk og virker bedst på sider med `meta`-price, JSON-LD eller tydelig pristekst.
- Hvis en side ændrer HTML eller blokerer scraping, logges det som fejl i historikken.
- Database-filen oprettes som `pricewatch.db` i projektmappen.

## Test

```bash
python3 -m unittest -v
```
