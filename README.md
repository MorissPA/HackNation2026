# Risk Miner – prototyp

Aplikacja dla eksperta inwestycji wodno-ściekowych. Importuje arkusz projektów i automatycznie pobiera dane z Biuletynu Zamówień Publicznych (BZP). Z tych danych buduje kartę przypadku: postępowanie, umowy, zmiany, oś czasu, fakty z dowodem, obliczenia, propozycje ryzyk R01–R15 i braki danych.

## Uruchomienie

Wymagania: Python 3.9+ i Node.js 18+.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cd web && npm install
npm run dev        # API (FastAPI) na :8080 + interfejs (Vite) na http://localhost:5173
```

W interfejsie kliknij **Importuj paczkę organizatora** (plik `../Risk_Miner_dane_projekty.xlsx`), a potem **Pobierz z BZP wszystkie rekordy**.

Inne sposoby uruchomienia:

| Polecenie | Co robi |
|---|---|
| `cd web && npm start` | buduje interfejs i serwuje całość z jednego procesu na http://localhost:8000 |
| `.venv/bin/uvicorn api:app --port 8000` | samo REST API (dokumentacja: http://localhost:8000/docs) |
| `.venv/bin/streamlit run app.py` | wcześniejszy interfejs w Streamlit, http://localhost:8501 (ta sama baza) |
| `.venv/bin/python cli.py import ../Risk_Miner_dane_projekty.xlsx` | import arkusza z terminala |
| `.venv/bin/python cli.py fetch RM-2026-003` | pobranie jednego rekordu z BZP |

Inne polecenia: `cli.py fetch --all` (wszystkie rekordy), `cli.py show RM-2026-003` (podsumowanie karty w terminalu).

Konfiguracja przez zmienne środowiskowe ([riskminer/config.py](riskminer/config.py)):

| Zmienna | Domyślnie | Opis |
|---|---|---|
| `RISKMINER_DB` | `data/riskminer.sqlite` | plik SQLite (w kontenerze na trwałym wolumenie) |
| `BZP_MIRROR_BASE` | `https://bzp.cytr.us/mo-board/api/v1` | kopia ogłoszeń wod-kan od organizatora, źródło główne (pusta wartość = tylko oficjalne API) |
| `BZP_MIN_INTERVAL_S` | `2.2` | odstęp między zapytaniami do oficjalnego API BZP (limit 30/min) |
| `BZP_OFFICIAL_ORG_SCAN` | `0` | `1` = przy włączonej kopii i tak rób pełny przegląd ogłoszeń zamawiającego w oficjalnym API |
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
| `riskminer/analysis.py` | Analiza nowej inwestycji: cechy z opisu/PDF/DOCX, ranking podobnych przypadków, koszty i terminy, flagi i rekomendacje, checklista wodociągowa, eksport CSV/JSON. |
| `riskminer/expert.py` | Decyzje eksperta (ryzyka, powiązania KPO) – wspólne dla API i Streamlit. |
| `api.py` | REST API (FastAPI) dla interfejsu w Vite; serwuje też zbudowany `web/dist`. |
| `web/` | Interfejs: Vite + React + TypeScript (Baza inwestycji z kartą projektu, Weryfikacja eksperta, Analiza nowego projektu). |
| `app.py` | Wcześniejszy interfejs w Streamlit (te same funkcje, ta sama baza). |

## Źródło: BZP – jak łączymy ogłoszenia

**Skąd dane.** Głównym źródłem jest kopia ogłoszeń o robotach wod-kan udostępniona przez organizatora (`bzp.cytr.us`). Ma ten sam endpoint `/notice` co API BZP i nie ma limitu zapytań. Pełne przeliczenie 22 rekordów przy pustym cache trwa ok. 1 minuty. Kopia różni się od oficjalnego API:
- nie ma wyszukiwarki `Board/Search` – emulujemy ją zapytaniami `/notice` per typ ogłoszenia z filtrem `OrderObject` i filtrowaniem po zamawiającym po stronie klienta,
- nie stronicuje (maks. 500 wyników na zapytanie) – przy ogólnych frazach wynik bywa ucięty, co aplikacja zapisuje w logu,
- zawiera tylko 4 typy ogłoszeń: o zamówieniu, o wyniku, o zmianie umowy, o wykonaniu umowy. **Brak ogłoszeń o zmianie ogłoszenia** (modyfikacje SWZ/terminów), więc nie ma ich na osi czasu,
- nie podaje `moIdentifier`, więc link „Otwórz w BZP” zostaje z wcześniejszego pobrania z oficjalnej wyszukiwarki, jeśli takie było.

Oficjalne API jest zapasem: używamy go, gdy kopia nie odpowiada albo nie znajduje ogłoszenia o podanym numerze. W regresji na 22 rekordach z kopii poszło 274 zapytań, a z oficjalnego API 1 (numer Wolina, którego nie ma nigdzie). Powiązania, umowy, kwoty i obliczenia wyszły identyczne jak przy samym oficjalnym API.

1. `GET /Board/Search?NoticeNumber=<numer z arkusza>` zwraca ogłoszenie bazowe, a z nim **identyfikator postępowania (OCID)** i identyfikator zamawiającego.
2. Ogłoszenia powiązane (wynik, zmiany umowy, wykonanie):
   - Wyszukiwarka ignoruje filtr po OCID. Dlatego szukamy po `OrganizationId` i początku tytułu (`OrderObject` dopasowuje podciąg).
   - Gdy brakuje ogłoszenia o wyniku albo o wykonaniu, przeglądamy wszystkie ogłoszenia zamawiającego od daty ogłoszenia bazowego (`PageNumber`, po 10 na stronę).
   - Wyniki zawsze **filtrujemy po OCID**.
3. Treść każdego ogłoszenia pobiera `GET /notice?NoticeType&PublicationDateFrom/To&NoticeNumber`. Okno dat wynosi ±1 dzień, bo API inaczej gubi ogłoszenia z wczesnych godzin. Pełny HTML zapisujemy w bazie, dzięki czemu dowód da się otworzyć w aplikacji.
4. **Ogłoszenie z arkusza niedostępne w API** (np. Wolin, `2023/BZP 00110672/01`). Szukamy ogłoszeń zamawiającego (zgodny NIP) po fragmentach nazwy przedsięwzięcia i sprawdzamy, które w treści cytują numer z arkusza. OCID bierzemy z takiego ogłoszenia. Metoda powiązania to `odwołanie_w_ogłoszeniu`, cytat trafia do dowodu, a w brakach pojawia się informacja o niedostępnym ogłoszeniu bazowym.
5. **Bez ogłoszenia o wyniku** umowy budujemy z ogłoszeń o wykonaniu, po jednej na część. Numer części odczytujemy z nazwy zamówienia („Umowa dla części nr 2”). Termin podany jako czas trwania („5 miesiące”) przeliczamy od daty zawarcia umowy i zapisujemy jako obliczenie z formułą.
6. **Rekordy KPO (bez numeru BZP)**, np. Modlikowice. Zgodnie z treścią zadania, gdy nie ma wspólnego identyfikatora, dopasowujemy po **nazwie, zamawiającym, miejscu, CPV, wartości i datach** i pokazujemy podstawę oraz poziom pewności ([riskminer/matcher.py](riskminer/matcher.py)).
   - **Zamawiający (NIP)** to warunek konieczny: kandydatów szukamy tylko wśród ogłoszeń tego NIP-u, od roku poprzedzającego nabór KPO.
   - Pozostałe kryteria są oceniane jako *pasuje*, *nie pasuje* albo *brak danych*:

     | Kryterium | Kiedy pasuje |
     |---|---|
     | nazwa | co najmniej połowa słów nazwy przedsięwzięcia jest w tytule zamówienia, a zamówienie dotyczy robót, nie samej dokumentacji |
     | miejsce | miejscowość z nazwy przedsięwzięcia jest w tytule |
     | CPV | postępowanie ma kod robót z zakresu przedsięwzięcia (np. 452324 kanalizacja, 4523215 wodociąg, 452521 oczyszczalnia) |
     | wartość | umowy mają 30–125% wartości przedsięwzięcia KPO |
     | daty | pierwsze ogłoszenie przypada na okres naboru KPO |

   - **Poziom pewności:**
     - wysoka: wszystkie sprawdzalne kryteria spełnione (co najmniej 5),
     - średnia: najwyżej jedno niespełnione,
     - niska: pozostałe.
   - **Propozycja automatyczna** (status *proponowane*) powstaje tylko wtedy, gdy dokładnie jeden kandydat ma pewność wysoką. Gdy kilku spełnia wszystko, wybieramy ten, którego tytuł zawiera najwięcej słów z nazwy przedsięwzięcia, o ile jest jeden taki, i piszemy to w uzasadnieniu. W każdym innym przypadku kandydata wybiera ekspert.
   - Ekspert może potwierdzić propozycję, wybrać innego kandydata albo ją odrzucić. Odrzucony OCID jest pomijany w kolejnych rankingach, a każda decyzja trafia do `expert_decision`.
   - Na 7 rekordach KPO z paczki nowe reguły wskazały te same postępowania co wcześniejsza wersja z punktami (7/7). W 3 przypadkach (Grodzisko Dolne, Kleszczewo, Zduny) rozstrzygnęła reguła remisu.
7. **Części zamówienia.** Ogłoszenie o wyniku ma sekcje „Część N”. Rekord ze `Zakres rekordu = część 2` dostaje tylko umowę z części 2. Ogłoszenia o wykonaniu i o zmianie nie podają numeru części, więc przypisujemy je do umowy po wartości, dacie zawarcia i NIP wykonawcy.

## Analiza nowego projektu

1. **Cechy z opisu** (tekst albo PDF z warstwą tekstową / DOCX). Każda cecha ma fragment źródłowy:
   - podsektor główny i dodatkowe (taksonomia organizatora),
   - rodzaj prac, formuła realizacji,
   - skala (km, RLM, m³/d, przyłącza), budżet, termin,
   - znane ograniczenia (odbiornik ścieków i pozwolenie wodnoprawne, grunty prywatne, kolizje, przekroczenia, obiekt w eksploatacji, azbest, warunki gruntowe).
2. **Profile przypadków z bazy.** Opis przedmiotu z ogłoszenia o zamówieniu (albo opis KPO), wartości umów, wypłaty, terminy, opóźnienia i ryzyka. Ryzyka zatwierdzone przez eksperta ważą 1, propozycje 0,5, odrzucone są pomijane.
3. **Ranking podobieństwa** (treść zadania: łączyć dane strukturalne z treścią opisów i wyjaśniać, które cechy przesądziły o podobieństwie):
   - porównywane cechy: podsektor główny i dodatkowe, rodzaj prac, formuła, budżet względem wartości umów, długość sieci, treść opisu (wspólne rdzenie słów), znane ograniczenia,
   - każda cecha waży tyle samo; *pasuje* = 1, *częściowo* = ½, cechy bez danych nie są liczone,
   - wynik ma postać „pasuje 5 z 7”,
   - kolejność: najpierw ten sam podsektor główny, potem odsetek pasujących cech, a przy remisie podobieństwo treści.
4. **Raport:**
   - wzrost wypłaty, opóźnienie i okres realizacji z liczebnością próby; przy n ≥ 3 mediana i zakres, przy mniejszej próbie wartości per przypadek z informacją, czego brakuje,
   - poziom pewności prognozy:
     - wysoka: n ≥ 5 i wszystkie przypadki z tego samego podsektora,
     - średnia: n ≥ 3 i co najmniej 2 z tego samego podsektora,
     - niska: pozostałe,
   - flagi R01–R15 z siłą sygnału, podstawą i dowodami, a do każdej działanie i zapis do sprawdzenia w SWZ lub umowie,
   - dla sieci wodociągowych checklista 9 pytań z poradnika organizatora.
5. **Eksport** do CSV (separator `;`, z BOM dla Excela) i JSON.

Ogłoszenie o wykonaniu umowy, które podaje „wykonana należycie: Nie” albo wypłatę poniżej 90% wartości umowy, daje zdarzenie typu `sygnał` i propozycję R12 do oceny eksperta.

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
