# PriceWatch

Simpelt internt Python-script (pricerunner-style) til at overvåge priser på specifikke links.

Løsningen matcher dine krav:
- **Manuel oprettelse** af varer.
- **Samme vare kan have flere links** (gruppering).
- **Pris gemmes ved hver kørsel** i en simpel **JSON tekstfil**.
- **Alarm ved hvert prisfald** (med cooldown for støjfilter).
- **Daglig kørsel** som standard i `watch`.
- **Daglig email-rapport** via SMTP med pris i dag + ændring ift. i går.

## Vurdering og forbedringer

Efter gennemgang af kode + dokumentation er disse forbedringer lavet:
- Sammenligning i daglig email er nu eksplicit mod **seneste pris fra en tidligere dag** (ikke en ekstra kørsel samme dag).
- Robusthed ved datafil: ugyldig JSON flyttes til `*.corrupt`, og scriptet starter videre med en ren datafil.
- Bedre CLI-fejlbesked ved `add-link`, hvis produkt-id ikke findes eller URL allerede eksisterer.

## Datafil

Scriptet gemmer kun overblik over produkter/links i `pricewatch_data.json` i projektmappen.

Prishistorik gemmes separat som tekstfiler i mappen `price_history/` (én fil per produkt, fx `price_history/product_1.txt`).

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

### Kør som cron job kl. 02:00

Hvis din Raspberry Pi viser:
- projektsti: `/home/alex/PriceWatch`
- python: `/usr/bin/python3`

så skal din cron-linje være:

```cron
0 2 * * * cd /home/alex/PriceWatch && /usr/bin/python3 pricewatch.py check >> /home/alex/PriceWatch/cron.log 2>&1
```

Du har allerede et andet job kl. 03:00, og det er helt fint — cron kan sagtens have begge linjer.

Eksempel på `crontab -e` med begge jobs:

```cron
0 2 * * * cd /home/alex/PriceWatch && /usr/bin/python3 pricewatch.py check >> /home/alex/PriceWatch/cron.log 2>&1
0 3 * * * /usr/bin/python3 /home/alex/funny_dates/send_mail.py
```

Hvis du bruger `send_mail.py` fra dette repo, så undgå at lægge credentials i selve scriptet.
Brug i stedet en **lokal** fil `send_mail.local.json` (som er ignoreret af git):

```bash
cp send_mail.local.example.json send_mail.local.json
```

Udfyld derefter filen med dine egne værdier på Pi'en.

`send_mail.py` læser følgende nøgler (miljøvariabler har forrang):
- `PRICEWATCH_SENDER`
- `PRICEWATCH_APP_PASSWORD`
- `PRICEWATCH_RECIPIENT`
- `PRICEWATCH_PROJECT_DIR` (valgfri, default: `/home/alex/PriceWatch`)
- `PRICEWATCH_PYTHON_BIN` (valgfri, default: `/usr/bin/python3`)

Efter du har gemt, verificér med:

```bash
crontab -l
```

Tip: hvis du bruger mail fra PriceWatch, kan du erstatte `check`-delen med hele kommandoen inkl. SMTP-parametre.

## Email-notifikation

Scriptet sender en daglig mail (når SMTP-parametre gives) med dagens pris og ændring ift. dagen før for hvert link:

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
