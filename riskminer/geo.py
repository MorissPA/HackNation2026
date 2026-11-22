"""Moduł geolokalizacji i współrzędnych gmin dla mapy inwestycji."""
import re
import unicodedata

# Współrzędne stolic województw jako domyślne punkty zapasowe (lat, lon)
VOIVODESHIP_CENTROIDS = {
    "dolnośląskie": (51.1079, 17.0385),      # Wrocław
    "kujawsko-pomorskie": (53.0138, 18.5984), # Toruń
    "lubelskie": (51.2465, 22.5684),          # Lublin
    "lubuskie": (51.9356, 15.5062),           # Zielona Góra
    "łódzkie": (51.7592, 19.4560),            # Łódź
    "małopolskie": (50.0647, 19.9450),        # Kraków
    "mazowieckie": (52.2297, 21.0122),        # Warszawa
    "opolskie": (50.6751, 17.9213),           # Opole
    "podkarpackie": (50.0412, 21.9991),       # Rzeszów
    "podlaskie": (53.1325, 23.1688),          # Białystok
    "pomorskie": (54.3520, 18.6466),          # Gdańsk
    "śląskie": (50.2649, 19.0238),            # Katowice
    "świętokrzyskie": (50.8661, 20.6286),     # Kielce
    "warmińsko-mazurskie": (53.7784, 20.4801),# Olsztyn
    "wielkopolskie": (52.4064, 16.9252),      # Poznań
    "zachodniopomorskie": (53.4285, 14.5528), # Szczecin
}

# Współrzędne (szerokość, długość geograficzna) dla gmin i miast
LOCATION_COORDS = {
    "oława": (50.9419, 17.2947),
    "zagrodno": (51.1834, 15.9128),
    "czernikowo": (52.9515, 18.9407),
    "zławieś wielka": (53.0844, 18.3341),
    "gościeradów ukazowy": (50.8661, 21.9961),
    "gościeradów": (50.8661, 21.9961),
    "kamionka": (51.4728, 22.4644),
    "biecz": (49.7319, 21.2619),
    "zakrzew": (51.4647, 21.0583),
    "grodzisko dolne": (50.1558, 22.4542),
    "sanok": (49.5606, 22.2094),
    "kartuzy": (54.3344, 18.2014),
    "bestwina": (49.8978, 19.0625),
    "bobrowniki": (50.3986, 19.0347),
    "elbląg": (54.1661, 19.4128),
    "miłakowo": (54.0114, 20.0714),
    "kleszczewo": (52.3386, 17.1814),
    "zduny": (51.6481, 17.3828),
    "poznań": (52.4064, 16.9252),
    "nowogard": (53.6733, 15.1228),
    "wolin": (53.8428, 14.6192),
}


def _norm(text: str) -> str:
    if not text:
        return ""
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^\w\s-]", "", t).strip()


def extract_gmina_name(recipient_name: str, city: str) -> str:
    """Zwraca czytelną nazwę gminy/podmiotu do wyświetlenia na mapie i w filtrach."""
    rec = recipient_name or ""
    rec_clean = re.split(r"[-–—]", rec)[0].strip()
    if re.search(r"\bgmina\b", rec_clean, re.I):
        return rec_clean
    if city:
        return f"Gmina {city}" if not city.lower().startswith("gmina") else city
    return rec_clean or "Nieznana gmina"


def get_coords(city: str, recipient_name: str, voivodeship: str):
    """Zwraca (lat, lon)."""
    c_key = (city or "").strip().lower()
    if c_key in LOCATION_COORDS:
        return LOCATION_COORDS[c_key]

    norm_c = _norm(city)
    for k, coords in LOCATION_COORDS.items():
        if _norm(k) == norm_c:
            return coords

    for word in re.findall(r"[A-ZĄĆĘŁŃÓŚŹŻa-ząćęłńóśźż]{4,}", recipient_name or ""):
        w_lower = word.lower()
        if w_lower in LOCATION_COORDS:
            return LOCATION_COORDS[w_lower]
        w_norm = _norm(word)
        for k, coords in LOCATION_COORDS.items():
            if _norm(k) == w_norm:
                return coords

    v_key = (voivodeship or "").strip().lower()
    if v_key in VOIVODESHIP_CENTROIDS:
        return VOIVODESHIP_CENTROIDS[v_key]

    return (52.0, 19.0)
