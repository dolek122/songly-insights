# ADR 0014: Monitoring (Prometheus) i dashboardy (Grafana)

Status: zaakceptowana · Data: 2026-11-12

## Kontekst

Po wdrożeniu trzeba wiedzieć, czy system działa (API, baza), czy dane są świeże
(pipeline uruchamia się co noc) i co mówią same dane (odsłuchy, gatunki, sesje).
Rozwiązanie ma być standardowe i trzymane w repozytorium jako kod.

## Decyzja

- **Prometheus** pobiera co 15 s metryki z `GET /metrics` API (`prometheus_client`):
  - ruch HTTP: liczba zapytań i histogram czasu odpowiedzi; etykietą jest **szablon
    trasy** (`/api/v1/listeners/{listener_id}`), nie prawdziwa ścieżka, żeby nie tworzyć
    osobnej serii dla każdego id. `/metrics` i `/health` nie są liczone.
  - stan danych, odczytywany z bazy przy każdym pobraniu: czy baza odpowiada, wiek martów,
    wynik ostatniego przebiegu pipeline'u, liczba ostrzeżeń jakości danych.
- **Historia przebiegów pipeline'u** w `ops.pipeline_runs` (migracja `0006`): flow zapisuje
  start i koniec każdego przebiegu, także nieudanego (z treścią błędu). Pipeline nie ma
  własnego endpointu metryk, bo działa okresowo; API wystawia jego stan za niego.
- **Alerty** w `deploy/prometheus/alerts.yml` (m.in. ApiDown, DatabaseDown, HighErrorRate,
  MartsStale, PipelineFailed) z testami jednostkowymi (`promtool test rules`) w CI.
- **Grafana** z dwoma dashboardami jako pliki JSON w `deploy/grafana/dashboards`
  (provisioning, zmiany przez UI nie są zapisywane):
  - „Songly – operations” (Prometheus): stan API i bazy, świeżość danych, ruch, błędy,
    percentyle czasu odpowiedzi,
  - „Songly – listening” (PostgreSQL): odsłuchy, gatunki, top artyści, sesje, czytane
    **bezpośrednio z martów** przez użytkownika tylko do odczytu `grafana_reader`.
    Uprawnienia do martów nadaje `marts.sql`, bo pipeline tworzy schemat od nowa.

## Konsekwencje

- Bez Alertmanagera alerty widać tylko w Prometheusie (:9090/alerts) i Grafanie; wysyłka
  e-mailem lub na Slacka to kolejny krok.
- Dashboard produktowy liczy w SQL to samo co część API (np. odsłuchy na dzień), więc
  logika jest w dwóch miejscach. Akceptujemy to: oba czytają te same marty, a zapytania
  są proste.
- Metryki HTTP zerują się przy restarcie API (Prometheus radzi sobie z tym w `rate()`).
- Wykresy oparte na `rate(...[5m])` są puste przez pierwsze minuty po starcie.
