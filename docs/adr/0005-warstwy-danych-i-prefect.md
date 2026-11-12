# ADR 0005: Warstwy raw → staging → marts i orkiestracja w Prefect

Status: zaakceptowana · Data: 2026-11-12

## Kontekst

Etap 2 dodaje pipeline danych: dane zewnętrzne (MusicBrainz, później ListenBrainz), tabele
gotowe do analityki i testy jakości danych. API z etapu 1 ma działać bez zmian. Potrzebny
jest też orkiestrator, który uruchamia kroki w kolejności, ponawia je po błędzie, loguje
przebieg i pozwala uruchamiać całość według harmonogramu.

## Decyzja

**Warstwy to osobne schematy w tej samej bazie PostgreSQL:**

- **`raw`**: dane zewnętrzne dokładnie tak, jak przyszły (np. cała odpowiedź JSON
  z MusicBrainz w kolumnie `jsonb`), plus metadane: `run_id`, `loaded_at`, adres zapytania.
  Tylko dopisujemy (append-only), nigdy nie zmieniamy ani nie usuwamy. Dzięki temu można
  przebudować wszystko dalej bez ponownego pobierania i widać historię. Tabele `raw` tworzy
  migracja Alembic (`0002`), bo to stały kontrakt na dane wejściowe.
- **`staging`**: widoki, które czyszczą i nazywają kolumny jednolicie, ale nie agregują.
  Np. `staging.musicbrainz_artists` rozpakowuje JSON i bierze najnowszą wersję artysty,
  `staging.listening_events` dodaje dzień w UTC. Tabele API (`public`) czytamy bezpośrednio
  przez widoki staging, bez kopiowania do `raw`: są w tej samej bazie i już mają typy
  i ograniczenia. Gdyby hurtownia była w osobnej bazie, trzeba by je najpierw skopiować.
- **`marts`**: tabele gotowe do analityki (`daily_listener_activity`, `daily_genre_plays`,
  `artist_popularity`). Klucz główny każdej tabeli opisuje jej ziarno („jeden wiersz na dzień
  i słuchacza”).

Staging i marts są w całości wyliczane z SQL w `pipeline/sql/`. Każde uruchomienie robi
`DROP SCHEMA ... CASCADE` i tworzy je od nowa **w jednej transakcji**. PostgreSQL ma
transakcyjne DDL, więc błąd w połowie budowania przywraca poprzednią wersję. Pełna
przebudowa jest prosta i przy obecnej skali (tysiące-miliony wierszy) wystarczająco szybka.

**Testy jakości danych** to zapytania SQL zwracające wiersze łamiące regułę (jak testy dbt):
0 wierszy = test przeszedł. Sprawdzamy źródła przed budowaniem, staging po zbudowaniu i marts
na końcu, m.in. uzgodnienie (suma odsłuchów w marcie = liczba zdarzeń w staging). Poziom
`error` zatrzymuje pipeline, `warn` jest tylko logowany.

**Orkiestrator: Prefect 3.** Flow i taski to zwykłe funkcje Pythona z dekoratorami
`@flow`/`@task`. Prefect działa lokalnie bez osobnego schedulera i bazy (uruchamia tymczasowy
serwer sam), a flow testuje się zwykłym `pytest`. Właściwa logika jest w modułach bez
Prefecta (`layers`, `quality`, `musicbrainz`); `pipeline/flows.py` tylko je łączy.

## Konsekwencje

- Pipeline można uruchomić jednym poleceniem (`python -m pipeline run`) albo według
  harmonogramu (`python -m pipeline serve`). UI z historią uruchomień: `prefect server start`.
- Podczas przebudowy marts zapytania do nich czekają na koniec transakcji (blokada). Przy
  większych danych można przejść na budowanie przyrostowe albo podmianę tabel.
- Airflow jest popularniejszy w ogłoszeniach o pracę, ale wymaga schedulera, webservera
  i osobnej bazy metadanych. Logika jest oddzielona od Prefecta, więc migracja byłaby
  przepisaniem tylko `flows.py`.
- API nadal czyta tabele `public`. Przełączenie statystyk API na marts to osobna decyzja
  (podjęta w ADR 0007).
