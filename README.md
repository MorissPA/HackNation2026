# Risk Miner – prototyp

Aplikacja dla eksperta inwestycji wodno-ściekowych. Importuje arkusz projektów i automatycznie pobiera dane z Biuletynu Zamówień Publicznych (BZP). Z tych danych buduje kartę przypadku: postępowanie, umowy, zmiany, oś czasu, fakty z dowodem, obliczenia, propozycje ryzyk R01–R15 i braki danych.

## Uruchomienie

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python cli.py import ../Risk_Miner_dane_projekty.xlsx   # import arkusza
.venv/bin/python cli.py fetch RM-2026-003                          # Steklin z BZP
.venv/bin/streamlit run app.py                                     # UI: http://localhost:8501
```

Inne polecenia: `cli.py fetch --all` (wszystkie rekordy), `cli.py show RM-2026-003` (podsumowanie karty w terminalu).

Konfiguracja przez zmienne środowiskowe ([riskminer/config.py](riskminer/config.py)):

| Zmienna | Domyślnie | Opis |
|---|---|---|
| `RISKMINER_DB` | `data/riskminer.sqlite` | plik SQLite (w kontenerze na trwałym wolumenie) |
| `BZP_MIN_INTERVAL_S` | `2.2` | odstęp między zapytaniami do BZP (limit 30/min) |
| `BZP_SEARCH_CACHE_TTL_H` | `24` | ważność cache wyszukiwarki; treść ogłoszeń jest cache'owana bez limitu |
| `LLM_PROVIDER` / `LLM_MODEL` / `LLM_API_KEY` | – | model do ekstrakcji przyczyn (kolejny etap) |

## Architektura

| Moduł | Odpowiedzialność |
|---|---|
| `riskminer/importer.py` | Import XLSX/CSV z identyfikatorami jako tekst, walidacją formatów BZP/KPO/NIP i raportem per wiersz. Ponowny import robi upsert (nowy / zaktualizowany / bez zmian). |
| `riskminer/bzp/client.py` | Klient publicznego API BZP z limitem tempa, ponawianiem i cache w SQLite. |
| `riskminer/bzp/parser.py` | HTML ogłoszenia → pola z lokalizacją (sekcja, punkt, część). Ekstrakcja per typ ogłoszenia. |
| `riskminer/pipeline.py` | Ogłoszenia → postępowanie, umowy, zmiany, fakty, obliczenia, zdarzenia, propozycje ryzyk, braki. |
| `riskminer/risks.py` | Katalog R01–R15 z materiału eksperckiego i regułowe propozycje kategorii. |
| `riskminer/db.py` | Schemat SQLite. |
| `app.py` | Streamlit: Baza inwestycji, Weryfikacja eksperta, Analiza nowego projektu (szkielet). |

## Źródło: BZP – jak łączymy ogłoszenia

1. `GET /Board/Search?NoticeNumber=<numer z arkusza>` zwraca ogłoszenie bazowe, a z nim **identyfikator postępowania (OCID)** i identyfikator zamawiającego.
2. Ogłoszenia powiązane (wynik, zmiany umowy, wykonanie):
   - Wyszukiwarka ignoruje filtr po OCID. Dlatego szukamy po `OrganizationId` i początku tytułu (`OrderObject` dopasowuje podciąg).
   - Gdy brakuje ogłoszenia o wyniku albo o wykonaniu, przeglądamy wszystkie ogłoszenia zamawiającego od daty ogłoszenia bazowego (`PageNumber`, po 10 na stronę).
   - Wyniki zawsze **filtrujemy po OCID**.
3. Treść każdego ogłoszenia pobiera `GET /notice?NoticeType&PublicationDateFrom/To&NoticeNumber`. Okno dat wynosi ±1 dzień, bo API inaczej gubi ogłoszenia z wczesnych godzin. Pełny HTML zapisujemy w bazie, dzięki czemu dowód da się otworzyć w aplikacji.
4. **Ogłoszenie z arkusza niedostępne w API** (np. Wolin, `2023/BZP 00110672/01`). Szukamy ogłoszeń zamawiającego (zgodny NIP) po fragmentach nazwy przedsięwzięcia i sprawdzamy, które w treści cytują numer z arkusza. OCID bierzemy z takiego ogłoszenia. Metoda powiązania to `odwołanie_w_ogłoszeniu`, cytat trafia do dowodu, a w brakach pojawia się informacja o niedostępnym ogłoszeniu bazowym.
5. **Bez ogłoszenia o wyniku** umowy budujemy z ogłoszeń o wykonaniu, po jednej na część. Numer części odczytujemy z nazwy zamówienia („Umowa dla części nr 2”). Termin podany jako czas trwania („5 miesiące”) przeliczamy od daty zawarcia umowy i zapisujemy jako obliczenie z formułą.
6. **Rekordy KPO (bez numeru BZP)**, np. Modlikowice. Kandydatów szukamy w BZP po NIP zamawiającego (`OrganizationNationalId`) od roku poprzedzającego nabór KPO. Frazy wyszukiwania to rdzenie nazw miejscowości i słowa kluczowe podsektora. Ogłoszenia grupujemy po OCID i oceniamy jawnie w skali 0–100 ([riskminer/matcher.py](riskminer/matcher.py)):

   | Cecha | Punkty |
   |---|---|
   | miejscowości z nazwy przedsięwzięcia w tytule | do 35 |
   | podsektor (kanalizacja, wodociąg, oczyszczalnia, SUW) | do 25 |
   | podobieństwo nazwy (rdzenie słów) | do 20 |
   | roboty budowlane | 10 |
   | postępowanie wyłącznie na dokumentację projektową | −30 |
   | kompletność ogłoszeń (zamówienie, wynik, wykonanie) | do 5 |
   | wartość umów w przedziale 30–125% wartości przedsięwzięcia KPO | 5 |
   | wartość umów poza tym przedziałem | −15 |

   Gdy najlepszy kandydat ma co najmniej 60 pkt i 15 pkt przewagi nad drugim, powiązanie dostaje status **proponowane**, a karta liczy się od razu. W przeciwnym razie system nie tworzy powiązania i ekspert wybiera kandydata w panelu **Weryfikacja eksperta → Powiązania z BZP**. Ekspert może potwierdzić propozycję, wybrać innego kandydata albo ją odrzucić. Odrzucony OCID jest pomijany w kolejnych rankingach, każda decyzja trafia do `expert_decision`, a przypadek przelicza się automatycznie.
7. **Części zamówienia.** Ogłoszenie o wyniku ma sekcje „Część N”. Rekord ze `Zakres rekordu = część 2` dostaje tylko umowę z części 2. Ogłoszenia o wykonaniu i o zmianie nie podają numeru części, więc przypisujemy je do umowy po wartości, dacie zawarcia i NIP wykonawcy.

## Model danych

Tabele: `project`, `procedure` (OCID), `project_link` (z metodą dopasowania, dowodem i statusem), `notice`, `contract` (OCID + część), `contract_change`, `fact`, `event`, `gap`, `expert_decision`, `import_run`/`import_row` i `http_cache`.

- `fact.kind` przyjmuje jedną z trzech wartości:
  - **fakt** to odczyt ze znanego pola ogłoszenia z cytatem i punktem,
  - **obliczenie** ma zapisaną formułę,
  - **propozycja** to interpretacja do oceny eksperta.
- `fact.level` rozróżnia kwoty **umowy**, **postępowania** i **projektu** (KPO, z arkusza).
- Termin: **przesunięcie terminu umownego** (aneks) i **faktyczne opóźnienie** względem umowy pierwotnej to osobne obliczenia.
- Każdy przebieg robi upsert po kluczach naturalnych. Wpisy, których przebieg już nie wytworzył, są usuwane tylko wtedy, gdy ekspert ich nie ocenił.
- Decyzje eksperta trafiają do `expert_title`/`expert_comment` oraz do historii w `expert_decision` i nie są nadpisywane przy przeliczeniu.

## Znane ograniczenia i pułapki danych

- Pole „Wartość zmiany” w ogłoszeniu o wykonaniu bywa wypełniane **nową wartością umowy** zamiast różnicy (np. Zakrzew, część 1 i 2). Aplikacja oznacza to jako brak/niepewność, a wzrost kosztu liczy z „Łącznej wartości wynagrodzenia wypłaconej”.
- Wartość szacunkowa w BZP jest netto, a wartość umowy zwykle brutto. Porównanie ceny z szacunkiem ma przy formule zastrzeżenie o VAT.
- Dopasowanie KPO korzysta tylko z BZP. Drugie źródło dowodu, czyli dokumenty z BIP gminy (np. Zagrodno), to kolejny etap.
- Kilka ogłoszeń o wykonaniu tej samej umowy (korekty, np. Modlikowice) traktujemy tak: obowiązuje najnowsze, a różnice w kluczowych polach pokazujemy w brakach.
- Link „Otwórz w BZP” używa `moIdentifier`. Format adresu karty w serwisie BZP trzeba jeszcze potwierdzić ręcznie. Pełna treść ogłoszenia jest zawsze dostępna w zakładce „Źródła”.
- Propozycje ryzyk są regułowe (słowa kluczowe). Model językowy do przyczyny, skutku i kategorii to kolejny etap.

## Usługi, licencje, miejsce przetwarzania

- Dane pochodzą z publicznego API BZP (ezamowienia.gov.pl). Odczyt nie wymaga procedury integracyjnej.
- Przetwarzanie odbywa się lokalnie w SQLite.
- Zależności: Streamlit (Apache 2.0), pandas (BSD), openpyxl (MIT), requests (Apache 2.0).
