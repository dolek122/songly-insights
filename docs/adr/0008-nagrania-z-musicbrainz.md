# ADR 0008: Nagrania z MusicBrainz jako utwory w katalogu

Status: zaakceptowana · Data: 2026-11-12 · Uzupełnia: ADR 0006 · Częściowo zmieniona przez
ADR 0009 (nagrania bez długości trafiają do katalogu z nieznaną długością)

## Kontekst

Artyści zaimportowani z MusicBrainz (ADR 0006) nie mieli utworów, więc nie dało się do nich
importować odsłuchów. MusicBrainz nazywa utwór „nagraniem” (recording): konkretne wykonanie
z tytułem i długością. Jeden artysta może mieć tysiące nagrań (wersje live, remastery).

## Decyzja

- Nagrania pobieramy endpointem **browse**: `/ws/2/recording?artist=<mbid>`, który zwraca
  nagrania danego artysty stronami po maks. 100. Parametr `recordings_per_artist`
  (domyślnie 25, `0` = pomiń) ogranicza liczbę nagrań na artystę.
- Pobieramy je dla **wszystkich artystów z `staging.musicbrainz_artists`**. Krok działa po
  zbudowaniu staging, bo listę artystów czyta z widoku. Widoki czytają `raw` na bieżąco,
  więc nowe nagrania są widoczne w staging od razu, bez ponownej przebudowy.
- Odpowiedzi trafiają w całości do `raw.musicbrainz_recording_browse` (migracja `0003`),
  z tym samym 30-dniowym cache co artyści. Kod cache i zapisu do raw jest wspólny
  (`_fetch_page` w `pipeline/musicbrainz.py`).
- `staging.musicbrainz_recordings` bierze najnowszą wersję każdego nagrania. Nagranie
  kilku artystów (duet) przychodzi przy każdym z nich; zostaje artysta z najnowszej strony.
- Publikacja do `public.tracks` po `mbid`: nowe nagrania są dodawane, znane dostają aktualny
  tytuł i długość, ale **zachowują artystę**. Pomijamy nagrania bez długości (utwór musi
  mieć `duration_ms > 0`) i wideo. Tytuły i nazwy są przycinane do długości kolumn
  (`left(..., 300)`), bo dane z MusicBrainz nie znają naszych limitów.
- Test jakości `musicbrainz_recordings_have_length` (ostrzeżenie) pokazuje, ile nagrań
  pominięto z powodu braku długości.

## Konsekwencje

- Czas importu rośnie: 1 zapytanie na artystę (przy ≤ 100 nagraniach), czyli ok. 1 s na
  artystę przez limit MusicBrainz. 2 tagi × 25 artystów to ok. 50 s; kolejne uruchomienia
  w ciągu 30 dni korzystają z cache.
- Kolejność nagrań w browse nie oznacza popularności, więc 25 pierwszych to nie „największe
  przeboje”. W katalogu mogą być też podobne tytuły (np. wersja studyjna i remaster).
- Utwory z MusicBrainz nie mają jeszcze odsłuchów. Odsłuchy z ListenBrainz (powiązane
  z `mbid` nagrań) to naturalny następny krok.
