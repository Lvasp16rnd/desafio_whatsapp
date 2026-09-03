"""
gemini_stt.py — Teste isolado de transcrição (STT) com Google Gemini.

Útil para validar a chave do Gemini e o formato do áudio ANTES de plugar
no n8n (o WhatsApp entrega áudio OGG/Opus; o Gemini aceita ogg/m4a/mp3).

Uso:
    python gemini_stt.py caminho/do/audio.ogg

Requisitos:
    pip install requests
    Variável de ambiente GEMINI_API_KEY definida.

Referência da API:
    https://ai.google.dev/api/generate-content
"""

import base64
import mimetypes
import os
import sys

import requests

MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
API_KEY = os.getenv("GEMINI_API_KEY", "")
URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

PROMPT = (
    "Transcreva este áudio. Retorne apenas o texto transcrito, "
    "sem comentários ou marcações."
)


def transcribe(path: str) -> str:
    if not API_KEY:
        raise SystemExit("Defina GEMINI_API_KEY antes de rodar.")

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
