# ADR 0001: Stos technologiczny API

Status: zaakceptowana · Data: 2026-11-09

## Kontekst

Etap 1 to API do analizy odsłuchów muzyki. Projekt ma być portfolio juniora, więc liczy się
przede wszystkim czytelność kodu i to, że autor potrafi wytłumaczyć każdą jego część.
Kolejne etapy (pipeline danych, warstwy raw/staging/marts) też będą korzystać z PostgreSQL.

## Decyzja

- **FastAPI**: walidacja wejścia przez Pydantic, automatyczna dokumentacja OpenAPI (`/docs`),
  wstrzykiwanie zależności (`Depends`) dla sesji bazy, paginacji i okna czasowego.
- **SQLAlchemy 2.0 w trybie synchronicznym**: prostszy model mentalny niż `async`, a przy tej
  skali (pojedyncze zapytania agregujące) asynchroniczność nic nie daje. FastAPI uruchamia
  synchroniczne endpointy w puli wątków, więc serwer nie jest blokowany.
- **Alembic**: każda zmiana schematu to migracja w repozytorium. Testy budują bazę z migracji,
  a osobny test porównuje modele z migracjami (wykrywa zapomnianą migrację).
- **PostgreSQL 16**: `INSERT ... ON CONFLICT DO NOTHING` (idempotentny import), `timestamptz`,
  funkcje okienkowe i dobre wsparcie dla przyszłych warstw hurtowni danych.
- **Testy na prawdziwym PostgreSQL**, nie na SQLite: zapytania korzystają z funkcji specyficznych
  dla PostgreSQL, a testy mają sprawdzać to samo, co działa produkcyjnie.
- Kod jest podzielony na `routers` (HTTP), `services` (logika i zapytania) i `schemas`
  (kontrakt API). Routery są cienkie, cała logika agregacji jest w `app/services`.

## Konsekwencje

- Do uruchomienia testów potrzebny jest PostgreSQL (`docker compose up -d db`, a w CI kontener
  usługi w GitHub Actions).
- Przy dużym ruchu można później przejść na `async`, ale wymagałoby to zmiany sterownika
  i sesji w całej aplikacji. Na etapie 1 nie ma takiej potrzeby.
