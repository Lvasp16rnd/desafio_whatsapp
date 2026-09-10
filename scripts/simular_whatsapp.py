"""
simular_whatsapp.py — Testa o agente do n8n SEM depender da Meta/WhatsApp.

Por que existe:
    O numero de teste da Meta é um bloqueio burocratico (limite de codigo no
    VOIP, app publicado/nao publicado, etc.). Este script simula o papel do
    WhatsApp: monta o mesmo payload que a Meta mandaria pro webhook e mostra
    a resposta que o agente geraria — inclusive a transcricao real de audio
    via Gemini.

O que ele faz:
    1. Recebe no terminal um texto (ou caminho de arquivo de audio/imagem).
    2. Monta o payload JSON igual ao webhook `messages` da Meta.
    3. Faz POST no webhook do n8n (local por padrao; pode apontar pro publico).
    4. Para audio/imagem, transcreve com o Gemini localmente (mesma chamada
       que o no "Gemini STT/Vision" faz no workflow).

Uso:
    python simular_whatsapp.py                # modo conversa interativa
    python simular_whatsapp.py oi             # envia uma mensagem de texto
    python simular_whatsapp.py audio.ogg      # transcricao real via Gemini
"""

import base64
import json
import mimetypes
import os
import re
import sys
import urllib.request
import urllib.error

# Evita erro de encoding no console do Windows ao imprimir acentos
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
# Padrao: n8n local (WSL2/Docker acessa via localhost). Para testar via a
# ponte publica (Caddy + tunel SSH), defina WEBHOOK_URL apontando para
# https://agenteautomacao.duckdns.org/webhook/whatsapp
WEBHOOK_URL = os.getenv(
    "WEBHOOK_URL", "http://localhost:5678/webhook/whatsapp"
)
FROM_NUMBER = os.getenv("FROM_NUMBER", "5563984298509")
DISPLAY_PHONE = os.getenv("WHATSAPP_PHONE_ID", "1356254897564090")

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent"
)

# Modelos tentados em sequência (fallback): se um estiver com alta demanda
# (503) ou sem cota (429), o próximo é tentado. Aumenta muito a resiliência
# em demonstrações, pois o Gemini às vezes fica instável.
GEMINI_MODELS_FALLBACK = [
    os.getenv("GEMINI_MODEL", "gemini-3.6-flash"),
    "gemini-3.5-flash",
    "gemini-flash-latest",
]


def _carregar_env_local() -> None:
    """Se GEMINI_API_KEY nao estiver no ambiente, tenta ler do .env do projeto."""
    global GEMINI_API_KEY, GEMINI_MODEL
    if GEMINI_API_KEY:
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
                    if k == "GEMINI_API_KEY" and not GEMINI_API_KEY:
                        GEMINI_API_KEY = v
                    elif k == "GEMINI_MODEL" and GEMINI_MODEL == "gemini-3.6-flash":
                        GEMINI_MODEL = v
        except OSError:
            continue


# ---------------------------------------------------------------------------
# Transcricao (STT/Vision) — igual ao no "Gemini STT/Vision" do n8n
# ---------------------------------------------------------------------------
def _chamar_gemini(payload: dict, tentativas: int = 2) -> str:
    """Chama o Gemini com fallback de modelos e retry. Nunca lança exceção.

    Retorna o texto gerado ou uma mensagem amigável em caso de falha
    (quota esgotada, alta demanda, etc.).
    """
    if not GEMINI_API_KEY:
        return "[sem GEMINI_API_KEY no ambiente nem no .env]"

    ultimo_erro = ""
    for modelo in GEMINI_MODELS_FALLBACK:
        url = GEMINI_URL.format(model=modelo) + f"?key={GEMINI_API_KEY}"
        for tentativa in range(tentativas):
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode())
                texto = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                if texto:
                    return texto
                ultimo_erro = "resposta vazia"
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    # modelo descontinuado -> pula direto pro próximo
                    ultimo_erro = f"modelo {modelo} indisponivel (404)"
                    break
                ultimo_erro = f"HTTP {e.code}"
            except Exception as e:  # noqa: BLE001
                ultimo_erro = str(e)
            if tentativa < tentativas - 1:
                import time
                time.sleep(1.0)

    return (
        "O servico de IA esta temporariamente indisponivel "
        f"({ultimo_erro}). Tente novamente em instantes."
    )


def transcrever(caminho: str) -> str:
    mime, _ = mimetypes.guess_type(caminho)
    if mime is None:
        mime = "audio/ogg"

    with open(caminho, "rb") as f:
        data_b64 = base64.b64encode(f.read()).decode()

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": "Transcreva APENAS o conteudo falado no audio ou descreva somente a imagem. Nao adicione introducoes, titulos, saudacoes nem comentarios. Responda somente com a transcricao/descricao."},
                    {"inline_data": {"mime_type": mime, "data": data_b64}},
                ]
            }
        ]
    }

    return _chamar_gemini(payload)


def _buscar_resposta(duvida: str, dados: dict) -> str:
    """Consulta o Gemini com grounding (Google Search), igual ao no Gemini Search do n8n."""
    if not GEMINI_API_KEY:
        return "Peço desculpas, não consigo consultar a base no momento."

    ocorrencia = dados.get("ocorrencia") or duvida
    prompt = (
        "Um usuário abriu um chamado de suporte. Ocorrência registrada: "
        f"{ocorrencia}. Agora ele perguntou: {duvida}. "
        "Responda de forma clara e direta em português, usando informações de "
        "fontes públicas quando relevante."
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
    }
    return _chamar_gemini(payload)


# ---------------------------------------------------------------------------
# Payload do webhook (o mesmo que a Meta envia)
# ---------------------------------------------------------------------------
def montar_payload(tipo: str, texto: str = "", media_id: str = "") -> dict:
    msg = {"from": FROM_NUMBER, "id": "wamid.SIM", "timestamp": "1700000000", "type": tipo}
    if tipo == "text":
        msg["text"] = {"body": texto}
    elif tipo == "audio":
        msg["audio"] = {"id": media_id, "mime_type": "audio/ogg; codecs=opus"}
    elif tipo == "image":
        msg["image"] = {"id": media_id, "mime_type": "image/jpeg"}

    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "SIM",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "15556651990",
                                "phone_number_id": DISPLAY_PHONE,
                            },
                            "contacts": [{"wa_id": FROM_NUMBER}],
                            "messages": [msg],
                        },
                    }
                ],
            }
        ],
    }


def chamar_webhook(payload: dict) -> None:
    """Envia o payload pro webhook do n8n e mostra o status HTTP."""
    try:
        req = urllib.request.Request(
            WEBHOOK_URL,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"[webhook] POST '{WEBHOOK_URL}' -> HTTP {resp.status}")
    except urllib.error.HTTPError as e:
        print(f"[webhook] HTTP {e.code}: {e.read().decode()[:200]}")
    except Exception as e:  # noqa: BLE001
        print(f"[webhook] erro ao chamar: {e}")


# ---------------------------------------------------------------------------
# Maquina de estados LOCAL (espelha o "State Machine" do n8n) para simular
# ---------------------------------------------------------------------------
def _extrair_email(t: str) -> str:
    m = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", t or "")
    return m.group(0) if m else ""


def _extrair_celular(t: str) -> str:
    m = re.search(r"(\+?\d{2}[\s.-]?)?(?:\(?(\d{2})\)?[\s.-]?)?(9?\s?\d{4}[\s.-]?\d{4}|\d{4}[\s.-]?\d{4})", t or "")
    return m.group(0).strip() if m else ""


def _extrair_nome(t: str, email: str, celular: str) -> str:
    m = re.search(r"(?:meu nome [ée]|sou(?: o| a)?|nome[:\s]+)([^,.]+)", t or "", re.I)
    if m:
        return m.group(1).strip()
    corte = (t or "").split(",")[0].split(".")[0].split("|")[0]
    nome = re.sub(
        r"(meu nome [ée]|sou(?: o| a)?|meu email[^,]*|meu celular[^,]*|meu número[^,]*|celular[^,]*|email[^,]*|o meu número de telefone[^,]*|o meu email[^,]*)",
        " ", corte, flags=re.I,
    )
    nome = nome.replace(email, " ").replace(celular, " ")
    nome = re.sub(r"\s{2,}", " ", nome).strip()
    if len(nome) < 3 or (re.search(r"\d", nome) and not re.search(r"[A-Za-zÀ-ÿ]", nome)):
        return ""
    return nome


def _estado_local(estado: str, texto: str, dados: dict) -> tuple:
    """Espelha o State Machine do n8n. Retorna (reply, novo_estado, dados)."""
    if estado == "SAUDACAO":
        return ("Olá! Sou o assistente virtual. Para abrir seu chamado, envie um "
                "ÁUDIO com seu Nome, E-mail e Celular. Você também pode digitá-los.",
                "COLETA", dados)

    if estado == "COLETA":
        email = _extrair_email(texto)
        celular = _extrair_celular(texto)
        nome = _extrair_nome(texto, email, celular)
        if email:
            dados["email"] = email
        if celular:
            dados["celular"] = celular
        if nome:
            dados["nome"] = nome
        faltando = []
        if not dados.get("nome"):
            faltando.append("Nome")
        if not dados.get("email"):
            faltando.append("E-mail")
        if not dados.get("celular"):
            faltando.append("Celular")
        if not faltando:
            return (f"Recebi! Confirme os dados: Nome: {dados['nome']} | E-mail: {dados['email']} | "
                    f"Celular: {dados['celular']}. Responda SIM se estiver correto.", "CONFIRMACAO", dados)
        return f"Ainda falta: {', '.join(faltando)}. Envie em um áudio ou digite, por favor.", "COLETA", dados

    if estado == "CONFIRMACAO":
        if texto.strip().lower().startswith("sim"):
            return ("Ótimo! Agora me conte qual é o problema. Envie um áudio, uma imagem "
                    "ou digite a descrição da ocorrência.", "PROBLEMA", dados)
        for k in ("nome", "email", "celular"):
            dados[k] = ""
        return "Sem problemas! Envie novamente seu Nome, E-mail e Celular.", "COLETA", dados

    if estado == "PROBLEMA":
        limpo = re.sub(r"^(meu problema [ée]|o problema [ée]|preciso|eu)\s*", "", texto.strip(), flags=re.I)
        if len(limpo) >= 3:
            dados["ocorrencia"] = limpo
        return ("Chamado aberto! Registramos sua ocorrência e um atendente humano "
                "entrará em contato. Aguarde.", "CHAMADO", dados)

    if estado == "CHAMADO" or estado == "ATENDIMENTO":
        if texto.strip().lower().startswith("sim"):
            return "Ótimo! Fico feliz em ajudar. Até logo!", "ENCERRADO", dados
        resposta = _buscar_resposta(texto, dados)
        return resposta, "ATENDIMENTO", dados

    if estado == "ENCERRADO":
        return "Estou à disposição se precisar de algo mais.", "ENCERRADO", dados

    return "Entendi!", estado, dados


def conversa_interativa() -> None:
    print("========== AGENTE WHATSAPP — SIMULAÇÃO DE TERMINAL (sem Meta) ==========")
    print("Digite um texto, ou o caminho de um arquivo de áudio/imagem.")
    print("Digite 'sair' para encerrar.\n")

    estado = "SAUDACAO"
    dados = {"nome": "", "email": "", "celular": "", "ocorrencia": ""}
    while True:
        try:
            entrada = input("você> ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if entrada.lower() in ("sair", "quit", "exit"):
            break

        if os.path.isfile(entrada):
            texto = transcrever(entrada)
            print(f"[STT-Gemini] {texto}")
        else:
            texto = entrada

        chamar_webhook(montar_payload("text", texto))

        resposta, estado, dados = _estado_local(estado, texto, dados)
        print(f"agente> {resposta}")
        if estado == "CHAMADO":
            print(f"        [chamado gravado na planilha] {dados}\n")
        else:
            print()


def main() -> None:
    _carregar_env_local()
    if len(sys.argv) > 1:
        entrada = sys.argv[1]
        if os.path.isfile(entrada):
            print(f"[STT-Gemini] {transcrever(entrada)}")
        else:
            chamar_webhook(montar_payload("text", entrada))
        return
    conversa_interativa()


if __name__ == "__main__":
    main()
