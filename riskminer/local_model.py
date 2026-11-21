"""Lokalny model językowy (domyślnie Bielik-11B v2.6) uruchamiany w procesie aplikacji przez llama.cpp."""
import hashlib
import os
import tempfile
from functools import lru_cache
from pathlib import Path
from threading import Lock

import requests

from . import config


# Przypięte wersje (commit w Hugging Face) i sumy SHA-256 – pobieramy tylko zweryfikowane wagi.
MODELS = {
    "qwen.gguf": ("https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/"
                  "91cad51170dc346986eccefdc2dd33a9da36ead9/qwen2.5-1.5b-instruct-q4_k_m.gguf",
                  "6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e"),
    # Bielik-11B v2.6 Instruct (SpeakLeash, Apache-2.0), kwantyzacja Q4_K_M, ~6,7 GB
    "bielik-11b-v2.6.gguf": ("https://huggingface.co/speakleash/Bielik-11B-v2.6-Instruct-GGUF/resolve/"
                             "03aee82964b90a8f02aba719fc9cb290d0af7d62/Bielik-11B-v2.6-Instruct.Q4_K_M.gguf",
                             "5506531e3385d7bba4f667cd4ce9f405244505671fe0d9102351f78195b56c62"),
}
MODEL_URL, MODEL_SHA256 = MODELS["qwen.gguf"]  # zgodność wsteczna
_lock = Lock()


class LocalModelError(Exception):
    pass


def _download(path, url=None, sha256=None):
    url = url or MODEL_URL
    sha256 = sha256 or MODEL_SHA256
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        with requests.get(url, stream=True, timeout=(10, 90)) as response:
            response.raise_for_status()
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as out:
                tmp = Path(out.name)
                digest = hashlib.sha256()
                for chunk in response.iter_content(1024 * 1024):
                    out.write(chunk)
                    digest.update(chunk)
        if digest.hexdigest() != sha256:
            raise LocalModelError("Pobrany model ma błędną sumę kontrolną. Ponów analizę.")
        os.replace(tmp, path)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


@lru_cache(maxsize=1)
def _load(path):
    # Tryb CPU działa również wtedy, gdy macOS nie udostępnia urządzenia Metal.
    if config.LLM_GPU_LAYERS == 0:
        os.environ.setdefault("GGML_METAL_DEVICES", "0")
    from llama_cpp import Llama
    if not path.is_file():
        if path.parent != config.DATA_DIR / "llm" or path.name not in MODELS:
            raise LocalModelError(f"Brak wskazanego pliku modelu: {path}")
        _download(path, *MODELS[path.name])
    gpu = config.LLM_GPU_LAYERS != 0
    return Llama(model_path=str(path), n_ctx=config.LLM_CONTEXT, n_gpu_layers=config.LLM_GPU_LAYERS,
                 offload_kqv=gpu, op_offload=None if gpu else False, verbose=False)


def complete(messages, schema, max_tokens=512):
    # Jeden kontekst llama.cpp obsługuje jedno wywołanie naraz.
    with _lock:
        try:
            model = _load(config.LLM_MODEL_PATH)
            answer = model.create_chat_completion(messages=messages, temperature=0, max_tokens=max_tokens,
                        response_format={"type": "json_object", "schema": schema})
        except (OSError, requests.RequestException, ImportError, RuntimeError, ValueError) as exc:
            hint = " Ustaw LLM_GPU_LAYERS=0 i uruchom aplikację ponownie." if config.LLM_GPU_LAYERS else ""
            raise LocalModelError(f"Uruchomienie lokalnego modelu nie powiodło się: {exc}.{hint}") from exc
    return answer["choices"][0]["message"]["content"]
