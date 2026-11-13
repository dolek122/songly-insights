# ADR 0016: HTTPS przez Caddy i ograniczenie portów

Status: zaakceptowana · Data: 2026-11-13 · Uzupełnia: ADR 0013

## Kontekst

Stos z ADR 0013 publikował porty wszystkich usług na wszystkich interfejsach, bez
szyfrowania. Na serwerze oznaczałoby to: hasła i dane po HTTP otwartym tekstem oraz
Prometheus, Alertmanager i Prefect (bez logowania) dostępne z całego internetu. Ważna
pułapka: porty publikowane przez Dockera **omijają zaporę hosta** (np. ufw), bo Docker
dopisuje własne reguły iptables.

## Decyzja

- **Caddy** jako jedyna usługa dostępna z zewnątrz (porty 80 i 443). Dla prawdziwej
  domeny sam pobiera i odnawia certyfikat Let's Encrypt; HTTP przekierowuje na HTTPS.
  Konfiguracja to kilka linii w `deploy/caddy/Caddyfile` (prostsze niż nginx + certbot).
- Dwie domeny z `.env`: `API_DOMAIN` (API) i `GRAFANA_DOMAIN` (Grafana). Domyślnie
  `api.localhost` / `grafana.localhost` z lokalnym urzędem certyfikacji Caddy.
- `/metrics` jest zablokowane w Caddy (404): Prometheus czyta je w sieci Dockera,
  z internetu nie są potrzebne, a zdradzają szczegóły systemu.
- Nagłówki: HSTS (przeglądarka używa tylko HTTPS), `X-Content-Type-Options: nosniff`,
  bez nagłówka `Server`.
- **Wszystkie pozostałe porty tylko na `127.0.0.1`** (baza, API bez TLS, Grafana bez TLS,
  Prometheus, Alertmanager, Prefect). Z laptopa dostęp przez tunel SSH:
  `ssh -L 9090:localhost:9090 serwer`.

## Konsekwencje

- Na serwerze potrzebne są rekordy DNS obu domen wskazujące na serwer i otwarte porty
  80/443. Wolumen `caddy_data` przechowuje certyfikaty; jego utrata wymusi ponowne
  wydanie (Let's Encrypt ma limity).
- Lokalnie przeglądarka ostrzega o certyfikacie lokalnego CA Caddy; to oczekiwane.
- Prometheus, Alertmanager i Prefect nie mają logowania, więc pozostają tylko lokalne.
  Wystawienie ich wymagałoby uwierzytelnienia w Caddy (np. basic auth).
