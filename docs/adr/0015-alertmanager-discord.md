# ADR 0015: Wysyłka alertów przez Alertmanager na Discord

Status: zaakceptowana · Data: 2026-11-12 · Uzupełnia: ADR 0014

## Kontekst

Alerty z ADR 0014 były widoczne tylko w UI Prometheusa i Grafany, więc ktoś musiałby tam
zaglądać. Awaria w nocy (np. nieudany pipeline) powinna dotrzeć do autora sama, bez spamu:
jeden problem = jedna wiadomość, przypomnienie co kilka godzin, informacja o naprawie.

## Decyzja

- **Alertmanager** jako osobna usługa. Podział ról: Prometheus decyduje, *kiedy* coś jest
  źle (reguły w `deploy/prometheus/alerts.yml`), Alertmanager decyduje, *kto* i *jak często*
  dostaje powiadomienie (`deploy/alertmanager/alertmanager.yml`).
- Kanał: **Discord** przez webhook kanału (wbudowana obsługa w Alertmanagerze, darmowe,
  powiadomienia na telefon). Adres webhooka jest sekretem: trafia z `.env`
  (`DISCORD_WEBHOOK_URL`) do pliku `/run/secrets/discord_webhook_url` przez sekrety
  docker compose, a Alertmanager czyta go opcją `webhook_url_file`. Nie ma go w repo
  ani w zmiennych środowiskowych kontenera.
- **Grupowanie i powtarzanie:** alerty o tej samej nazwie idą w jednej wiadomości
  (`group_by: [alertname]`, `group_wait: 30s`); trwający problem przypomina się co 4 h,
  alerty `info` (ostrzeżenia jakości danych) raz na dobę. `send_resolved: true` wysyła
  też wiadomość o naprawie.
- **Wyciszanie skutków (inhibit rules):** gdy baza nie działa, nie wysyłamy alertów
  o nieświeżych martach i nieudanym pipeline'ie, bo to tylko skutki. Gdy nie działa API,
  nie wysyłamy alertów opartych na jego metrykach.
- **Własny szablon wiadomości** (`deploy/alertmanager/templates/discord.tmpl`): status,
  waga, opis z adnotacji `summary`, czas i link do Alertmanagera. Linki używają publicznych
  adresów (`PROMETHEUS_EXTERNAL_URL`, `ALERTMANAGER_EXTERNAL_URL`), a nie nazw kontenerów.
- CI sprawdza konfigurację i szablony (`amtool check-config`).

## Konsekwencje

- Sprawdzono end-to-end lokalnie: nieudany przebieg pipeline'u → `PipelineFailed`
  w Prometheusie → wiadomość pod adresem webhooka w formacie Discorda, a po naprawie
  wiadomość RESOLVED. Prawdziwego Discorda nie testowano (brak dostępu z sesji); test
  z prawdziwym kanałem robi `amtool alert add` (README).
- Bez ustawionego `DISCORD_WEBHOOK_URL` system działa, ale wysyłka kończy się błędem
  w logach Alertmanagera; alerty nadal widać w jego UI na :9093.
- Zmiana kanału (Slack, e-mail) to zmiana tylko w `alertmanager.yml`; reguły alertów
  zostają bez zmian.
- Wyciszenia na czas prac (silences) ustawia się w UI Alertmanagera.
