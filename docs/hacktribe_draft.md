# Draft zgłoszenia – HackTribe (wyzwanie MFiPR „Risk Miner”)

## Tytuł

Risk Miner – pamięć instytucjonalna inwestycji wodno-kanalizacyjnych

## Krótki opis (ok. 300 znaków)

Risk Miner sam łączy rekordy projektów z ogłoszeniami BZP i dokumentami z BIP, buduje karty inwestycji z udokumentowanymi zdarzeniami, kosztami i terminami oraz proponuje ryzyka R01–R15 do oceny eksperta. Dla nowej inwestycji dobiera podobne przypadki, prognozuje odchylenia i rekomenduje działania.

## Opis

**Problem.** Wiedza o tym, co poszło nie tak w zrealizowanych inwestycjach, jest rozproszona w BZP, BIP-ach i aneksach. Osoba przygotowująca nowy projekt nie ma jej pod ręką.

**Co działa (na paczce organizatora, 22 projekty wod-kan):**
- **Automatyczne zasilanie.** Import arkusza organizatora. System sam pobiera ogłoszenia z BZP (kopia organizatora i oficjalne API jako zapas) i łączy je po numerze ogłoszenia, OCID i NIP. Rekordy KPO bez numeru BZP dopasowuje po nazwie, zamawiającym, miejscu, CPV, wartości i datach, z podstawą i poziomem pewności. Drugie źródło to BIP gminy, z dowodem w postaci cytatu i numeru strony.
- **Karta przypadku.** Postępowanie, umowy i części zamówienia, zmiany umów, oś czasu, braki danych. Każdy fakt prowadzi do źródła: numer ogłoszenia, sekcja, cytat, data pobrania. Obliczenia mają formułę: wzrost wypłaty, opóźnienie, przesunięcie terminu aneksem.
- **Ryzyka do weryfikacji.** Propozycje kategorii R01–R15 z reguł i z lokalnego modelu językowego (Qwen 2.5, llama.cpp, bez klucza API i bez wysyłania danych na zewnątrz). Każda ma przyczynę i cytat ze źródła. Ekspert akceptuje, poprawia albo odrzuca, a decyzje są zapisywane z historią i nie giną przy przeliczeniu.
- **Analiza nowej inwestycji.** Opis albo PDF/DOCX. System dobiera podobne przypadki i wyjaśnia, które cechy pasują. Pokazuje przedziały odchyleń kosztu i czasu z liczebnością próby i poziomem pewności, flagi ryzyk, działania, propozycje zapisów umownych i checklistę wodociągową z materiału eksperckiego. Wynik można wyeksportować do CSV i JSON.

**Przykład.** Steklin (oczyszczalnia „zaprojektuj i wybuduj”): wypłata wyższa o 40,3% od wartości umowy, wykonanie 277 dni po terminie pierwotnym. Dokumentacja wskazuje m.in. przedłużające się postępowanie wodnoprawne (R04). Liczby dotyczą całej umowy, a udział tego zdarzenia wymaga osobnego dowodu. Dla nowej oczyszczalni system wskazuje Steklin jako najbliższy przypadek i rekomenduje ustalenie odpowiedzialności za pozwolenie wodnoprawne w harmonogramie. Raport z testu połączeń: 15 poprawnych, 7 niepewnych (czekają na eksperta), 0 błędnych.

**Technologia.** Python (FastAPI), SQLite, React + Vite, lokalny model w procesie aplikacji. Uruchomienie jednym poleceniem `docker compose up` z trwałym wolumenem na dane i model. Dostawca modelu jest ustawiany w konfiguracji (lokalny, Ollama albo Anthropic).

**W toku do finału:** kolejne źródła (TED, KIO, NIK, BK2021, KPOŚK), OCR skanów, otwarty katalog ryzyk w panelu eksperta, monitoring projektów w toku i publiczny link do aplikacji.

## Linki

- Repozytorium: https://github.com/MorissPA/HackNation2026/tree/risk-miner-prototyp
- Aplikacja: link zostanie dodany przed zgłoszeniem końcowym

## Zespół

Uzupełnij imiona, nazwiska i role członków zespołu.
