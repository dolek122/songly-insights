# ADR 0010: Sesje słuchania

Status: zaakceptowana · Data: 2026-11-12

## Kontekst

Etap 3 dodaje analitykę zachowań: nie tylko „ile”, ale „jak” ktoś słucha. Pojedyncze
odsłuchy nie mówią, czy ktoś słuchał godzinę bez przerwy, czy puścił jeden utwór.
Potrzebna jest definicja sesji, prosta do wyjaśnienia i do policzenia w SQL.

## Decyzja

- **Sesja** to ciąg odsłuchów jednego słuchacza, w którym każdy kolejny utwór zaczyna się
  najwyżej **30 minut** po początku poprzedniego. Przerwa dłuższa niż 30 minut zaczyna nową
  sesję (dokładnie 30 minut to jeszcze ta sama sesja). Podobny próg stosują popularne
  narzędzia analityki webowej.
- Sesje liczy pipeline w `marts.listening_sessions` wzorcem **gaps and islands**:
  `lag()` dokłada czas poprzedniego odsłuchu, odsłuch po dużej przerwie dostaje flagę 1,
  suma narastająca flag numeruje sesje, a `GROUP BY` po numerze zwija je do jednego wiersza.
- Sesja **kończy się**, gdy kończy się jej ostatni utwór (początek + długość). Utwór
  o nieznanej długości kończy się w chwili rozpoczęcia.
- Sesja należy do **dnia UTC, w którym się zaczęła**, także gdy trwa po północy. Filtr
  okna w API działa po tym dniu (pełne dni, ADR 0007).
- Sesję identyfikuje **(słuchacz, początek)**. Numer sesji nie jest zapisywany, bo zmienia
  się, gdy później zaimportujemy starsze odsłuchy.
- Test jakości `listening_sessions_separated_by_gap` sprawdza samą regułę: kolejne sesje
  słuchacza muszą być oddalone o więcej niż 30 minut.
- API: `GET /listeners/{id}/sessions` (lista, od najnowszych, z paginacją) oraz
  `GET /stats/sessions` (liczba, średnia i **mediana** długości, najdłuższa sesja).
- Generator danych tworzy teraz serie 1–12 utworów granych jeden po drugim; wcześniej
  odsłuchy były rozrzucone losowo i prawie każda „sesja” miała 1 utwór.

## Konsekwencje

- Próg 30 minut jest wpisany w SQL. Zmiana wymaga edycji `pipeline/sql/marts.sql`
  i przebudowy martów, ale nie migracji.
- Dwie sesje słuchacza nie mogą się nakładać, nawet gdy ktoś słucha na dwóch urządzeniach
  naraz: takie odsłuchy łączą się w jedną sesję.
- Zmiana generatora zmieniła dane demo (ten sam `--seed` daje teraz inne odsłuchy niż przed
  tą zmianą).
