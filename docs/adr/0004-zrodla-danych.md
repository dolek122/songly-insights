# ADR 0004: Źródła danych (bez Spotify Web API)

Status: zaakceptowana · Data: 2026-11-09

## Kontekst

Naturalnym źródłem danych o odsłuchach byłoby Spotify Web API. W latach 2024–2026 nowe
aplikacje straciły jednak dostęp do większości endpointów (m.in. rekomendacje, cechy audio,
rozszerzony dostęp wymaga zgody Spotify). Projekt oparty na tym API mógłby przestać działać
albo w ogóle nie dostać dostępu.

## Decyzja

- Nie budujemy funkcji na Spotify Web API.
- Źródła danych:
  1. **Generator syntetyczny** (`python -m app.cli seed`), deterministyczny (ten sam `--seed`
     daje te same dane), działa offline. Podstawa testów i demo w etapie 1.
  2. **MusicBrainz**: otwarta baza artystów, nagrań i tagów (gatunków). Kolumny `mbid`
     w tabelach `artists` i `tracks` są przygotowane pod import w etapie 2.
  3. **ListenBrainz** (opcjonalnie): otwarte historie odsłuchów powiązane z identyfikatorami
     MusicBrainz.

## Konsekwencje

- Dane syntetyczne nie odzwierciedlają w pełni prawdziwych zachowań słuchaczy; wnioski
  z demo dotyczą działania systemu, a nie muzyki.
- Import z MusicBrainz będzie musiał mapować tagi na gatunki i korzystać z `mbid` jako klucza.
