# ADR 0007: Statystyki API czytane z martów

Status: zaakceptowana · Data: 2026-11-12 · Zmienia częściowo: ADR 0003, ADR 0005

## Kontekst

Po etapie 2 te same liczby (odsłuchy na dzień, top artyści) były liczone w dwóch miejscach:
w API (zapytania na tabelach `public`) i w pipeline'ie (marts). Dwie implementacje tej samej
logiki mogą się rozjechać. Marts są też szybsze dla dużych danych, bo są już zagregowane.
Mają jednak ziarno 1 dnia i są aktualne tylko do ostatniego uruchomienia pipeline'u.

## Decyzja

- Wszystkie statystyki (`/stats/*` i `/listeners/{id}/summary`) czytają marts.
  Katalog i lista odsłuchów (`/listening-events`) nadal czytają `public`.
- Nowy mart **`marts.listener_track_daily`**: jeden wiersz na (dzień UTC, słuchacz, utwór).
  Takie ziarno jest potrzebne, bo **liczby unikalnych wartości nie są addytywne**: utwór
  słuchany w poniedziałek i we wtorek to 1 unikalny utwór, a suma dziennych liczb dałaby 2.
  Dzięki `track_id` w każdym wierszu policzymy `count(DISTINCT track_id)` dla dowolnego okna.
- Nazwy utworów, artystów i gatunków bierzemy z katalogu (`public`), a liczby z martu.
- **Okno musi składać się z pełnych dni UTC**: `from` i `to` muszą być północą UTC
  (`2026-01-01` lub `2026-01-01T00:00:00Z`). Inaczej `422 invalid_time_window`.
  Reguła półotwartego okna z ADR 0003 zostaje (`to` wyłącznie).
- Każda odpowiedź ma pole **`data_as_of`**: czas zbudowania martów (`marts.build_info`).
- Gdy pipeline nie został jeszcze uruchomiony, statystyki zwracają
  `503 marts_not_ready` z podpowiedzią `python -m pipeline run`.
- Tabele martów są opisane w `app/marts.py` w osobnym `MetaData`, a nie w modelach:
  tworzy je pipeline, nie Alembic.

## Konsekwencje

- Zmiana kontraktu API: okna z godzinami (np. `from=2026-01-01T12:00`) nie są już przyjmowane.
- Odsłuchy zaimportowane przez `/listening-events/bulk` pojawiają się w statystykach dopiero
  po kolejnym uruchomieniu pipeline'u. Klient widzi to po `data_as_of`.
- Przebudowa martów blokuje je na czas transakcji. Długa transakcja czytająca marts blokuje
  z kolei przebudowę; dlatego każde żądanie API zamyka swoją sesję (i transakcję) od razu.
- Definicje kolumn martów są w dwóch miejscach (`pipeline/sql/marts.sql` i `app/marts.py`).
  Rozjazd wykryją testy statystyk, które budują marts z prawdziwego SQL.
