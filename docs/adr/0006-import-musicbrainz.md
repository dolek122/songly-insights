# ADR 0006: Import artystów z MusicBrainz

Status: zaakceptowana · Data: 2026-11-12

## Kontekst

Katalog z etapu 1 zawiera tylko artystów syntetycznych. MusicBrainz udostępnia otwarte dane
o artystach i tagach nadawanych przez użytkowników (ADR 0004). API MusicBrainz wymaga
najwyżej 1 zapytania na sekundę i nagłówka User-Agent z nazwą aplikacji i kontaktem.

## Decyzja

- Pobieramy artystów **po tagu** (`/ws/2/artist?query=tag:"jazz"`), stronami po maks. 100.
  Lista tagów to parametr flow (`--musicbrainz-tag`).
- Klient (`pipeline/musicbrainz.py`) pilnuje odstępu 1 s między zapytaniami. Odpowiedź
  503 (przeciążenie) kończy task błędem, a Prefect ponawia go do 3 razy co 30 s.
- Każda odpowiedź trafia w całości do `raw.musicbrainz_artist_search`. Strona pobrana
  w ciągu ostatnich 30 dni nie jest pobierana ponownie: `raw` działa też jako cache.
- Kontakt do User-Agent jest w zmiennej `MUSICBRAINZ_CONTACT` (`.env`), a nie w kodzie.
- **Publikacja do katalogu API**: po zbudowaniu staging artyści są dopisywani do
  `public.artists` (dopasowanie po `mbid`; znany artysta dostaje aktualną nazwę), każdy
  wyszukiwany tag staje się gatunkiem, a artysta jest łączony z istniejącymi gatunkami,
  których nazwa równa się jego tagowi z dodatnią liczbą głosów. Wszystko przez
  `ON CONFLICT`, więc ponowne uruchomienie niczego nie dubluje. To jedyne miejsce,
  w którym pipeline zapisuje do `public`.

## Konsekwencje

- Zaimportowani artyści nie mają utworów ani odsłuchów (w `marts.artist_popularity` mają 0).
  Utwory (nagrania z MusicBrainz) i prawdziwe odsłuchy (ListenBrainz) to kolejne kroki.
  Nagrania dodaje ADR 0008.
- Tag usunięty w MusicBrainz nie usuwa powiązania z gatunkiem w katalogu (tylko dopisujemy).
- Tagi to wolny tekst, więc dopasowanie do gatunków jest proste (równość nazw po
  normalizacji). Mapowanie synonimów (np. „hip-hop” → „hip hop”) można dodać później.
