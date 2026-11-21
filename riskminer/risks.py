"""Katalog ryzyk R01–R15 (z materiału eksperckiego organizatora) + regułowe propozycje kategorii.

Regułowe dopasowanie to punkt startowy: wynik zawsze jest 'propozycją' z cytatem,
którą zatwierdza ekspert. Oddzielną analizę LLM można uruchomić na karcie projektu.
"""
import re

CATALOG = [
    ("R01", "Niepełny lub niespójny zakres", "Błędna wycena, pominięcie lub dublowanie robót, zmiana zakresu, roboty dodatkowe, roszczenie albo spór o wynagrodzenie."),
    ("R02", "Niedostateczne rozpoznanie stanu istniejącego", "Przeprojektowanie, nieprzewidziane roboty, przestoje, wzrost kosztu albo wydłużenie terminu."),
    ("R03", "Kolizje, dostęp do terenu i prawa do nieruchomości", "Brak możliwości rozpoczęcia części robót, zmiana trasy lub technologii, wstrzymanie prac albo roszczenia."),
    ("R04", "Decyzje, pozwolenia i uzgodnienia zależne od podmiotów trzecich", "Opóźnienie rozpoczęcia lub kontynuacji prac, zmiana warunków realizacji albo brak możliwości użytkowania obiektu."),
    ("R05", "Niejasny lub nieadekwatny podział odpowiedzialności", "Luka odpowiedzialności, dublowanie prac, odmowa wykonania, roszczenie i spór o koszt lub termin."),
    ("R06", "Nierealistyczny harmonogram i nieuwzględnione zależności", "Opóźnienie, kary, kumulacja prac, presja na skrócenie prób i badań albo pogorszenie jakości."),
    ("R07", "Nieprzewidziane zmiany i roboty dodatkowe", "Wstrzymanie robót, negocjacje, aneks, roszczenie, przekroczenie budżetu albo spór o odpowiedzialność."),
    ("R08", "Model wynagrodzenia niedopasowany do niepewności zakresu", "Zawyżona rezerwa w cenie albo niedoszacowanie, problemy płynnościowe i spory o zakres objęty wynagrodzeniem."),
    ("R09", "Niejednoznaczne lub niemierzalne wymagania techniczne", "Niewłaściwy dobór rozwiązania, przeprojektowanie, trudność w potwierdzeniu zgodności, problem z odbiorem."),
    ("R10", "Niedookreślone próby, rozruch i odbiór", "Wykonane roboty nie mogą zostać odebrane; opóźnia się użytkowanie i rozliczenie; powstaje spór o osiągnięcie parametrów."),
    ("R11", "Postępowanie podatne na odwołanie lub ograniczenie konkurencji", "Przedłużenie albo unieważnienie postępowania, słabsza konkurencja, wyższa cena lub wybór rozwiązania nieadekwatnego do potrzeb."),
    ("R12", "Niewystarczająca zdolność wykonawcy lub łańcucha dostaw", "Opóźnienie, zamiana materiałów lub urządzeń, problemy jakościowe i finansowe albo przerwanie realizacji."),
    ("R13", "Ryzyko finansowania, budżetu i płatności", "Ograniczenie zakresu, opóźnione płatności, utrata dofinansowania, brak środków na niezbędne zmiany albo problemy płynnościowe."),
    ("R14", "Nadmierne koszty eksploatacji i utrzymania", "Obiekt spełnia wymagania inwestycyjne, ale jest drogi, trudny lub niestabilny w eksploatacji."),
    ("R15", "Nieosiągnięcie efektu technologicznego, użytkowego lub środowiskowego", "Brak wymaganej jakości lub wydajności, ograniczenie użytkowania, konieczność dodatkowych prac, ryzyko sankcji albo utraty efektu projektu."),
]
NAMES = {c: n for c, n, _ in CATALOG}

# (kod, regex) – sygnał w treści przyczyny/opisu zmiany
RULES = [
    ("R04", r"pozwoleni\w* wodnoprawn|decyzj\w* (o )?(środowiskow|pozwoleniu)|uzgodnie\w*|postępowani\w* administracyjn|wody polskie|konserwator|RDOŚ|zmian\w* terminu załatwienia|przedłuż\w* postępowania"),
    ("R07", r"robót? dodatkow|roboty dodatkowe|nieprzewidzian|zwiększeni\w* zakresu"),
    ("R01", r"(nieprzewidzian|nieujęt|pominięt)\w* w (PFU|Programie Funkcjonalno|dokumentacji|przedmiarze)|niekompletn\w* dokumentacj|błęd\w* w dokumentacj"),
    ("R02", r"stan\w* istniejąc|azbest|inspekcj\w* TV|nieznan\w* (uzbrojeni|infrastruktur)|warunk\w* gruntow"),
    ("R03", r"kolizj|dostęp\w* do (terenu|nieruchomości)|właściciel|służebnoś|wejści\w* w teren"),
    ("R06", r"warunk\w* atmosferyczn|okres\w* zimow|harmonogram"),
    ("R12", r"dostaw\w* (urządzeń|materiałów)|niedostępnoś|upadłoś|zmian\w* podwykonawc"),
    ("R13", r"dofinansowani|środk\w* finansow|budżet"),
    ("R10", r"rozruch|odbior\w* końcow|próby"),
    ("R15", r"efekt\w* ekologiczn|parametr\w* ścieków"),
]


def propose(text: str):
    """Zwraca listę (kod, dopasowany fragment) – bez duplikatów, w kolejności reguł."""
    out, seen = [], set()
    for code, rx in RULES:
        m = re.search(rx, text or "", re.I)
        if m and code not in seen:
            seen.add(code)
            out.append((code, m.group(0)))
    return out
