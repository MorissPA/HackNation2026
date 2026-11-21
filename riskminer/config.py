"""Konfiguracja aplikacji – wartości z env, z rozsądnymi domyślnymi."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("RISKMINER_DATA_DIR", BASE_DIR / "data"))
DB_PATH = Path(os.environ.get("RISKMINER_DB", DATA_DIR / "riskminer.sqlite"))

BZP_API_BASE = os.environ.get("BZP_API_BASE", "https://ezamowienia.gov.pl/mo-board/api/v1")
# Kopia ogłoszeń wod-kan udostępniona przez organizatora HackNation: ten sam endpoint /notice, bez limitu
# zapytań, ale bez wyszukiwarki Board/Search, bez stronicowania i bez ogłoszeń o zmianie ogłoszenia.
# Pusta wartość wyłącza kopię (wtedy tylko oficjalne API).
BZP_MIRROR_BASE = os.environ.get("BZP_MIRROR_BASE", "https://bzp.cytr.us/mo-board/api/v1")
BZP_MIRROR_INTERVAL_S = float(os.environ.get("BZP_MIRROR_INTERVAL_S", "0.05"))
BZP_MIRROR_PAGE_SIZE = int(os.environ.get("BZP_MIRROR_PAGE_SIZE", "500"))
# Przy włączonej kopii nie robimy pełnego przeglądu ogłoszeń zamawiającego w oficjalnym API (do 25 stron
# po 2,2 s) – chyba że ktoś świadomie to włączy.
BZP_OFFICIAL_ORG_SCAN = os.environ.get("BZP_OFFICIAL_ORG_SCAN", "0") == "1"
# Oficjalny limit: 30 zapytań / minutę z jednego IP. Zostawiamy margines.
BZP_MIN_INTERVAL_S = float(os.environ.get("BZP_MIN_INTERVAL_S", "2.2"))
BZP_TIMEOUT_S = float(os.environ.get("BZP_TIMEOUT_S", "40"))
# Odpowiedzi wyszukiwarki cache'ujemy krócej niż treść ogłoszeń (te się nie zmieniają).
BZP_SEARCH_CACHE_TTL_H = float(os.environ.get("BZP_SEARCH_CACHE_TTL_H", "24"))
BZP_MAX_ORG_PAGES = int(os.environ.get("BZP_MAX_ORG_PAGES", "25"))

# Model językowy (używany w kolejnych etapach – ekstrakcja przyczyn/ryzyk).
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "anthropic")
LLM_MODEL = os.environ.get("LLM_MODEL", "claude-sonnet-5-5")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")

USER_AGENT = os.environ.get("RISKMINER_USER_AGENT", "RiskMiner-prototype/0.1 (hackathon)")
