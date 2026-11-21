# Raport z testu – Risk Miner (2026-11-21)

Raport generowany poleceniem `python cli.py report` z aktualnej bazy. Każde połączenie rekordu z arkusza z postępowaniem w BZP jest sprawdzane z danymi podmiotu i zamówienia: NIP zamawiającego, numer ogłoszenia, tytuł zamówienia, część zamówienia i kompletność ogłoszeń.

## Podsumowanie połączeń

| Wynik | Liczba | Znaczenie |
|---|---|---|
| poprawne | 15 | wszystkie kontrole spełnione, komplet ogłoszeń |
| niepewne | 7 | połączenie prawdopodobne, ale wymaga oceny eksperta (propozycja KPO, ogłoszenie niedostępne w API, brak ogłoszenia o wykonaniu, słaba zgodność tytułu) |
| błędne | 0 | niezgodny NIP, numer lub część albo brak powiązania |

Uwagi o jakości danych (np. pole „Wartość zmiany” wypełnione nową wartością umowy, kilka ogłoszeń o wykonaniu tej samej umowy, skany bez warstwy tekstowej) są w osobnej kolumnie – nie podważają połączenia, ale ekspert powinien je znać.

## Połączenia rekord po rekordzie

| Rekord | Identyfikator z arkusza | Metoda | Status | Wynik | Kontrole spełnione | Do sprawdzenia | Uwagi o danych |
|---|---|---|---|---|---|---|---|
| RM-2026-001 | Ogłoszenie BZP: `2022/BZP 00058537/01` | numer_bzp | potwierdzone | **poprawne** | NIP zgodny; numer BZP z arkusza w postępowaniu; tytuł zamówienia zawiera 100% słów nazwy | — | — |
| RM-2026-002 | Projekt KPO: `KPOD.03.15-IW.13-0004/25` | nazwa+NIP+miejscowość | potwierdzone | **poprawne** | NIP zgodny; tytuł zamówienia zawiera 100% słów nazwy | — | 7 dokumentów z BIP to skany lub pliki .doc – OCR nie jest obsługiwany, więc dowodem jest tytuł i data publikacji (np. „OBWIESZCZENIE dotyczące budowy oczyszczal; Ta sama umowa ma kilka ogłoszeń o wykonaniu – przyjęto najnowsze 2026/BZP 00285691/01, wcześniejsze 2026/BZP 00277648/01 różni się: okres realizacji: „3 miesiąc; Zmiana nr 1 (2026/BZP 00285691/01): „Wartość zmiany” 5,350,782.65 ≈ wartości umowy – prawdopodobnie wpisano nową wartość umowy, a nie różnicę. Wymaga weryfikacj |
| RM-2026-003 | Ogłoszenie BZP: `2024/BZP 00349631/01` | numer_bzp | potwierdzone | **poprawne** | NIP zgodny; numer BZP z arkusza w postępowaniu; tytuł zamówienia zawiera 100% słów nazwy | — | — |
| RM-2026-004 | Ogłoszenie BZP: `2025/BZP 00569258/01` | numer_bzp | potwierdzone | **poprawne** | NIP zgodny; numer BZP z arkusza w postępowaniu; tytuł zamówienia zawiera 100% słów nazwy | — | — |
| RM-2026-005 | Projekt KPO: `KPOD.03.15-IW.14-0032/25` | kryteria: nazwa, zamawiający, miejsce, CPV, wartość, daty | proponowane | **niepewne** | NIP zgodny; tytuł zamówienia zawiera 100% słów nazwy | powiązanie KPO zaproponowane automatycznie, czeka na eksperta (6/6 kryteriów, pewność wysoka) | — |
| RM-2026-006 | Ogłoszenie BZP: `2024/BZP 00067908/01` | numer_bzp | potwierdzone | **poprawne** | NIP zgodny; numer BZP z arkusza w postępowaniu; tytuł zamówienia zawiera 100% słów nazwy | — | — |
| RM-2026-007 | Projekt KPO: `KPOD.03.15-IW.15-0081/25` | kryteria: nazwa, zamawiający, miejsce, CPV, wartość, daty | proponowane | **niepewne** | NIP zgodny; tytuł zamówienia zawiera 100% słów nazwy | powiązanie KPO zaproponowane automatycznie, czeka na eksperta (6/6 kryteriów, pewność wysoka) | — |
| RM-2026-008 | Ogłoszenie BZP: `2026/BZP 00084760/01` | numer_bzp | potwierdzone | **poprawne** | NIP zgodny; numer BZP z arkusza w postępowaniu; tytuł zamówienia zawiera 100% słów nazwy; umowa części 1 | — | Ogłoszenia o wykonaniu nieprzypisane do umowy z tego zakresu: 2026/BZP 00255135/01, 2026/BZP 00255161/01, 2026/BZP 00255185/01 (inne części postępowania) |
| RM-2026-009 | Ogłoszenie BZP: `2025/BZP 00307948/01` | numer_bzp | potwierdzone | **poprawne** | NIP zgodny; numer BZP z arkusza w postępowaniu; tytuł zamówienia zawiera 100% słów nazwy; umowa części 2 | — | Ogłoszenia o wykonaniu nieprzypisane do umowy z tego zakresu: 2025/BZP 00568576/01 (inne części postępowania); Zmiana nr 1 (2025/BZP 00568661/01): „Wartość zmiany” 1,881,383.15 ≈ wartości umowy – prawdopodobnie wpisano nową wartość umowy, a nie różnicę. Wymaga weryfikacj |
| RM-2026-010 | Projekt KPO: `KPOD.03.15-IW.21-0025/25` | kryteria: nazwa, zamawiający, miejsce, CPV, wartość, daty | proponowane | **niepewne** | NIP zgodny; tytuł zamówienia zawiera 100% słów nazwy | powiązanie KPO zaproponowane automatycznie, czeka na eksperta (6/6 kryteriów, pewność wysoka) | Zmiana nr 1 (2026/BZP 00004536/01): „Wartość zmiany” 3,348,882.44 ≈ wartości umowy – prawdopodobnie wpisano nową wartość umowy, a nie różnicę. Wymaga weryfikacj |
| RM-2026-011 | Ogłoszenie BZP: `2023/BZP 00271948/01` | numer_bzp | potwierdzone | **poprawne** | NIP zgodny; numer BZP z arkusza w postępowaniu; tytuł zamówienia zawiera 100% słów nazwy | — | — |
| RM-2026-012 | Ogłoszenie BZP: `2025/BZP 00119683/01` | numer_bzp | potwierdzone | **poprawne** | NIP zgodny; numer BZP z arkusza w postępowaniu; tytuł zamówienia zawiera 100% słów nazwy | — | — |
| RM-2026-013 | Ogłoszenie BZP: `2023/BZP 00206497/01` | numer_bzp | potwierdzone | **poprawne** | NIP zgodny; numer BZP z arkusza w postępowaniu; tytuł zamówienia zawiera 100% słów nazwy | — | — |
| RM-2026-014 | Ogłoszenie BZP: `2026/BZP 00130634/01` | numer_bzp | potwierdzone | **poprawne** | NIP zgodny; numer BZP z arkusza w postępowaniu; tytuł zamówienia zawiera 100% słów nazwy | — | — |
| RM-2026-015 | Ogłoszenie BZP: `2023/BZP 00135041/01` | numer_bzp | potwierdzone | **poprawne** | NIP zgodny; numer BZP z arkusza w postępowaniu; tytuł zamówienia zawiera 100% słów nazwy | — | — |
| RM-2026-016 | Ogłoszenie BZP: `2022/BZP 00308854/01` | numer_bzp | potwierdzone | **poprawne** | NIP zgodny; numer BZP z arkusza w postępowaniu; tytuł zamówienia zawiera 100% słów nazwy | — | — |
| RM-2026-017 | Projekt KPO: `KPOD.03.15-IW.27-0013/25` | kryteria: nazwa, zamawiający, miejsce, CPV, wartość, daty | proponowane | **niepewne** | NIP zgodny; tytuł zamówienia zawiera 100% słów nazwy | powiązanie KPO zaproponowane automatycznie, czeka na eksperta (6/6 kryteriów, pewność wysoka) | — |
| RM-2026-018 | Projekt KPO: `KPOD.03.15-IW.27-0107/25` | kryteria: nazwa, zamawiający, miejsce, CPV, wartość, daty | proponowane | **niepewne** | NIP zgodny; tytuł zamówienia zawiera 100% słów nazwy | powiązanie KPO zaproponowane automatycznie, czeka na eksperta (6/6 kryteriów, pewność wysoka) | — |
| RM-2026-019 | Ogłoszenie BZP: `2024/BZP 00354928/01` | numer_bzp | potwierdzone | **poprawne** | NIP zgodny; numer BZP z arkusza w postępowaniu; tytuł zamówienia zawiera 100% słów nazwy | — | Zmiana nr 1 (2025/BZP 00626318/01): „Wartość zmiany” 3,648,128.71 ≈ wartości umowy – prawdopodobnie wpisano nową wartość umowy, a nie różnicę. Wymaga weryfikacj; Zmiana nr 5 (2025/BZP 00626318/01): „Wartość zmiany” 4,192,921.56 ≈ wartości umowy – prawdopodobnie wpisano nową wartość umowy, a nie różnicę. Wymaga weryfikacj |
| RM-2026-020 | Projekt KPO: `KPOD.03.15-IW.28-0003/24` | kryteria: nazwa, zamawiający, miejsce, CPV, wartość, daty | proponowane | **niepewne** | NIP zgodny; tytuł zamówienia zawiera 100% słów nazwy | powiązanie KPO zaproponowane automatycznie, czeka na eksperta (6/6 kryteriów, pewność wysoka) | — |
| RM-2026-021 | Ogłoszenie BZP: `2025/BZP 00364116/01` | numer_bzp | potwierdzone | **poprawne** | NIP zgodny; numer BZP z arkusza w postępowaniu; tytuł zamówienia zawiera 100% słów nazwy | — | — |
| RM-2026-022 | Ogłoszenie BZP: `2023/BZP 00110672/01` | odwołanie_w_ogłoszeniu | potwierdzone | **niepewne** | NIP zgodny; tytuł zamówienia zawiera 100% słów nazwy | ogłoszenie z arkusza niedostępne w API – powiązanie przez odwołanie w innym ogłoszeniu | Treść ogłoszenia o zamówieniu 2023/BZP 00110672/01 jest niedostępna w API BZP – powiązanie ustalono przez odwołanie w ogłoszeniu 2023/BZP 00580488/01. Brak dany; Nie znaleziono ogłoszenia o wyniku postępowania – brak cen ofert i wartości szacunkowej. |

## Analiza nowego projektu – przykłady

### Nowa oczyszczalnia ścieków

Gmina planuje budowę nowej biologicznej oczyszczalni ścieków dla 1200 RLM w formule zaprojektuj i wybuduj, wraz z przebudową kolektora kanalizacji sanitarnej. Oczyszczone ścieki będą odprowadzane do rzeki. Istniejąca oczyszczalnia musi pracować bez przerwy w trakcie budowy. Budżet 4,5 mln zł, termin realizacji 18 miesięcy.

Podobne przypadki (pasujące cechy / porównywalne): RM-2026-003 (5/7); RM-2026-006 (3/6); RM-2026-015 (4/7); RM-2026-021 (3/6); RM-2026-013 (4/7)

Wzrost wypłaty: n = 5, mediana 6.8%, zakres -45.0…40.3%. Opóźnienie: n = 5, mediana 81 dni, zakres 31…277 dni. Pewność prognozy: **średnia**.

| Ryzyko | Siła sygnału | Rekomendowane działanie |
|---|---|---|
| R07 Nieprzewidziane zmiany i roboty dodatkowe | średnia | Zaplanować rezerwę budżetową na roboty nieprzewidziane (na podstawie wzrostu wypłat w podobnych przypadkach). |
| R04 Decyzje, pozwolenia i uzgodnienia zależne od podmiotów trzecich | silna | Ustalić, kto i kiedy uzyskuje decyzje (pozwolenie wodnoprawne, środowiskowa, pozwolenie na budowę), i ująć ich czas w harmonogramie. |
| R03 Kolizje, dostęp do terenu i prawa do nieruchomości | średnia | Potwierdzić prawo do dysponowania gruntem na całej trasie i zinwentaryzować kolizje z uzbrojeniem. |
| R01 Niepełny lub niespójny zakres | słaba | Zweryfikować kompletność zakresu w PFU/OPZ (inwentaryzacja, przedmiar, granice zadania) przed ogłoszeniem. |

### Rozbudowa sieci wodociągowej

Rozbudowa sieci wodociągowej o długości 6,5 km w trzech miejscowościach wraz z 80 przyłączami. Trasa w pasie drogi powiatowej i częściowo przez grunty prywatne, przejście pod linią kolejową. Zasilanie z istniejącej SUW. Budżet 3 mln zł, termin 12 miesięcy.

Podobne przypadki (pasujące cechy / porównywalne): RM-2026-007 (3/7); RM-2026-011 (4/7); RM-2026-022 (3/7); RM-2026-016 (3/7); RM-2026-009 (3/7)

Wzrost wypłaty: n = 5, mediana 3.9%, zakres -0.6…14.7%. Opóźnienie: n = 5, mediana 12 dni, zakres -6…31 dni. Pewność prognozy: **wysoka**.

| Ryzyko | Siła sygnału | Rekomendowane działanie |
|---|---|---|
| R07 Nieprzewidziane zmiany i roboty dodatkowe | średnia | Zaplanować rezerwę budżetową na roboty nieprzewidziane (na podstawie wzrostu wypłat w podobnych przypadkach). |
| R03 Kolizje, dostęp do terenu i prawa do nieruchomości | średnia | Potwierdzić prawo do dysponowania gruntem na całej trasie i zinwentaryzować kolizje z uzbrojeniem. |
| R04 Decyzje, pozwolenia i uzgodnienia zależne od podmiotów trzecich | średnia | Ustalić, kto i kiedy uzyskuje decyzje (pozwolenie wodnoprawne, środowiskowa, pozwolenie na budowę), i ująć ich czas w harmonogramie. |
| R12 Niewystarczająca zdolność wykonawcy lub łańcucha dostaw | słaba | Sprawdzić zdolność wykonawców i dostępność urządzeń na rynku. |
