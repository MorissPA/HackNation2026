# Risk Miner – prototyp

Aplikacja dla eksperta inwestycji wodno-ściekowych. Importuje arkusz projektów i automatycznie pobiera dane z Biuletynu Zamówień Publicznych (BZP). Z tych danych buduje kartę przypadku: postępowanie, umowy, zmiany, oś czasu, fakty z dowodem, obliczenia, propozycje ryzyk R01–R15 i braki danych.

## Uruchomienie w kontenerze (wariant demonstracyjny)

Wymagania: Docker z Compose (np. Docker Desktop). Z katalogu `risk_miner/`, gdy katalog wyżej leży paczka organizatora z plikiem `Risk_Miner_dane_projekty.xlsx`:

```bash
docker compose up -d --build
```

Aplikacja działa na **http://localhost:8000** (jeden port: interfejs i API).

- **Dane:** wolumen `riskminer-data` (`/data` w kontenerze) trzyma bazę SQLite, cache BZP/BIP i model GGUF. Przetrwa `docker compose restart` oraz `down` i `up`. Wyczyścić go można przez `docker compose down -v`.
- **Arkusz organizatora:** montowany tylko do odczytu jako `/import/Risk_Miner_dane_projekty.xlsx`. Przy pustej bazie importuje się automatycznie przy starcie (`RISKMINER_AUTOIMPORT=1`). Inne położenie pliku: `RISKMINER_XLSX=/ścieżka/do/pliku.xlsx docker compose up -d`. Bez pliku arkusz można wgrać w interfejsie przyciskiem „Wgraj XLSX / CSV”.
- **Model Bielik-11B** (~6,7 GB, sprawdzany SHA-256) jest wspólny z uruchomieniem bez kontenera: compose podłącza katalog `data/llm` z hosta jako `/data/llm` (inne położenie: `RISKMINER_MODELS=/ścieżka`). Gdy pliku brak, aplikacja pobiera go tam przy pierwszej analizie. Kontener nie ma dostępu do GPU Maca, więc model liczy na CPU: **ok. 2–2,5 min na fragment** (pierwsze wywołanie z ładowaniem modelu dłużej), a analiza wszystkich 62 fragmentów trwa ok. 2 godzin. Potrzeba ok. 8 GB pamięci dla Dockera (Ustawienia → Resources); kontekst modelu w kontenerze to 4096 tokenów (`LLM_CONTEXT`). Na Macu z działającym Metal można uruchomić aplikację natywnie z `LLM_GPU_LAYERS=-1 npm run start` (w poprzednim pomiarze GPU ok. 6 s na fragment).
- **Konfiguracja modelu w kontenerze:** przekaż zmienne z powłoki lub z pliku przez `docker compose --env-file .env.local up -d`. Zobacz [llm.env.example](llm.env.example). Własny GGUF umieść w katalogu montowanym jako `/data/llm` i wskaż ścieżkę wewnątrz kontenera. Dla Ollamy podaj adres dostępny z kontenera.
- **Inny port:** `RISKMINER_PORT=9000 docker compose up -d`.
- **macOS:** paczka organizatora leży zwykle w folderze Pobrane. Przy pierwszym starcie macOS pyta, czy Docker może uzyskać dostęp do tego folderu. Bez zgody kontener zatrzymuje się w stanie „Created”. Zgodę można też włączyć w Ustawienia systemowe → Prywatność i ochrona → Pliki i foldery → Docker.
- **Pierwsza budowa** obrazu trwa ok. 20 minut, bo `llama-cpp-python` kompiluje się ze źródeł. Obraz waży ok. 1,1 GB, a kolejne budowy korzystają z cache.

Test wdrożenia (Docker Desktop 29.9, arm64), wszystko ✅:

| Krok | Wynik |
|---|---|
| start z pustym wolumenem | autoimport 22 projektów, healthcheck „healthy” |
| Steklin (RM-2026-003) | 5 ogłoszeń, +40,3% wypłaty, 277 dni opóźnienia – jak lokalnie |
| analiza LLM (Qwen, pierwsza wersja) | model pobrany do wolumenu i sprawdzony (5,5 min), 3 propozycje: R07 ×2, R04 |
| analiza LLM (Bielik-11B, 21.11) | model z `data/llm` hosta, CPU, 3 fragmenty RM-2026-003 (1 duplikat) w 4 min 53 s, 2 propozycje: R04 i R07, pewność wysoka; pamięć kontenera 3,6 GB |
| `docker compose restart` oraz `down` + `up` | dane, propozycje i model zachowane; brak ponownego importu; ponowna analiza z zapisanych wyników w 0,01 s |

## Uruchomienie lokalne (praca nad kodem)

Wymagania: Python 3.9+ i Node.js 18+.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cd web && npm install
npm run dev        # API (FastAPI) na :8000 + interfejs (Vite) na http://localhost:5173
```

W interfejsie kliknij **Importuj paczkę organizatora** (plik `../Risk_Miner_dane_projekty.xlsx`), a potem **Pobierz z BZP wszystkie rekordy**.

Testy (z katalogu głównego repozytorium):

```bash
.venv/bin/pip install -r requirements-test.txt
.venv/bin/python -m unittest discover -s tests
cd web && npm test
```

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
| `LLM_PROVIDER` / `LLM_MODEL` / `LLM_API_KEY` | llama.cpp / Bielik-11B lokalnie | dostawca, model i klucz backendu. Przykłady w [llm.env.example](llm.env.example) |

## Analiza przyczyn przez model językowy

W karcie projektu wybierz **Analizuj przyczyny i ryzyka przez LLM**. Równoważne polecenie CLI:

```bash
.venv/bin/python cli.py llm RM-2026-003
```

Domyślnie backend wykonuje analizę w swoim procesie za pomocą biblioteki `llama-cpp-python`, modelem [Bielik-11B v2.6 Instruct](https://huggingface.co/speakleash/Bielik-11B-v2.6-Instruct-GGUF) (SpeakLeash, polski model, Apache 2.0) w kwantyzacji Q4_K_M. Przy pierwszej analizie aplikacja korzysta z pliku `data/llm/bielik-11b-v2.6.gguf`; jeśli go brakuje, pobiera około 6,7 GB z przypiętej wersji i sprawdza sumę SHA-256. Kolejne analizy działają lokalnie, również offline.

Własny plik GGUF można wskazać przez `LLM_MODEL_PATH` i opisać przez `LLM_MODEL`. Opcjonalne ustawienia Ollamy i Anthropic znajdują się w [llm.env.example](llm.env.example).

### Wybór modelu i ocena jakości

| Model | Zbiór testowy (49 fragmentów) | Czas | Gdzie |
|---|---|---|---|
| **Bielik-11B v2.6 Instruct** (SpeakLeash, Q4_K_M, ~6,7 GB) – **domyślny** | **81,6%** – 37 trafnych, 6 częściowo, 6 błędnych | ~6 s / fragment (Mac, GPU Metal) | wszędzie (lokalnie, CLI, Docker) |
| Qwen2.5-1.5B Instruct (Q4_K_M, ~1,1 GB) – wcześniejszy model, do porównań | 56,1% – 26 trafnych, 3 częściowo, 20 błędnych | ~2,5 s / fragment (CPU) | tylko po ustawieniu `LLM_MODEL=qwen2.5-1.5b-instruct` |

Model wybiera `LLM_MODEL` (`bielik-11b-v2.6-instruct` albo `qwen2.5-1.5b-instruct`); oba pliki pobierają się automatycznie z przypiętej wersji i są sprawdzane sumą SHA-256. Domyślnie model korzysta z CPU (`LLM_GPU_LAYERS=0`) i kontekstu 4096 tokenów. W natywnym środowisku z działającym Metal można jawnie ustawić `LLM_GPU_LAYERS=-1`.

Zbiór testowy to [docs/llm_zbior_testowy.csv](docs/llm_zbior_testowy.csv): każdy unikalny fragment źródłowy z oczekiwaną kategorią przyczyny (lub „brak”, gdy dokument nie podaje przyczyny). Etykiety „zespół” zastępuje automatycznie decyzja eksperta z kolejki weryfikacji. Ocena:

```bash
.venv/bin/python cli.py eval-llm
```

Wynik trafia do `docs/llm_ewaluacja_<model>.md`. Przykłady eksperta z tego samego projektu są przy ocenie pomijane. Analiza wszystkich fragmentów naraz: przycisk w zakładce „Dane i reguły” albo `cli.py llm --all`.

Model dostaje katalog R01–R15, kontekst zdarzenia i zapisany fragment dowodowy zmiany umowy lub dokumentu BIP. Przy odrzuconym powiązaniu BIP dokument jest pomijany. Model proponuje jedną główną kategorię i przyczynę albo wskazuje brak podstaw. Aplikacja pobiera cytat ze wskazanego przez model fragmentu oraz zapisuje numer źródła, adres i sekcję. Trafność interpretacji ocenia ekspert w dotychczasowym panelu. Zakres analizy ogranicza się do fragmentów już wydobytych na kartę projektu.

Powtórzenie analizy wykorzystuje zapisane wyniki dla tego samego tekstu, dostawcy, modelu i instrukcji. Błąd usługi lub walidacji pozwala ponowić wywołanie. Ukończone wcześniej fragmenty i decyzje eksperta pozostają zapisane.

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
| `riskminer/bip.py` | Drugie źródło: BIP gminy (d-bip.pl) – przegląd sekcji, odczyt dokumentów, powiązanie z projektem z cytatem i stroną. |
| `riskminer/expert.py` | Decyzje eksperta (ryzyka, powiązania KPO) – wspólne dla API i Streamlit. |
| `api.py` | REST API (FastAPI) dla interfejsu w Vite; serwuje też zbudowany `web/dist`. |
| `web/` | Interfejs: Vite + React + TypeScript – cztery zakładki: Nowa inwestycja (ocena ryzyk, checklista, podobne przypadki, eksport), Do weryfikacji (kolejka eksperta z dowodem w kontekście dokumentu), Baza projektów (filtry, szuflada z hierarchią powiązań, pełna karta przypadku), Dane i reguły (import, synchronizacja BZP, otwarty katalog ryzyk, reguły dla modelu). Przełącznik rozmiaru tekstu i tryb wysokiego kontrastu. |
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

## Sygnały z materiału eksperckiego

Poza kwotami i terminami program wyłapuje zdarzenia z listy „Zmiany i wydarzenia” w materiale eksperckim ([riskminer/signals.py](riskminer/signals.py)). Każde daje zdarzenie typu `sygnał` z cytatem i propozycję kategorii do oceny eksperta:

| Sygnał | Skąd | Propozycja |
|---|---|---|
| unieważnienie postępowania lub części | ogłoszenie o wyniku, pkt „Podstawa prawna” i „Przyczyna unieważnienia” | wg art. 255: brak ofert lub odrzucone → R11, cena ponad budżet → R13, uchylenie się wykonawcy → R12 |
| powtórzone postępowanie | wcześniejsze unieważnione postępowanie zamawiającego o podobnym tytule (do 2 lat wstecz) | jak wyżej + obliczenie „czas stracony na powtórzenie” |
| zmiana wykonawcy | zmiana umowy na podstawie art. 455 ust. 1 pkt 2 | R12 |
| odstąpienie, rozwiązanie, wypowiedzenie umowy | opis zmiany lub informacje dodatkowe w ogłoszeniu o wykonaniu | R12 |
| niewykonanie / nienależyte wykonanie umowy | ogłoszenie o wykonaniu | R12 |
| wypłata poniżej 90% wartości umowy | ogłoszenie o wykonaniu | — (sygnał do wyjaśnienia) |

W paczce: Gościeradów (RM-2026-006) – pierwsze postępowanie z 2023 r. unieważniono, bo nie wpłynęła żadna oferta, a powtórzenie ogłoszono 223 dni później; 4 umowy wykonane nienależycie; 2 umowy z wypłatą poniżej 90% wartości.

## Drugie źródło: BIP gminy

Konfiguracja jest w [bip_sources.json](bip_sources.json): NIP zamawiającego → adres BIP. Na razie obsługujemy system **d-bip.pl** (sekcje `?strona=N`, stronicowanie `,m0,sN,pK.html`, załączniki `pliki/…`), z którego korzysta wiele gmin. Kolejną gminę dodaje się wpisem w tym pliku. Zmienna `BIP_SOURCES_FILE` pozwala podać inny plik konfiguracji. Kod jest w [riskminer/bip.py](riskminer/bip.py).

Przy pobieraniu projektu, którego zamawiający ma skonfigurowany BIP:
1. Przeglądamy wszystkie sekcje i strony BIP, a dla każdego załącznika zapisujemy tytuł, sekcję i datę publikacji. Strony są w cache przez 24 h. Pierwszy przegląd BIP Zagrodna (390 stron, 1670 załączników) trwa ok. 5 minut, kolejne korzystają z cache.
2. Czytamy dwa rodzaje dokumentów:
   - załączniki z numerem projektu, postępowania lub nazwą wykonawcy w tytule oraz te, których tytuł wymienia miejscowość i zakres projektu lub zależny obiekt,
   - 4 najnowsze plany finansowe (WPF, plan postępowań).
   PDF czytamy strona po stronie, a do tego DOCX i ODT. Skany bez warstwy tekstowej i pliki `.doc` zostają z tytułem i datą jako dowodem i trafiają do braków.
3. Powiązanie z projektem ma cytat i numer strony:
   - **przedsięwzięcie**: miejscowość i zakres projektu (np. kanalizacja w Modlikowicach),
   - **powiązana inwestycja**: miejscowość i obiekt, od którego projekt zależy według opisu KPO (np. oczyszczalnia, do której wpięta będzie sieć).
4. Każdy dokument daje zdarzenie `dokument BIP` na osi czasu. Reguły ryzyk działają też na tytule i cytacie, np. „zmiana terminu załatwienia sprawy” daje R04. Kwotę WPF odczytujemy z pozycji tabeli zawierającej dowód. Dla zależnej inwestycji kwota ma odrębny poziom i nie zasila kosztu umowy.
5. W zakładce **Źródła** można potwierdzić lub odrzucić powiązanie z BIP. Decyzja przechodzi do historii i obowiązuje po kolejnym pobraniu. Odrzucony dokument pozostaje dostępny do ponownej oceny. Jego fakty i zdarzenia są pomijane na karcie i w analizie. Dopasowanie jedynie po wykonawcy jest kandydaturą do sprawdzenia.
6. Analiza treści dotyczy wybranych załączników. Identyfikator występujący wyłącznie wewnątrz pominiętego dokumentu może pozostać niewykryty. Przy skanie lub nieobsługiwanym formacie karta wskazuje ograniczenie i tytuł z wykazu BIP.

Wynik dla Modlikowic:
- 10 dokumentów: postępowanie środowiskowe dla oczyszczalni (obwieszczenia, decyzja, zmiana terminu załatwienia sprawy), zapytanie na przyłącze elektryczne oczyszczalni i 3 uchwały WPF,
- WPF podaje „Budowa oczyszczalni ścieków w Modlikowicach, 2023–2026, 13 700 000,00 zł” (str. 13),
- 2 propozycje R04 do oceny eksperta.

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

## Eksport bazy przypadków

W interfejsie (Baza projektów → „Cała baza JSON / CSV (ZIP)”), przez API (`/api/export?format=json` lub `csv`) albo z terminala:

```bash
.venv/bin/python cli.py export        # docs/przyklad_eksportu/risk_miner_baza.json i risk_miner_baza_csv.zip
```

JSON zawiera projekt po projekcie z relacjami: powiązanie → postępowanie → ogłoszenia, umowy ze zmianami, fakty i obliczenia z dowodem, zdarzenia ze statusem eksperta, braki, dokumenty BIP i historię decyzji. CSV to archiwum ZIP z 13 tabelami (separator `;`, UTF-8 z BOM) i plikiem z opisem. Dowody odrzucone przez eksperta są pomijane.

## Raport z testu

```bash
.venv/bin/python cli.py report        # zapisuje docs/raport_z_testu.md i docs/raport_polaczen.csv
```

Raport sprawdza każde połączenie rekordu z arkusza z postępowaniem w BZP na danych podmiotu i zamówienia:
- NIP zamawiającego z arkusza = NIP w ogłoszeniach,
- numer BZP z arkusza jest wśród ogłoszeń postępowania,
- tytuł zamówienia zawiera słowa nazwy przedsięwzięcia,
- dla rekordów „część N” przypisana jest umowa właściwej części,
- jest ogłoszenie o wykonaniu umowy.

Wynik: *poprawne*, *niepewne* (wymaga oceny eksperta) albo *błędne*. Uwagi o jakości danych są w osobnej kolumnie. Raport zawiera też wyniki analizy dwóch przykładowych nowych inwestycji.

Stan na paczce organizatora: 15 połączeń poprawnych, 7 niepewnych (6 propozycji KPO czekających na eksperta i Wolin, którego ogłoszenia nie zwraca API BZP), 0 błędnych.

## Model danych

Tabele: `project`, `procedure` (OCID), `project_link` (z metodą dopasowania, dowodem i statusem), `notice`, `contract` (OCID + część), `contract_change`, `fact`, `event`, `gap`, `expert_decision`, `import_run`/`import_row` i `http_cache`. Dokumenty BIP, powiązania i historię weryfikacji przechowują `document`, `document_link` i `document_review`.

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
- BIP jest skonfigurowany na razie dla jednej gminy (Zagrodno). Skany wymagają OCR, którego nie mamy, więc dla nich dowodem jest tytuł i data publikacji.
- Kilka ogłoszeń o wykonaniu tej samej umowy (korekty, np. Modlikowice) traktujemy tak: obowiązuje najnowsze, a różnice w kluczowych polach pokazujemy w brakach.
- Link „Otwórz w BZP” używa `moIdentifier`. Format adresu karty w serwisie BZP trzeba jeszcze potwierdzić ręcznie. Pełna treść ogłoszenia jest zawsze dostępna w zakładce „Źródła”.
- Propozycje regułowe powstają podczas pobierania. Propozycje LLM uruchamia użytkownik na karcie lub z CLI.

## Usługi, licencje, miejsce przetwarzania

**Licencja projektu:** MIT, zob. [LICENSE](LICENSE).

**Źródła danych (tylko odczyt danych publicznych):**
- Biuletyn Zamówień Publicznych: kopia ogłoszeń wod-kan udostępniona przez organizatora (`bzp.cytr.us`) i oficjalne API e-Zamówień (`ezamowienia.gov.pl`). Odczyt nie wymaga procedury integracyjnej.
- Biuletyny Informacji Publicznej gmin z `bip_sources.json` (obecnie BIP Gminy Zagrodno).
- Model Bielik-11B pobierany jednorazowo z Hugging Face (przypięta wersja), ze sprawdzeniem sumy SHA-256.

**Gdzie przetwarzane są dane:**
- Baza SQLite, cache zapytań, dokumenty i decyzje eksperta są lokalnie: na komputerze albo w wolumenie kontenera.
- Domyślny model językowy (Bielik-11B v2.6, llama.cpp) działa w procesie aplikacji na CPU. GPU można włączyć w konfiguracji natywnej. Fragmenty dokumentów nie opuszczają maszyny i nie jest potrzebny klucz API.
- Opcjonalnie można ustawić `LLM_PROVIDER=ollama` (serwer na wskazanym hoście) albo `LLM_PROVIDER=anthropic`. W tym drugim przypadku fragmenty trafiają do API Anthropic, zgodnie z warunkami i regionem konta, potencjalnie poza UE. Zmiana dostawcy nie wymaga zmian w kodzie.
- Aplikacja nie przetwarza danych osobowych poza tym, co jest w publicznych ogłoszeniach: nazwy zamawiających i wykonawców, a przy jednoosobowych firmach także imiona i nazwiska.

**Model i biblioteki:**

| Składnik | Wersja | Licencja |
|---|---|---|
| Qwen2.5-1.5B-Instruct (wagi GGUF, Q4_K_M) | – | Apache 2.0 |
| Bielik-11B-v2.6-Instruct (wagi GGUF, Q4_K_M, SpeakLeash) | – | Apache 2.0 |
| llama.cpp / llama-cpp-python | 0.3.19 | MIT |
| FastAPI | 0.128.8 | MIT |
| Uvicorn | 0.39.0 | BSD-3-Clause |
| Pydantic | 2.13.5 | MIT |
| requests | 2.32.5 | Apache 2.0 |
| pandas | 2.3.3 | BSD-3-Clause |
| openpyxl | 3.1.5 | MIT |
| pypdf | 6.21.4 | BSD-3-Clause |
| python-multipart | 0.0.20 | Apache 2.0 |
| Streamlit (interfejs pomocniczy) | 1.50.0 | Apache 2.0 |
| React, React DOM | 18.3.1 | MIT |
| Vite, @vitejs/plugin-react | 6.4.6, 4.7.0 | MIT |
| TypeScript | 5.9.3 | Apache 2.0 |
| concurrently (tylko tryb deweloperski) | 9.2.5 | MIT |
| Czcionki IBM Plex (Google Fonts) | – | SIL Open Font License 1.1 |
