# ADR 0017: Kopie zapasowe bazy z automatycznym testem odtworzenia

Status: zaakceptowana · Data: 2026-11-13

## Kontekst

Baza zawiera jedyne kopie odsłuchów zaimportowanych przez API i ListenBrainz. Marts da
się odbudować pipeline'em, ale `public` i `raw` już nie. Kopia, której nikt nigdy nie
odtworzył, może okazać się bezużyteczna dokładnie wtedy, gdy jest potrzebna.

## Decyzja

- Usługa `backup` (oficjalny obraz `postgres:16`, bez własnego obrazu) uruchamia
  `deploy/backup/backup.sh`: **jedna kopia od razu po starcie**, potem codziennie
  o `BACKUP_TIME` (UTC).
- `pg_dump --format=custom` (skompresowany, pozwala odtwarzać wybrane części) do
  `./backups` na hoście. Plik powstaje jako `.partial` i dostaje docelową nazwę dopiero
  po zakończeniu, więc niedokończona kopia nigdy nie wygląda na gotową.
- **Każda kopia jest odtwarzana** do tymczasowej bazy `insights_restore_check`
  (`pg_restore --exit-on-error`), liczone są w niej odsłuchy, a baza jest usuwana.
  Dopiero wtedy kopia jest „zweryfikowana”.
- Rotacja: pliki starsze niż `BACKUP_KEEP_DAYS` dni są usuwane.
- Wynik każdej kopii trafia do `ops.backups` (migracja `0007`); API wystawia metryki
  `songly_backup_last_success_timestamp_seconds` i `songly_backup_last_failed`, a alerty
  `BackupMissing` (brak zweryfikowanej kopii od 26 h) i `BackupFailed` trafiają na Discord.
- Odtworzenie: `backup.sh restore PLIK` używa `pg_restore --clean --if-exists
  --single-transaction`: wszystko albo nic; nieudane odtworzenie zostawia bazę bez zmian.
  Przed odtworzeniem zatrzymujemy API i pipeline (procedura w README).

## Konsekwencje

- Sprawdzono ćwiczeniem: usunięcie wszystkich odsłuchów, odtworzenie z kopii, ta sama
  liczba wierszy, uprawnienia `grafana_reader` i wersja migracji na miejscu.
- Kopie leżą na tym samym serwerze co baza: chronią przed błędem (np. przypadkowym
  `DELETE`), ale nie przed utratą serwera. Następny krok: kopiowanie `./backups` poza
  serwer (np. `rclone` do magazynu obiektów).
- Kopia z jednego dnia oznacza utratę do 24 h danych. Mniejsza strata wymagałaby
  archiwizacji WAL (odtwarzanie do punktu w czasie), na razie niepotrzebnej.
- Zrzuty zawierają dane osobowe (odsłuchy): `backups/` jest w `.gitignore`
  i `.dockerignore`.
