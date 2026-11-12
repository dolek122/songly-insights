# ADR 0013: Wdrożenie w Dockerze (obraz + docker compose)

Status: zaakceptowana · Data: 2026-11-12

## Kontekst

Etap 4 ma pozwolić uruchomić cały system poza komputerem autora: API, bazę, pipeline
z harmonogramem, monitoring i dashboardy. Projekt nie ma budżetu ani konta w konkretnej
chmurze, a instrukcja ma działać na dowolnym serwerze z Dockerem (np. tani VPS).

## Decyzja

- **Jeden obraz** dla wszystkich usług w Pythonie (API, migracje, pipeline, serwer Prefect).
  Usługi w `docker-compose.yml` różnią się tylko komendą. Mniej do budowania i utrzymania;
  wszystkie usługi zawsze mają tę samą wersję kodu.
- **Dockerfile:** najpierw same zależności (lista czytana z `pyproject.toml`), potem kod.
  Warstwa zależności jest w cache, dopóki nie zmieni się `pyproject.toml`. Kontener działa
  jako zwykły użytkownik (`songly`), nie root.
- **Migracje** to osobna jednorazowa usługa `migrate` (`alembic upgrade head`). API
  i pipeline startują dopiero po jej sukcesie (`service_completed_successfully`), więc
  nigdy nie działają na starym schemacie.
- **Pipeline** działa stale jako `python -m pipeline serve` z harmonogramem cron
  (domyślnie codziennie 03:15 UTC) i zgłasza przebiegi do serwera Prefect z UI na :4200.
- **Profile compose:** `docker compose up -d db` działa jak dotąd (tylko baza do
  developmentu), `docker compose --profile full up -d` uruchamia cały stos.
- **Hasła** pochodzą z `.env` (interpolacja compose); wartości domyślne są tylko do użytku
  lokalnego.
- **CI** buduje obraz przy każdym pushu, a z gałęzi domyślnej publikuje go w GitHub
  Container Registry (`ghcr.io/<właściciel>/songly-insights:latest` i `:sha-…`).
  Serwer pobiera gotowy obraz zamiast budować go sam.
- API działa z **jednym workerem** uvicorna: metryki Prometheusa są w pamięci procesu
  (ADR 0014). Przy tej skali jeden proces wystarcza.

## Konsekwencje

- Wdrożenie na serwer: skopiować repozytorium (lub sam `docker-compose.yml` i `deploy/`),
  ustawić `.env`, `docker compose --profile full up -d`. Brakuje jeszcze: HTTPS (reverse
  proxy, np. Caddy), kopii zapasowych bazy i ograniczenia portów tylko do potrzebnych.
- Obraz ma ok. 0,5 GB, głównie przez Prefect. Osobny, mniejszy obraz dla API byłby możliwy,
  ale kosztem drugiego Dockerfile.
- Skrypty w `docker/initdb` działają tylko przy tworzeniu wolumenu bazy; zmiana haseł na
  istniejącej bazie wymaga ręcznego `ALTER ROLE`.
