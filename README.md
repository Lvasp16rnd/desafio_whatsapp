# Agente de Atendimento WhatsApp — Pré-atendimento

Agente de suporte no WhatsApp que faz o **pré-atendimento**: coleta os dados do usuário por áudio, transcreve com IA, confirma a transcrição, abre o chamado e responde dúvidas consultando bases públicas.

---

## O que o agente faz

1. Recebe o usuário e solicita, por **áudio**, Nome, E-mail e Celular.
2. Aceita **imagem ou áudio** da ocorrência.
3. Converte os dados em texto (IA) e pede **confirmação** da transcrição.
4. Ao confirmar, **abre o chamado** e orienta a aguardar atendimento humanizado.
5. Conforme a dúvida do usuário, busca respostas em **bases públicas** e valida se foi compreendido (com laço de nova busca se necessário).

---

## Arquitetura

```
WhatsApp ──► Meta Cloud API ──► Caddy (VM Oracle, HTTPS)
                                   │ SSH reverso
                                   ▼
                              n8n (Docker, PC) ──► Gemini (IA) / Sheets / Redis
```

| Peça | Onde | Papel |
|---|---|---|
| **Meta WhatsApp Cloud API** | nuvem Meta | Canal de mensagens (webhook) |
| **Caddy** | VM Oracle (Always Free) | HTTPS público com Let's Encrypt automático |
| **n8n** | PC (Docker) | Orquestração do fluxo (máquina de estados) |
| **Redis** | PC (Docker) | Estado da conversa por usuário |
| **Google Gemini** | nuvem Google | Transcrição de áudio, análise de imagem, busca pública |
| **Google Sheets** | nuvem Google | Base de chamados (tickets) |
| **DuckDNS** | nuvem | Subdomínio grátis → IP público da VM |

A URL pública chega até o n8n local via **túnel SSH reverso** (`VM:5678 → PC:5678`), sem abrir porta no PC.

---

## Stack (tudo gratuito)

| Camada | Ferramenta |
|---|---|
| Mensageria | Meta WhatsApp Cloud API (número de teste) |
| Orquestração | n8n (Docker) |
| IA multimodal | Google Gemini (`gemini-2.0-flash`) |
| Busca pública | Gemini Google Search *grounding* |
| Estado | Redis (TTL) |
| Ticket | Google Sheets |
| HTTPS | Caddy + DuckDNS |
| Ponte | SSH reverso (ou Tailscale) |

---

## Pré-requisitos

- Docker Desktop (Windows)
- OpenSSH client (padrão no Windows 10+)
- Contas/credenciais:
  - Meta Developer (app com use case **"Connect with customers through WhatsApp"**)
  - Google AI Studio (chave Gemini)
  - DuckDNS (subdomínio apontando para o IP da VM)
  - VM Oracle com Caddy + portas 80/443 liberadas

---

## Como rodar

### 1. Configurar variáveis

```powershell
Copy-Item .env.example .env
# preencha .env com seus tokens/IDs
```

### 2. Subir n8n + Redis (no PC)

```powershell
.\scripts\setup.ps1
```

O script cria a rede Docker, sobe Redis e n8n, e abre a ponte SSH reversa no final (deixe o terminal aberto).

- Editor do n8n: http://localhost:5678
- Webhook (via Caddy): https://`seu-subdomínio`.duckdns.org/webhook/whatsapp

### 3. Configurar o HTTPS na VM

```bash
sudo apt install -y caddy
sudo cp infra/Caddyfile /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

### 4. Importar o workflow no n8n

No editor, **Import from File** → `n8n/workflow.json`. Depois:
1. Criar a credencial **Redis** (host `redis`, porta `6379`).
2. No nó **Open Ticket**, selecionar a planilha e mapear as colunas.
3. No nó **Gemini STT/Vision**, colar o base64 da mídia (baixada no nó **Download Media**).
4. Configurar a resposta do webhook para ecoar o `hub.challenge` (verificação da Meta).

### 5. Registrar o webhook na Meta

- URL: `https://`seu-subdomínio`.duckdns.org/webhook/whatsapp`
- Verify token: o valor de `VERIFY_TOKEN`
- Assinar os eventos `messages` e `media`.

---

## Teste isolado da transcrição

Antes de plugar tudo, valide a chave do Gemini com um áudio local:

```powershell
$env:GEMINI_API_KEY="sua-chave"
python scripts\gemini_stt.py caminho\do\audio.ogg
```

---

## Estrutura do repositório

```
├── README.md
├── .env.example
├── .gitignore
├── infra/
│   └── Caddyfile
├── n8n/
│   └── workflow.json
└── scripts/
    ├── setup.ps1
    └── gemini_stt.py
```

---

## Segurança (LGPD)

- Todo o tráfego é **HTTPS** (Meta ↔ Caddy ↔ n8n ↔ Gemini ↔ Sheets).
- Estado no Redis com **TTL** (retenção mínima); não logar dados pessoais.
- Planilha de chamados **privada** (nunca pública).
- Segredos apenas em `.env` (fora do git).
- A confirmação da transcrição funciona como **consentimento** para a abertura do chamado.

---

## Limitações do número de teste (Meta)

- Conversa apenas com **até 5 números** cadastrados.
- Respostas livres dentro da **janela de 24h** da última mensagem do usuário.
- Para produção, é necessário verificação de negócio (Meta Business).
