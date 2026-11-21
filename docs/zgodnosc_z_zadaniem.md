# Zgodność z treścią zadania i materiałami eksperckimi

Stan po sprawdzeniu kodu i bazy na paczce organizatora (22 rekordy). Legenda: ✅ działa · 🟨 częściowo · ❌ brak.

## Treść zadania MFiPR

### Automatyczne zasilanie bazy (pkt 3)

| Wymaganie | Stan | Jak / czego brakuje |
|---|---|---|
| Import danych z pliku organizatora | ✅ | XLSX/CSV, raport per wiersz, ponowny import bez duplikatów; w kontenerze autoimport przy pustej bazie |
| Wgrywanie dodatkowych danych z plików (.doc .xls .pdf .csv) | 🟨 | PDF z warstwą tekstową i DOCX tylko w analizie nowego projektu; brak dołączania dokumentów (aneks, protokół) do istniejącego projektu; stare formaty .doc i .xls nieobsługiwane |
| Samodzielne wyszukiwanie danych w BZP/e-Zamówienia | ✅ | kopia organizatora `bzp.cytr.us` + oficjalne API jako zapas, cache, limit tempa |
| Dodatkowe źródła (TED, BK2021, KPOŚK, BIP, NIK, KIO) | 🟨 | BIP gminy (system d-bip, konfiguracja `bip_sources.json`, na razie Zagrodno); TED, BK2021, KPOŚK, NIK, KIO – brak |
| Ponowna analiza po pojawieniu się nowych dokumentów | 🟨 | ponowne pobranie przelicza kartę i zachowuje decyzje eksperta; brak automatycznego harmonogramu (monitoringu) |

### Łączenie rekordów (pkt 3 i 5)

| Wymaganie | Stan | Jak / czego brakuje |
|---|---|---|
| Łączenie po numerze ogłoszenia BZP, NIP, OCID | ✅ | numer BZP → OCID → wszystkie ogłoszenia postępowania; NIP sprawdzany w raporcie z testu (22/22 zgodne) |
| Łączenie po numerze TED, numerze projektu CST | ❌ | arkusz ich nie zawiera; brak integracji TED |
| Normalizacja i weryfikacja numerów z danymi podmiotu i zamówienia | ✅ | walidacja formatów BZP/KPO/NIP przy imporcie; raport: NIP, numer, tytuł, część zamówienia |
| Gdy brak klucza: nazwa, zamawiający, miejsce, CPV, wartość, daty + podstawa i poziom pewności | ✅ | 6 kryteriów, pewność wysoka/średnia/niska, propozycja tylko przy jednym kandydacie z wysoką pewnością |
| Projekt z wieloma postępowaniami / postępowanie z wieloma częściami | 🟨 | części zamówienia ✅ (Biecz, Zakrzew, Wolin); jeden projekt = jedno postępowanie (model danych dopuszcza więcej, pipeline nie) |

### Baza przypadków i identyfikowalność (pkt 3 i 5)

| Wymaganie | Stan | Jak |
|---|---|---|
| Relacje: projekt, postępowanie, ogłoszenia, kontrakty, zmiany, zdarzenia, koszty i terminy, dokumenty i źródła | ✅ | tabele `project`, `procedure`, `notice`, `contract`, `contract_change`, `event`, `fact`, `document`, `document_link` |
| Każdy rekord i wniosek prowadzi do źródła: identyfikator, link, data pobrania, strona/fragment | ✅ | numer ogłoszenia, URL, sekcja i punkt, cytat, data pobrania; BIP – numer strony PDF |
| Rozdzielenie danych źródłowych, obliczeń i wniosków | ✅ | w karcie: fakt / obliczenie (z formułą) / propozycja; w analizie każda sekcja ma etykietę „dane źródłowe” / „obliczenie” / „wniosek – do oceny eksperta” |
| Wyniki jako rekordy do filtrowania, aktualizacji i eksportu (JSON/CSV) | ✅ | eksport całej bazy (JSON z relacjami, CSV – 13 tabel w ZIP) z interfejsu, API (`/api/export`) i CLI; eksport analizy; raport połączeń CSV |

### Ryzyka i praca eksperta (pkt 3)

| Wymaganie | Stan | Jak / czego brakuje |
|---|---|---|
| Identyfikacja zdarzeń i fragmentów świadczących o ryzyku wg katalogu, do weryfikacji eksperta | ✅ | reguły R01–R15 + lokalny model Bielik-11B (przyczyna, kategoria, cytat ze źródła), wszystko jako propozycje |
| Katalog otwarty – proponowanie nowych kategorii do zatwierdzenia | ❌ | katalog R01–R15 jest w kodzie; brak dodawania kategorii w interfejsie |
| Skutki w czasie i koszcie | ✅ | wzrost wypłaty, opóźnienie względem terminu pierwotnego, przesunięcie terminu aneksem |
| Przyczyny zdarzeń | ✅ | z ogłoszeń o zmianie/wykonaniu umowy; model proponuje przyczynę jednym zdaniem z cytatem |
| Podjęte działania zaradcze i ich skuteczność | ❌ | rekomendacje są dla nowej inwestycji; brak wyciągania działań podjętych w historycznych przypadkach |
| Każde zdarzenie i wniosek zatwierdzane przez eksperta, z historią | 🟨 | propozycje ryzyk, powiązania KPO i dokumenty BIP – akceptuj / popraw / odrzuć z historią; fakty i zdarzenia faktyczne nie mają zatwierdzania |
| Panel eksperta: edycja danych wejściowych, opisów sektorów, tabel, ocena wiarygodności, materiały wzorcowe | ❌ | brak edycji faktów, katalogu i opisów w interfejsie; brak oceny wiarygodności i oznaczania wzorców |
| Wykorzystanie zatwierdzonej wiedzy w kolejnych analizach | ✅ | w analizie nowego projektu ryzyka zatwierdzone ważą więcej, odrzucone są pomijane |

### Analiza nowej inwestycji (pkt 3 i 5)

| Wymaganie | Stan | Jak |
|---|---|---|
| Opis językiem naturalnym albo wstępne dokumenty | ✅ | tekst, PDF z warstwą tekstową, DOCX |
| Najbardziej zbliżone zakończone inwestycje z wyjaśnieniem podobieństwa | ✅ | cechy o równej wadze, „pasuje X z Y”, tabela pasuje / różni się / brak danych |
| Łączenie danych strukturalnych z treścią opisów | ✅ | podsektor, formuła, skala, budżet + podobieństwo treści |
| Prognozy kosztów i czasu, przedziały, liczebność próby, poziom pewności | ✅ | mediana i zakres przy n ≥ 3, wartości per przypadek przy mniejszej próbie, pewność wysoka/średnia/niska |
| Lista zagadnień, rekomendowane działania, propozycje zapisów | ✅ | flagi R01–R15 z dowodami, działanie i zapis do sprawdzenia; checklista wodociągowa |
| Eksport | ✅ | CSV (z BOM dla Excela) i JSON |

### Wymagania techniczne (pkt 5)

| Wymaganie | Stan | Jak / czego brakuje |
|---|---|---|
| Model ustawiany w konfiguracji, przykładowy plik konfiguracji | ✅ | `LLM_PROVIDER` / `LLM_MODEL` / `LLM_API_KEY`, `llm.env.example`; domyślnie lokalny Bielik-11B bez klucza |
| Informacja, gdzie przetwarzane są dane, licencje | ✅ | LICENSE (MIT); README: źródła, miejsce przetwarzania (lokalnie, w procesie; opcjonalnie Ollama/Anthropic), tabela licencji bibliotek i wag Qwen 2.5 (Apache 2.0) |
| DOCX i PDF z warstwą tekstową | ✅ | |
| OCR skanów (atut) | ❌ | 6 skanów w BIP Zagrodna – dowodem tytuł i data |
| Rejestr źródeł i operacji | 🟨 | cache zapytań, `import_run`, historia decyzji; brak dziennika operacji użytkownika |
| Skalowalność: wpisy powstają automatycznie | ✅ | import → BZP → BIP → karta bez ręcznego wiązania |
| Monitoring projektów w toku (atut) | ❌ | |

### Wymagania formalne (pkt 4) i materiały (pkt 6)

| Element | Stan |
|---|---|
| Działający prototyp (link) | 🟨 kontener w przygotowaniu; publiczny link – brak |
| Repozytorium | ✅ GitHub `MorissPA/HackNation2026`, gałąź `risk-miner-prototyp` |
| Schemat architektury i modelu danych | ✅ `docs/architektura.html` (przepływ + UML 2.0) |
| Instrukcja uruchomienia, opis źródeł i metod dopasowania | ✅ README |
| Raport z testu (poprawne / niepewne / błędne połączenia + analiza nowego projektu) | ✅ `docs/raport_z_testu.md` (15 / 7 / 0) |
| Przykładowy eksport ustrukturyzowanych danych | ✅ `docs/przyklad_eksportu/` (JSON i CSV ZIP, generowane `cli.py export`) |
| Opis rozwiązania (do 10 stron) | ❌ |
| Prezentacja PDF (do 10 slajdów) | ❌ |
| Film (do 3 minut) | ❌ |

## Materiał „porady, fazy, dokumenty, ryzyka”

| Zalecenie | Stan | Uwagi |
|---|---|---|
| Kopia BZP `bzp.cytr.us` | ✅ | źródło główne |
| Taksonomia podsektorów, podsektor główny i dodatkowe, rodzaj prac osobno | ✅ | w analizie nowego projektu |
| Katalog R01–R15, wskazanie „sygnał → zdarzenie → wpływ” | 🟨 | katalog ✅; propozycje mają sygnał i cytat, wpływ liczony dla umowy, nie dla zdarzenia |
| Zdarzenia: zmiana terminu, wynagrodzenia, zakresu, wykonanie po terminie, wypłata wyższa | ✅ | |
| Nienależyte wykonanie | ✅ | sygnał z ogłoszenia o wykonaniu (4 umowy w paczce) + propozycja R12 |
| Niewykonanie, rozwiązanie, odstąpienie od umowy | ✅ | „wykonana: Nie” i słowa „odstąpienie / rozwiązanie / wypowiedzenie umowy” w ogłoszeniu o wykonaniu → sygnał + propozycja R12 (w paczce brak takich umów; reguły pokryte testami) |
| Unieważnienie i powtórzone postępowanie | ✅ | unieważnienie (całości lub części) z przesłanką art. 255 i przyczyną → sygnał + propozycja (np. pkt 3 → R13); wcześniejsze unieważnione postępowanie zamawiającego o podobnym przedmiocie → sygnał + czas stracony na powtórzenie. W paczce: Gościeradów – pierwsze postępowanie unieważnione z braku ofert, powtórka po 223 dniach |
| Zmiana wykonawcy (art. 455 ust. 1 pkt 2) | ✅ | sygnał + propozycja R12 (w paczce brak takich zmian; reguła pokryta testami) |
| Odwołanie do KIO, wyniki kontroli NIK | ❌ | brak tych źródeł |
| Znaczenie podstaw prawnych zmian (art. 455) | 🟨 | podstawa pokazana, bez objaśnienia |
| Kwoty netto i brutto | ✅ | ostrzeżenie przy porównaniu z wartością szacunkową |
| Projekt ≠ postępowanie ≠ część ≠ umowa | ✅ | osobne poziomy kwot |
| „Brak dokumentu ≠ brak działania” | ✅ | braki opisują, czego nie ma w źródłach i co uzupełnić |
| Chronologia i wersje dokumentów | 🟨 | kilka ogłoszeń o wykonaniu tej samej umowy – obowiązuje najnowsze, różnice w brakach |
| Hierarchia dokumentów, sprzeczności SWZ/PFU/umowa | ❌ | nie analizujemy dokumentacji przetargowej z platform zakupowych |
| PPU/SWU jako substytut umowy | ❌ | |

## Materiał „przygotowanie inwestycji wodociągowej”

| Zalecenie | Stan | Uwagi |
|---|---|---|
| Checklista 9 pozycji jako pytania do opisu nowej sieci | ✅ | w analizie nowego projektu: „jest w opisie” / „brak w opisie” z fragmentem |
| Rozróżnienie funkcji sieci, odbiorców początkowych i docelowych, zasilania | 🟨 | tylko jako pozycje checklisty (słowa kluczowe), bez osobnych pól formularza |
