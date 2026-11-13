# ADR 0018: Logi w formacie JSON z identyfikatorem zapytania

Status: zaakceptowana · Data: 2026-11-13

## Kontekst

Na serwerze logi czyta się przez `docker compose logs` albo narzędzia do ich zbierania.
Tekstowe logi trudno filtrować („pokaż wszystkie 500 dla tej trasy”), a logów jednego
zapytania nie da się powiązać, gdy obok działają inne zapytania.

## Decyzja

- Przy `LOG_FORMAT=json` (ustawione w docker compose) każda linia logu to jeden obiekt
  JSON: czas (UTC), poziom, logger, treść i dodatkowe pola. Formatter to kilkanaście linii
  na standardowym module `logging`, bez nowych zależności (`app/logging_config.py`).
  Lokalnie i w testach (`LOG_FORMAT=text`) logowanie zostaje domyślne.
- **Log dostępu** pisze aplikacja, nie uvicorn (`--no-access-log`): jedna linia na
  zapytanie z metodą, szablonem trasy, ścieżką, statusem i czasem w ms. `/health`
  i `/metrics` są pomijane jak w metrykach.
- **Identyfikator zapytania:** nagłówek `X-Request-ID` od klienta lub proxy (jeśli wygląda
  bezpiecznie), inaczej nowy UUID. Wraca w odpowiedzi, a każdy log zapisany podczas
  obsługi zapytania, także błąd 500, ma pole `request_id`. Wartość jest w `ContextVar`,
  który ma osobną wartość w każdym zapytaniu, więc nie trzeba jej przekazywać przez funkcje.
- Logi uvicorna przechodzą przez ten sam formatter, a o poziomie decyduje `LOG_LEVEL`.

## Konsekwencje

- Przykład: `docker compose logs --no-log-prefix api | jq 'select(.status >= 500)'`.
  Użytkownik zgłaszający błąd może podać `X-Request-ID`, a my znajdziemy wszystkie
  linie tego zapytania.
- Pipeline loguje przez Prefect w jego formacie; jego logi są w UI Prefecta (:4200).
- Zbieranie logów w jednym miejscu (np. Loki + Grafana) to możliwy kolejny krok;
  format JSON go ułatwia.
