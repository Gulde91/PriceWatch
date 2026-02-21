# PriceWatch

Simpelt internt Python-script (pricerunner-style) til at overvåge priser på specifikke links.

Løsningen matcher dine krav:
- **Manuel oprettelse** af varer.
- **Samme vare kan have flere links** (gruppering).
- **Pris gemmes ved hver kørsel** i en simpel **JSON tekstfil**.
- **Alarm ved hvert prisfald** (med cooldown for støjfilter).
- **Daglig kørsel** som standard i `watch`.
- **Email-notifikationer** via SMTP.

## Datafil

Scriptet gemmer alt i `pricewatch_data.json` i projektmappen.

## Kom i gang

```bash
# 1) Opret produkt-gruppe
python3 pricewatch.py add-product --name "Danish Endurance merinostrømper"

# 2) Tilføj et eller flere links til samme produkt
python3 pricewatch.py add-link --product-id 1 --url "https://danishendurance.com/da/products/classic-merinould-vandrestroemper?variant=34364359475259"
python3 pricewatch.py add-link --product-id 1 --url "https://www.spejdersport.dk/asivik-hiker-jr-110-140-boernesovepose-ny"

# 3) Se opsætning
python3 pricewatch.py list

# 4) Kør ét check nu
python3 pricewatch.py check

# 5) Se historik
python3 pricewatch.py history --limit 20
```

## Daglig drift på Raspberry Pi

Kør dagligt i loop (default er 1440 min = 1 dag):

```bash
python3 pricewatch.py watch
```

Alternativt anbefales cron én gang i døgnet.

## Email-notifikation

Ved prisfald kan scriptet sende mail:

```bash
python3 pricewatch.py check \
  --email "dig@example.com" \
  --smtp-host "smtp.gmail.com" \
  --smtp-port 587 \
  --smtp-user "dig@example.com" \
  --smtp-password "app-password"
```

## Test

```bash
python3 -m unittest -v
```
