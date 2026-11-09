# ADR 0002: Unikalność zdarzeń odsłuchu i idempotentny import

Status: zaakceptowana · Data: 2026-11-09

## Kontekst

Zdarzenia odsłuchu trafiają do systemu partiami (`POST /api/v1/listening-events/bulk`, seed,
a w etapie 2 pipeline z zewnętrznych źródeł). Partie mogą być wysyłane ponownie: po timeoucie,
po błędzie sieci albo przy ponownym uruchomieniu zadania. Ponowne wysłanie nie może podwoić
statystyk.

## Decyzja

- Zdarzenie jest jednoznacznie identyfikowane przez **`(listener_id, track_id, listened_at)`**.
  W bazie pilnuje tego ograniczenie `uq_listening_events_natural_key`.
- Import używa `INSERT ... ON CONFLICT DO NOTHING ... RETURNING id`. Istniejące zdarzenia są
  pomijane, a `RETURNING` mówi, ile wierszy naprawdę dodano. Odpowiedź zawiera
  `received`, `inserted` i `duplicates`.
- Powtórzone wywołanie z tymi samymi danymi zwraca `inserted = 0` i ten sam stan bazy, dlatego
  endpoint zwraca `200`, a nie `201`.
- Unikalność sprawdza baza, a nie kod Pythona (`SELECT` przed `INSERT`). Dzięki temu dwa
  równoległe importy też nie utworzą duplikatów.
- `listened_at` musi zawierać strefę czasową (inaczej `422`). Ten sam moment zapisany w innej
  strefie (`12:00+02:00` i `10:00Z`) to to samo zdarzenie, bo baza przechowuje go w UTC.
- Import jest „wszystko albo nic”: jeśli którekolwiek zdarzenie wskazuje na nieistniejącego
  słuchacza lub utwór, cała partia jest odrzucana z kodem `unknown_reference` i listą brakujących id.
- Partia ma najwyżej 10 000 zdarzeń: jedno zapytanie ma 3 parametry na zdarzenie, a PostgreSQL
  pozwala na maksymalnie 65 535 parametrów.

## Konsekwencje

- Dwa prawdziwe odtworzenia tego samego utworu przez tę samą osobę w dokładnie tej samej
  chwili zostaną policzone raz. W praktyce to niemożliwe (precyzja do mikrosekund).
- Dane bez strefy czasowej trzeba poprawić przed importem. To świadomy wybór: lepiej odrzucić
  dane niż po cichu przesunąć je o kilka godzin.
