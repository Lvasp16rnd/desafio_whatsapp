"""
gemini_stt.py — Teste isolado de transcrição (STT) com Google Gemini.

Útil para validar a chave do Gemini e o formato do áudio ANTES de plugar
no n8n (o WhatsApp entrega áudio OGG/Opus; o Gemini aceita ogg/m4a/mp3).

Uso:
    python gemini_stt.py caminho/do/audio.ogg

Requisitos:
    pip install requests
    GEMINI_API_KEY definida no ambiente OU no .env do projeto.

Referência da API:
    https://ai.google.dev/api/generate-content
"""

import base64
import mimetypes
import os
import sys

import requests

# Evita erro de encoding no console do Windows ao imprimir acentos
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
API_KEY = os.getenv("GEMINI_API_KEY", "")
URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

PROMPT = (
    "Transcreva este áudio. Retorne apenas o texto transcrito, "
    "sem comentários ou marcações."
)


def _carregar_env_local() -> None:
    """Se GEMINI_API_KEY não estiver no ambiente, tenta ler do .env do projeto."""
    global API_KEY, MODEL
    if API_KEY:
        return
    candidates = [
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
        ".env",
    ]
    for env_path in candidates:
        if not os.path.isfile(env_path):
            continue
        try:
            with open(env_path, encoding="utf-8") as f:
                for linha in f:
                    linha = linha.strip()
                    if not linha or linha.startswith("#") or "=" not in linha:
                        continue
                    k, v = linha.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k == "GEMINI_API_KEY" and not API_KEY:
                        API_KEY = v
                    elif k == "GEMINI_MODEL" and MODEL == "gemini-3.6-flash":
                        MODEL = v
        except OSError:
            continue


def transcribe(path: str) -> str:
    _carregar_env_local()
    if not API_KEY:
        raise SystemExit("Defina GEMINI_API_KEY (no ambiente ou no .env) antes de rodar.")

    mime, _ = mimetypes.guess_type(path)
    if mime is None:
        mime = "audio/ogg"

    with open(path, "rb") as f:
        audio_b64 = base64.b64encode(f.read()).decode()

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": PROMPT},
                    {"inline_data": {"mime_type": mime, "data": audio_b64}},
                ]
            }
        ]
    }

    resp = requests.post(
        URL.format(model=MODEL),
        params={"key": API_KEY},
        json=payload,
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()

    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as exc:
        raise SystemExit(f"Resposta inesperada do Gemini:\n{data}") from exc


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Uso: python gemini_stt.py <arquivo de áudio>")

    texto = transcribe(sys.argv[1])
    print("Transcrição:")
    print(texto)
