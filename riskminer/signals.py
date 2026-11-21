"""Sygnały z materiału eksperckiego (pkt 4.1 „Zmiany i wydarzenia”), których nie da się wyczytać
z samych kwot i terminów: unieważnienie, powtórzone postępowanie, zmiana wykonawcy, odstąpienie
lub rozwiązanie umowy, niewykonanie umowy. Czyste funkcje – pipeline zamienia wynik na zdarzenia.
"""
import re

# art. 255 Pzp – przesłanki unieważnienia -> (kategoria ryzyka, opis)
CANCEL_BASIS = {
    1: ("R11", "nie złożono żadnej oferty"),
    2: ("R11", "wszystkie oferty zostały odrzucone"),
    3: ("R13", "cena najkorzystniejszej oferty przewyższa kwotę przeznaczoną na sfinansowanie zamówienia"),
    4: ("R11", "oferty o takiej samej cenie lub koszcie, bez możliwości wyboru"),
    5: ("R06", "istotna zmiana okoliczności – wykonanie zamówienia nie leży w interesie publicznym"),
    6: ("R11", "niemożliwa do usunięcia wada postępowania"),
    7: ("R12", "wykonawca uchylił się od zawarcia umowy lub wniesienia zabezpieczenia"),
    8: ("R13", "nie przyznano środków z funduszy UE, które miały sfinansować zamówienie"),
}
TERMINATION = r"odst[aą]pi\w*|rozwiąza\w* umow\w*|rozwiązani\w* umow\w*|wypowiedz\w* umow\w*"


def cancellation(result_text, basis_text=None, reason_text=None):
    """Ogłoszenie o wyniku: czy postępowanie (część) zakończyło się unieważnieniem.
    Zwraca None albo {code, basis, label, reason}."""
    if not re.search(r"unieważni", result_text or "", re.I):
        return None
    m = re.search(r"art\.\s*255\s*pkt\s*(\d)", basis_text or "", re.I)
    point = int(m.group(1)) if m else None
    code, label = CANCEL_BASIS.get(point, ("R11", "przesłanka nieustalona"))
    reason = (reason_text or "").strip()
    if point is None and re.search(r"przewyższa kwotę|przekracza kwotę", reason, re.I):
        code, label = CANCEL_BASIS[3]
    return {"code": code, "basis": (basis_text or "").strip() or None, "label": label, "reason": reason or None}


def contractor_change(legal_basis):
    """Zmiana umowy na podstawie art. 455 ust. 1 pkt 2 Pzp = zmiana wykonawcy."""
    return bool(re.search(r"455\s*ust\.\s*1\s*pkt\s*2(?!\d)", legal_basis or "", re.I))


def termination(text):
    """Odstąpienie, rozwiązanie albo wypowiedzenie umowy w tekście – zwraca dopasowany fragment albo None."""
    m = re.search(TERMINATION, text or "", re.I)
    return m.group(0) if m else None


def not_executed(executed_text):
    """„Czy umowa została wykonana: Nie”."""
    return (executed_text or "").strip().lower().startswith("nie")


def similar_title(a, b, threshold=0.6):
    """Czy dwa tytuły zamówień opisują ten sam przedmiot (udział wspólnych rdzeni słów)."""
    from .matcher import _fold, stem, tokens
    sa = {stem(_fold(t)) for t in tokens(a)}
    sb = {stem(_fold(t)) for t in tokens(b)}
    if not sa or not sb:
        return False
    return len(sa & sb) / min(len(sa), len(sb)) >= threshold
