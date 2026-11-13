# ADR 0012: Podobieństwo słuchaczy

Status: zaakceptowana · Data: 2026-11-12

## Kontekst

Ostatni element etapu 3: „kto słucha podobnie do mnie?”. To podstawa rekomendacji
(„słuchacze podobni do ciebie słuchają też...”). Miara musi być prosta do wyjaśnienia
i policzalna w SQL.

## Decyzja

- Każdy słuchacz to **wektor odsłuchów artystów** w oknie czasowym (artysta → liczba
  odsłuchów). Artyści, a nie utwory: wektory utworów są bardzo rzadkie i dwie osoby
  słuchające różnych piosenek tego samego artysty wyglądałyby na obce.
- Miara: **podobieństwo kosinusowe** = iloczyn skalarny / (długość a × długość b),
  od 0 (nic wspólnego) do 1 (te same proporcje). Nie zależy od tego, ile kto słucha:
  10 razy więcej odsłuchów w tych samych proporcjach to wciąż 1,0. Alternatywa,
  indeks Jaccarda (wspólni artyści / wszyscy artyści), ignoruje, jak często ktoś słucha.
- Liczone **w API na żądanie** z `marts.listener_track_daily`, jednym zapytaniem z CTE:
  odsłuchy per (słuchacz, artysta), długości wektorów, iloczyny skalarne przez złączenie
  po artyście. Złączenie wewnętrzne sprawia, że słuchacze bez wspólnych artystów nie
  pojawiają się w wyniku. Dzięki liczeniu na żądanie działa okno czasowe jak w innych
  statystykach i nie trzeba nowego martu.
- Każdy wynik ma `shared_artists` (ilu wspólnych artystów) i `top_shared_artists`
  (do 3), czyli wyjaśnienie, *dlaczego* słuchacze są podobni. Kolejność: według mniejszej
  z dwóch liczb odsłuchów (`least()`), żeby liczyli się artyści ważni dla obojga.
  Wybór pierwszych 3 na słuchacza robi `row_number() OVER (PARTITION BY ...)`.
- Endpoint: `GET /listeners/{id}/similar` (`limit`, okno czasowe).

## Konsekwencje

- **Popularni artyści podnoszą podobieństwo wszystkich ze wszystkimi.** W danych demo
  wyniki są w zakresie ok. 0,4–0,95: ranking rozróżnia słuchaczy, ale wartości bezwzględne
  są zawyżone. Poprawka na przyszłość: ważenie jak w TF-IDF (rzadki wspólny artysta mówi
  więcej niż wspólny hit) albo skala logarytmiczna liczby odsłuchów.
- Koszt rośnie z liczbą słuchaczy (porównanie z każdym, kto ma wspólnego artystę).
  Przy tysiącach słuchaczy wystarczy; przy milionach trzeba by liczyć podobieństwa
  w pipeline'ie (mart z top N podobnych na słuchacza) albo użyć przybliżonych metod
  wyszukiwania sąsiadów.
- Artyści bez odsłuchów w oknie nie wpływają na wynik; okno zmienia wektory, więc
  podobieństwo może się różnić między np. ostatnim miesiącem a całym rokiem.
