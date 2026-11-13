# ADR 0009: Odsłuchy z ListenBrainz

Status: zaakceptowana · Data: 2026-11-12 · Zmienia częściowo: ADR 0008

## Kontekst

Do tej pory jedynymi odsłuchami były dane syntetyczne i to, co ktoś wyśle przez API.
ListenBrainz udostępnia prawdziwe historie odsłuchów przez API `/1/user/<nazwa>/listens`.
Większość odsłuchów ma identyfikator nagrania MusicBrainz (`recording_mbid`), więc można je
powiązać z katalogiem. Odsłuchy są publiczne, ale to dane osobowe.

## Decyzja

- **Kogo importujemy:** użytkowników podanych jawnie (`--listenbrainz-user`). Tylko własne
  konto albo konta osób, które się zgodziły. Każdy użytkownik staje się słuchaczem
  `lb_<nazwa>` z wypełnioną kolumną `listeners.listenbrainz_user`.
- **Import przyrostowy (watermark):** API zwraca odsłuchy od najnowszych. Pobieramy strony
  wstecz (`max_ts` = najstarszy odsłuch poprzedniej strony) i kończymy, gdy dojdziemy do
  najnowszego odsłuchu, który już mamy w staging. Kolejne uruchomienie pobiera więc tylko
  nowe odsłuchy. Zamiast cache z ADR 0006 jest znacznik, bo pierwsza strona zmienia się
  przy każdym nowym odsłuchu. Limit `--listens-per-user` (domyślnie 1000) chroni przed
  pobieraniem wieloletniej historii naraz.
- **raw → staging:** strony w całości w `raw.listenbrainz_listens`. Widok
  `staging.listenbrainz_listens` usuwa duplikaty z nakładających się stron i wybiera
  `mbid` z mapowania ListenBrainz, a gdy go brak, z danych od aplikacji. Wartości, które
  nie są UUID ani dodatnią liczbą, stają się NULL zamiast psuć cały widok.
- **Dopasowanie do katalogu po `recording_mbid`.** Nagranie, którego nie ma w katalogu,
  tworzymy z metadanych odsłuchu (tytuł, pierwszy artysta). Dane z MusicBrainz mają
  pierwszeństwo: publikacja ListenBrainz idzie po MusicBrainz i niczego nie nadpisuje.
- **Nieznana długość utworu:** odsłuchy często nie mają długości, więc
  `tracks.duration_ms` może być NULL (migracja `0004`). API nadal wymaga długości przy
  tworzeniu utworu. Czas słuchania w statystykach liczy tylko utwory o znanej długości.
  Z tego samego powodu nagrania z MusicBrainz bez długości też trafiają do katalogu
  (wcześniej były pomijane, ADR 0008).
- **Zdarzenia** dostają ten sam klucz naturalny co import przez API (ADR 0002), więc
  ponowne uruchomienie niczego nie dubluje.
- **Pomijane i raportowane (ostrzeżenia jakości danych):** odsłuchy bez `recording_mbid`,
  odsłuchy „z przyszłości” (zły zegar w aplikacji; zatrzymałyby test źródeł przy kolejnym
  uruchomieniu) i nagrania, których nie da się utworzyć (brak `mbid` artysty).
- Ograniczenia zapytań: wspólny `RateLimiter` (1 zapytanie/s) dla obu API.

## Konsekwencje

- Artyści utworzeni z odsłuchów nie mają gatunków, więc nie pojawiają się w rankingu
  gatunków, dopóki nie trafią do katalogu z wyszukiwania po tagu w MusicBrainz.
- `max_ts` jest wyłączny: jeśli strona urywa się w środku kilku odsłuchów z tej samej
  sekundy, pozostałe z tej sekundy zostaną pominięte. W praktyce bardzo rzadkie.
- Słuchacz, którego nazwa `lb_<nazwa>` jest już zajęta, nie zostanie utworzony, a jego
  odsłuchy pokaże ostrzeżenie `listenbrainz_listens_not_imported`.
- Cofnięcie migracji `0004` nie powiedzie się, dopóki istnieją utwory bez długości
  (celowo: nie usuwamy danych po cichu).
