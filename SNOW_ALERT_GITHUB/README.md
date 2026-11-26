# SNOW ALERT – GitHub Actions

Cloudová varianta Telegram bota. Nepotřebuje vlastní počítač ani VPS.
GitHub Actions spouští krátkou kontrolu každých 10 minut.

## Co projekt dělá
- Kontroluje hodinovou předpověď sněžení v Jičíně, Vrchlabí a Špindlerově Mlýně.
- Posílá upozornění do Telegramu při předpovědi sněžení 3–12 hodin dopředu.
- Zpracovává příkazy `/start`, `/status`, `/forecast`, `/cameras` a `/help`.
- Uchovává registraci Telegram chatu a historii odeslaných upozornění v SQLite.
- Stav SQLite obnovuje mezi běhy pomocí GitHub Actions cache.

## 1. Nahrání na GitHub
Nahraj obsah tohoto ZIPu do kořenové složky repozitáře `SNOW_REPORT`.
Musí vzniknout například:
- `.github/workflows/snow-alert.yml`
- `main.py`
- `requirements.txt`
- `cameras.json`

V GitHubu použij **Add file → Upload files** a nahraj soubory i složku `.github/workflows`.

## 2. Bezpečné vložení Telegram tokenu
1. Otevři repozitář `SNOW_REPORT`.
2. Klikni **Settings → Secrets and variables → Actions**.
3. Klikni **New repository secret**.
4. Name: `TELEGRAM_TOKEN`
5. Secret: vlož token od BotFather.
6. Klikni **Add secret**.

Token nikdy nevkládej do `main.py`, `README.md` ani do běžného souboru repozitáře.

## 3. Zapnutí a test
1. Otevři záložku **Actions**.
2. Pokud GitHub zobrazí tlačítko **I understand my workflows, go ahead and enable them**, potvrď ho.
3. Vlevo vyber workflow **SNOW ALERT**.
4. Klikni **Run workflow → Run workflow**.
5. Otevři běh a zkontroluj, zda krok **Spustit kontrolu** proběhl zeleně.
6. V Telegramu otevři svého bota a pošli mu `/start`.

Naplánované spuštění pak probíhá každých 10 minut. GitHub negarantuje přesnou minutu; plánované běhy mohou mít zpoždění.

## Důležité omezení GitHub Free
U soukromých repozitářů jsou GitHub-hosted Actions omezené měsíčními minutami. Desetiminutový interval znamená přibližně 4 320 spuštění za 30 dní; pokud každý běh zabere alespoň jednu účtovanou minutu, překročí to standardní bezplatný limit 2 000 minut.
Veřejné repozitáře mají pro standardní GitHub-hosted runners neomezené minuty, ale jejich zdrojový kód je veřejný. Token zůstává chráněný v Secrets. Zvaž tedy, zda chceš mít repozitář veřejný, nebo snížit frekvenci například na 30 minut pro soukromý repozitář. Před změnou viditelnosti si ověř aktuální limity ve svém GitHub účtu.

## Kamery – důležité
`cameras.json` zatím obsahuje kandidátní silniční kamery, ale přímé URL obrázků jsou prázdné.
Bot proto zatím neumí stahovat jejich snímky. Až budou ověřené veřejné přímé JPEG/PNG adresy, lze je doplnit.
Tato verze kontroluje dostupnost snímku, nikoli automaticky rozpoznává sníh na vozovce.

## Jak funguje stav mezi běhy
SQLite databáze se ukládá do GitHub Actions cache. Cache je vhodná pro tento bezplatný prototyp, ale není garantované trvalé úložiště; při jejím ztracení může bot zapomenout registraci chatu nebo historii upozornění. V takovém případě pošli znovu `/start`. Cache může být odstraněna také při dlouhé neaktivitě.

## Použitá data
Počasí: Open-Meteo Forecast API. Předpověď ani údaj modelu o aktuálním sněžení nepotvrzuje stav ani sjízdnost vozovky.
