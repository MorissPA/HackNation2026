# Risk Miner – prototyp

Aplikacja dla eksperta inwestycji wodno-ściekowych. Importuje arkusz projektów i automatycznie pobiera dane z Biuletynu Zamówień Publicznych (BZP). Z tych danych buduje kartę przypadku: postępowanie, umowy, zmiany, oś czasu, fakty z dowodem, obliczenia, propozycje ryzyk R01–R15 i braki danych.

## Uruchomienie

Wymagania: Python 3.9+ i Node.js 18+.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cd web && npm install
npm run dev        # API (FastAPI) na :8000 + interfejs (Vite) na http://localhost:5173
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
| `riskminer/expert.py` | Decyzje eksperta (ryzyka, powiązania KPO) – wspólne dla API i Streamlit. |
| `api.py` | REST API (FastAPI) dla interfejsu w Vite; serwuje też zbudowany `web/dist`. |
| `web/` | Interfejs: Vite + React + TypeScript (Baza inwestycji z kartą projektu, Weryfikacja eksperta, Analiza nowego projektu – szkielet). |
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
