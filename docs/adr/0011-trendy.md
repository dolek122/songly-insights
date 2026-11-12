# ADR 0011: Trendy (rosnący i spadający artyści oraz gatunki)

Status: zaakceptowana · Data: 2026-11-12

## Kontekst

Ranking „top” pokazuje, co jest popularne, ale nie co zyskuje lub traci popularność.
Trend musi być prosty do wyjaśnienia i odporny na brak danych z przeszłości.

## Decyzja

- Trend porównuje **okno z poprzednim oknem tej samej długości**: dla
  `from=2026-01-08&to=2026-01-15` poprzednie okno to `2026-01-01 – 2026-01-08`.
  Oba końce okna są wymagane, oba muszą być pełnymi dniami UTC (ADR 0007).
- `change` = odsłuchy teraz − odsłuchy wcześniej. Ranking `direction=rising` sortuje po
  największym wzroście, `falling` po największym spadku; przy remisie wygrywa ten z większą
  liczbą odsłuchów, a dalej niższe id (wynik deterministyczny).
- Sortujemy po **zmianie bezwzględnej**, a nie procentowej: wzrost z 1 do 3 odsłuchów to
  +200%, co wypchnęłoby na górę artystów z garstką odsłuchów. Procent (`change_pct`)
  zwracamy jako informację; przy wzroście od zera jest `null`.
- Jedno zapytanie czyta oba okna z `marts.listener_track_daily`, a `CASE` w sumach
  rozdziela odsłuchy na „teraz” i „wcześniej”. Nie potrzeba nowego martu.
- Gatunki liczymy tak jak w rankingu gatunków: odsłuch liczy się do każdego gatunku
  artysty (ADR 0003).
- Endpointy: `GET /stats/trending-artists` i `GET /stats/trending-genres`
  (`listener_id` opcjonalnie). Generator danych dostał powolny trend popularności artystów,
  żeby dane demo pokazywały coś więcej niż szum.

## Konsekwencje

- Nowi artyści (0 odsłuchów wcześniej) pojawiają się wśród rosnących, ale bez procentu.
- Okno sięgające przed początek danych porówna się z pustym poprzednim oknem: wszystko
  będzie „rosnące”. To poprawne liczbowo, ale mało ciekawe; klient wybiera okno.
- Przy małej liczbie odsłuchów zmiany to głównie przypadek. Testy statystyczne
  (np. istotności zmiany) można dodać później.
