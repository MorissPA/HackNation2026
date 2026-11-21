"""Model Qwen uruchamiany w procesie aplikacji."""
import hashlib
import os
import tempfile
from functools import lru_cache
from pathlib import Path
from threading import Lock

import requests

from . import config


MODEL_URL = ("https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/"
             "91cad51170dc346986eccefdc2dd33a9da36ead9/qwen2.5-1.5b-instruct-q4_k_m.gguf")
MODEL_SHA256 = "6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e"
_lock = Lock()


class LocalModelError(Exception):
    pass


def _download(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        with requests.get(MODEL_URL, stream=True, timeout=(10, 90)) as response:
            response.raise_for_status()
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as out:
                tmp = Path(out.name)
                digest = hashlib.sha256()
                for chunk in response.iter_content(1024 * 1024):
                    out.write(chunk)
                    digest.update(chunk)
        if digest.hexdigest() != MODEL_SHA256:
            raise LocalModelError("Pobrany model ma błędną sumę kontrolną. Ponów analizę.")
        os.replace(tmp, path)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


@lru_cache(maxsize=1)
def _load(path):
    # Tryb CPU działa również wtedy, gdy macOS nie udostępnia urządzenia Metal.
    os.environ.setdefault("GGML_METAL_DEVICES", "0")
    from llama_cpp import Llama
    if not path.is_file():
        if path != config.DATA_DIR / "llm" / "qwen.gguf":
            raise LocalModelError(f"Brak wskazanego pliku modelu: {path}")
        _download(path)
    return Llama(model_path=str(path), n_ctx=4096, n_gpu_layers=0, verbose=False)


def complete(messages, schema):
    # Jeden kontekst llama.cpp obsługuje jedno wywołanie naraz.
    with _lock:
        try:
            model = _load(config.LLM_MODEL_PATH)
            answer = model.create_chat_completion(messages=messages, temperature=0, max_tokens=512,
                        response_format={"type": "json_object", "schema": schema})
        except (OSError, requests.RequestException, ImportError, RuntimeError, ValueError) as exc:
            raise LocalModelError(f"Uruchomienie lokalnego modelu nie powiodło się: {exc}") from exc
    return answer["choices"][0]["message"]["content"]
