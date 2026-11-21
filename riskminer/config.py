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

# Analiza przyczyn i kategorii ryzyka na żądanie.
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "llama.cpp")
LLM_MODEL = os.environ.get("LLM_MODEL", {"llama.cpp": "bielik-11b-v2.6-instruct",
                                         "anthropic": "claude-sonnet-5-5"}.get(LLM_PROVIDER, ""))
# Modele lokalne (llama.cpp): nazwa -> plik w data/llm; pobierane automatycznie z przypiętej wersji (local_model.MODELS).
LOCAL_MODEL_FILES = {"qwen2.5-1.5b-instruct": "qwen.gguf", "bielik-11b-v2.6-instruct": "bielik-11b-v2.6.gguf"}
LLM_MODEL_PATH = Path(os.environ.get("LLM_MODEL_PATH",
                                     DATA_DIR / "llm" / LOCAL_MODEL_FILES.get(LLM_MODEL, "bielik-11b-v2.6.gguf")))
# CPU jest domyślny również na Macu. Metal można jawnie włączyć przez LLM_GPU_LAYERS=-1.
LLM_GPU_LAYERS = int(os.environ.get("LLM_GPU_LAYERS", "0"))
# Z GPU (Metal) 8192 tokenów mieści kilkustronicowy dokument w jednym wywołaniu; na CPU 4096 (szybciej, mniej pamięci).
LLM_CONTEXT = int(os.environ.get("LLM_CONTEXT") or ("8192" if LLM_GPU_LAYERS else "4096"))
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")

USER_AGENT = os.environ.get("RISKMINER_USER_AGENT", "RiskMiner-prototype/0.1 (hackathon)")

BIP_SOURCES_FILE = Path(os.environ.get("BIP_SOURCES_FILE", BASE_DIR / "bip_sources.json"))
