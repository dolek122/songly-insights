# ADR 0003: Okna czasowe, dni w UTC i liczenie gatunków

Status: zaakceptowana · Data: 2026-11-09 · Częściowo zmieniona przez ADR 0007
(statystyki przyjmują tylko pełne dni UTC)

## Kontekst

Wszystkie statystyki są liczone „w jakimś okresie”. Bez jasnych reguł łatwo o podwójne liczenie
na granicy okresów albo o różne wyniki zależnie od strefy czasowej serwera. Artysta może mieć
kilka gatunków, więc trzeba też ustalić, jak liczyć odsłuchy per gatunek.

## Decyzja

- **Okno jest półotwarte: `from` włącznie, `to` wyłącznie** (`from <= listened_at < to`).
  Kolejne okna (`1 sty – 1 lut`, `1 lut – 1 mar`) stykają się bez nakładania i bez dziur.
- Oba końce są opcjonalne (brak końca = brak ograniczenia), poza `/stats/daily`, które
  wymaga obu i obejmuje maksymalnie 366 dni. `from >= to` daje błąd `invalid_time_window`.
- **Wszystko liczymy w UTC.** Parametr bez strefy czasowej (np. `?from=2026-01-01`) jest
  traktowany jako UTC. Odpowiedź zwraca pole `window`, żeby klient widział, jak zinterpretowano
  jego dane.
- **Dzień to dzień kalendarzowy w UTC.** W SQL używamy `timezone('UTC', listened_at)::date`.
  Bez jawnej konwersji PostgreSQL użyłby strefy ustawionej w sesji i ten sam odsłuch mógłby
  trafić do innego dnia zależnie od konfiguracji serwera.
- Dni bez odsłuchów są zwracane z `plays = 0` (uzupełniane w Pythonie).
- **Odsłuch liczy się do każdego gatunku swojego artysty.** Artysta z gatunkami `rock`
  i `jazz` dodaje 1 do obu. Suma po gatunkach może więc być większa niż liczba odsłuchów.
  Odsłuchy artystów bez gatunku nie pojawiają się w rankingu gatunków.
- Przy równej liczbie odsłuchów rankingi sortujemy dodatkowo po id, żeby wynik był
  deterministyczny.

## Konsekwencje

- Użytkownik w Polsce widzi „dzień” przesunięty o 1–2 godziny względem swojego czasu lokalnego.
  Statystyki w strefie użytkownika mogą być dodane później jako parametr `tz`.
- Udziały procentowe gatunków trzeba liczyć względem sumy po gatunkach, a nie liczby odsłuchów.
