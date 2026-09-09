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
| IA multimodal | Google Gemini (`gemini-3.6-flash`) |
| Busca pública | Gemini Google Search *grounding* |
| Estado | Redis (TTL) |
| Ticket | Google Sheets |
| HTTPS | Caddy + DuckDNS |
| Ponte | SSH reverso (ou Tailscale) |

---

## Pré-requisitos

- Docker Desktop (Windows) ou Docker no WSL2 (Ubuntu)
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

> O `WHATSAPP_TOKEN` expira (o de teste dura horas; o temporário ~24h). Para
> desenvolvimento use um **token permanente (System User)** — não expira.
> Veja [Token permanente](#token-permanente-system-user).

### 2. Subir n8n + Redis (no PC)

```powershell
.\scripts\setup.ps1
```

O script cria a rede Docker, sobe Redis e n8n, e abre a ponte SSH reversa no final (deixe o terminal aberto).

> **Rodando no WSL2 (Ubuntu):** use `./scripts/setup.sh` (equivalente bash do `setup.ps1`). O script já aplica `chmod 600` na chave `.pem` e abre a ponte SSH no final.

- Editor do n8n: http://localhost:5678
- Webhook (via Caddy): https://agenteautomacao.duckdns.org/webhook/whatsapp

> ⚠️ **Importante (n8n 2.x):** o script já define
> `N8N_BLOCK_ENV_ACCESS_IN_NODE=false`. Sem isso, o n8n bloqueia `$env.*`
> dentro dos nós (erro `access to env vars denied`) e o `Send Reply`/`Gemini`
> não conseguem ler `WHATSAPP_TOKEN`/`GEMINI_API_KEY`.

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
3. O webhook já vem com GET+POST (multipleMethods) e um nó **Respond to
   Webhook** que ecoa o `hub.challenge` (verificação da Meta — nada a configurar).

> Correções já embutidas neste arquivo (não remover ao editar):
> - `State Machine` só acessa `$('Gemini STT/Vision')` dentro de `if (type !== 'text')`.
> - `Route by State` tem `options.fallbackOutput = "extra"` (sem isso a saudação nunca chega ao `Send Reply`).
> - Nós HTTP usam `authentication: "none"` com header manual.

### 5. Registrar o webhook na Meta

- URL: `https://agenteautomacao.duckdns.org/webhook/whatsapp`
- Verify token: o valor de `VERIFY_TOKEN`
- Assinar o evento `messages` (o campo `media` vem embutido na mensagem `messages`, não é um field separado).

---

## Token permanente (System User)

O token de teste do painel expira em horas/dias. Para desenvolvimento:

1. `business.facebook.com` → seu negócio → **Users → System users** → **Add**.
2. No system user → **Assign assets** → selecione o app e o WhatsApp Business
   Account com **Manage**.
3. **Generate token** → app → expiry **Never** → escopos
   `whatsapp_business_messaging` + `whatsapp_business_management`.
4. Cole o token no `.env` em `WHATSAPP_TOKEN` e rode `setup` de novo.

---

## Testar SEM a Meta (modo terminal)

O número de teste da Meta é um bloqueio burocrático (VOIP, limite de envio de
código, app publicado/não publicado). Para testar o agente **sem WhatsApp no
meio**, use o simulador de terminal — ele monta o mesmo payload que a Meta
enviaria e chama o webhook do n8n de verdade, incluindo transcrição real de
áudio via Gemini:

```powershell
# modo conversa interativa (texto)
python scripts\simular_whatsapp.py

# envia uma mensagem de texto e vê o fluxo rodar no n8n
python scripts\simular_whatsapp.py oi

# transcrição real de um áudio/imagem via Gemini
$env:GEMINI_API_KEY="sua-chave"
python scripts\simular_whatsapp.py caminho\do\audio.ogg
```

Por padrão ele aponta para `http://localhost:5678/webhook/whatsapp` (n8n
local, sem depender do túnel). Para testar via ponte pública, defina
`WEBHOOK_URL=https://agenteautomacao.duckdns.org/webhook/whatsapp`.

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
    ├── gemini_stt.py
    └── simular_whatsapp.py
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
- O webhook de mensagens **reais** exige condições que o número de teste
  costuma não cumprir (VOIP/limite de código, app "published vs unpublished").
  Por isso, para demonstração técnica, use o
  [`scripts/simular_whatsapp.py`](#testar-sem-a-meta-modo-terminal), que
  exercita o **mesmo fluxo do n8n** sem depender da Meta.
