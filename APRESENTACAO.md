# Desafio 1 — Agente de Atendimento WhatsApp (Pré-atendimento)

> Apresentação da solução desenvolvida para o processo seletivo de Automação/DevOps.
> Repositório com o código da solução acompanha este documento.

---

## 1. O que foi pedido

Criar um agente de atendimento no WhatsApp que faça o **pré-atendimento** do usuário: receber, coletar dados (nome, e-mail e celular) por áudio, transcrever com IA, confirmar com o usuário, abrir o chamado e responder dúvidas consultando fontes públicas.

## 2. A solução em uma frase

Um **fluxo orquestrado no n8n** que conecta o WhatsApp a uma IA multimodal (Gemini), mantém o estado da conversa em Redis e registra os chamados em uma planilha — tudo com ferramentas gratuitas e sem depender de servidor próprio.

## 3. Arquitetura

```
WhatsApp ──► Meta Cloud API ──► Caddy (VM Oracle, HTTPS)
                                   │ túnel SSH reverso
                                   ▼
                              n8n (Docker) ──► Gemini · Google Sheets · Redis
```

| Componente | Papel | Onde roda |
|---|---|---|
| Meta WhatsApp Cloud API | Canal de mensagens (webhook) | nuvem Meta |
| Caddy | Termina o HTTPS (Let's Encrypt automático) | VM Oracle |
| n8n | Orquestra todo o fluxo | Docker (PC) |
| Redis | Estado da conversa por usuário (com TTL) | Docker (PC) |
| Google Gemini | Transcrição de áudio, análise de imagem e busca pública | nuvem Google |
| Google Sheets | Base de chamados | nuvem Google |
| DuckDNS + SSH reverso | Expor o agente publicamente sem servidor | — |

## 4. Fluxo de atendimento

O agente funciona como uma **máquina de estados**, guardando em que etapa cada usuário está (chave = número do WhatsApp):

```
SAUDACAO → COLETA → CONFIRMACAO → PROBLEMA → CHAMADO → ATENDIMENTO → ENCERRADO
```

1. **Saudação** — recebe o usuário e pede um áudio com Nome, E-mail e Celular.
2. **Coleta** — escuta o áudio (ou imagem da ocorrência), transcreve com o Gemini e
   **extrai automaticamente Nome, E-mail e Celular** do texto transcrito (regex sobre
   o formato livre da fala).
3. **Confirmação** — devolve os dados extraídos e pergunta se estão corretos.
4. **Problema** — ao confirmar ("sim"), pergunta qual é o problema/ocorrência.
5. **Chamado** — registra nome, e-mail, celular e a **ocorrência relatada** na planilha e orienta aguardar atendimento humano.
6. **Atendimento** — busca respostas em fontes públicas e valida se o usuário compreendeu (com nova busca se não).

## 5. Escolhas técnicas e por quê

| Decisão | Motivo |
|---|---|
| **n8n** | Orquestrador visual que dispensa escrever um backend inteiro; versionável via JSON; já traz conectores de webhook e banco |
| **Docker** | Reproduz o ambiente de forma isolada e consistente; conceito central em DevOps |
| **Redis** | Guarda o estado da conversa com TTL (retenção mínima de dados), sem servidor extra |
| **Gemini** | Já tinha acesso, é multimodal (áudio + imagem + texto) num único serviço, e o *grounding* com Google Search resolve a busca em fontes públicas |
| **Caddy + DuckDNS + SSH reverso** | Contorna a indisponibilidade de VMs ARM na Oracle: a VM Always Free (x86) só hospeda o Caddy, e a URL pública chega até o n8n local por um túnel SSH reverso |

## 6. Segurança e privacidade (LGPD)

- Todo o tráfego é **HTTPS** (Meta ↔ Caddy ↔ n8n ↔ Gemini ↔ Sheets).
- Estado no Redis com **TTL**; sem log de dados pessoais.
- Planilha de chamados **privada**; segredos apenas em `.env` (fora do git).
- A confirmação da transcrição funciona como **consentimento** para a abertura do chamado.

## 7. Dificuldades e barreiras do projeto

A maior barreira foi de **infraestrutura**: a Oracle não estava liberando VMs ARM, então não havia VPS disponível — e também não havia domínio próprio nem hospedagem.

Para contornar isso, a solução ficou distribuída:

- **IP público sem domínio** — reutilizei uma VM Always Free (E2.1 Micro, 1 GB de RAM), fraca demais para rodar tudo, apenas para ter um IP público e gerar um subdomínio grátis no DuckDNS.
- **Parte do projeto no computador** — o n8n e o Redis rodam em Docker no meu PC (que tem mais recursos); na VM fica só o Caddy (HTTPS), e um túnel SSH reverso liga a URL pública ao n8n local.

Outras barreiras técnicas:

- **Webhook da Meta exige HTTPS válido** — IP puro não recebe certificado gratuito, o que levou à combinação DuckDNS + Caddy.
- **Formato de áudio do WhatsApp (OGG/Opus)** — exige baixar o binário, codificar em base64 e só então enviar à IA.
- **Estado entre mensagens** — cada mensagem chega como uma requisição isolada; o Redis resolve a continuidade da conversa.
- **Limites do número de teste da Meta** (5 destinatários / janela de 24h) — moldaram a demonstração.
- **Modelos do Gemini descontinuados** — o workflow apontava para `gemini-2.0-flash`,
  que a Google removeu do catálogo (e depois `gemini-2.5-flash`, também removido
  para novos usuários). Ajustado para `gemini-3.6-flash`, hoje o modelo flash
  estável recomendado.

## 8. O bloqueio com a Meta e como foi contornado

### O que aconteceu

Na etapa final, para validar o fluxo de ponta a ponta com mensagens reais, o
**número de teste da Meta** se mostrou o maior obstáculo. Esbarramos em
limitações que não dependem do código:

1. **O token de acesso expirava rápido** — o token de teste do painel durava
   horas, e o temporário ~24h; a cada sessão o agente parava de responder com
   erro `Session has expired`.
2. **A Meta não entregava o webhook de mensagens reais** — o *dashboard*
   entregava só o "Test webhook" (botão de teste), mas a mensagem vinda de um
   número do WhatsApp ficava com *double check cinza* e **nunca gerava o evento
   `messages`** no webhook, em nenhum estado (app publicado ou não publicado).
3. **Limite de envio de código no VOIP** — ao tentar validar um número VoIP
   pago para o teste, a Meta bloqueou o envio do código de verificação
   (limite atingido), impedindo concluir a configuração do destinatário.

### O que foi feito para tentar contornar

- **Token permanente (System User)** — gerado via Business Settings, com
  escopos `whatsapp_business_messaging`/`whatsapp_business_management`, sem
  expiração. Resolveu definitivamente o item 1.
- **Diagnóstico de ponta a ponta via API da Meta** — confirmei que o webhook
  estava `active: true`, com `messages` subscribed e a URL correta, provando
  que o problema **não** era a configuração.
- **Teste do botão "Test" do dashboard** — a Meta entregou um payload real de
  teste ao n8n e o fluxo processou do início ao `Send Reply`, provando que a
  infra (Caddy + túnel + n8n + workflow) estava 100% funcional.
- **Correções no workflow** — três bugs de integração que custaram horas:
  (a) o `State Machine` acessava o nó de mídia sem *guard* e quebrava em texto;
  (b) o switch de roteamento descartava a resposta padrão por falta de
  `fallbackOutput`; (c) o n8n 2.x bloqueava `$env` dentro dos nós
  (`N8N_BLOCK_ENV_ACCESS_IN_NODE`).

### O que foi possível entregar

A parte do bloqueio que era **limitação de ambiente** (número de teste/VOIP da
Meta) não impediu de validar a solução. Criei um **simulador de WhatsApp em
linha de comando** (`scripts/simular_whatsapp.py`) que monta o mesmo payload
que a Meta enviaria e chama o webhook do n8n de verdade — incluindo a
**transcrição real de áudio via Gemini**. Com isso foi possível exercitar o
mesmo fluxo do agente (saudação → transcrição → confirmação → chamado) sem
depender do WhatsApp.

## 9. Melhorias possíveis

- Adicionar **testes automatizados** do fluxo e monitoramento/alertas.
- Extração estruturada dos dados (nome/e-mail/celular) **via saída JSON do Gemini**
  (hoje é feita por regex; usar o Gemini com `response_mime_type=application/json`
  deixaria a extração mais robusta para falas menos padronizadas).
- Subir o n8n em uma VPS de verdade (ou PaaS) para eliminar o túnel SSH e a
  dependência do notebook.

---

## 10. Roteiro de demonstração (com o simulador)

Como a validação com o WhatsApp real ficou bloqueada pela Meta, a demonstração
usa o simulador de terminal, que exercita o **mesmo fluxo do n8n**. Passos:

**Pré-requisitos** (antes de começar):

```powershell
# 1. n8n + Redis no ar
.\scripts\setup.ps1

# 2. chave do Gemini no ambiente (para a transcrição)
$env:GEMINI_API_KEY = "sua-chave"
```

**Passo 1 — Saudação (mensagem de texto):**

```powershell
python scripts\simular_whatsapp.py oi
```

> Mostra no n8n (http://localhost:5678) a execução do fluxo: Webhook →
> Parse → Read State → roteamento → State Machine → Send Reply. A resposta
> gerada é a saudação pedindo o áudio.

**Passo 2 — Transcrição de áudio (o coração do agente):**

```powershell
# grave um áudio: "Meu nome é João, email joao@email.com, celular 11 98765-4321"
python scripts\simular_whatsapp.py meu_audio.ogg
```

> O script envia o áudio ao **Gemini** e imprime a transcrição real — é a
> mesma chamada que o nó `Gemini STT/Vision` faz no workflow.

**Passo 3 — o fluxo completo (conversa interativa):**

```powershell
python scripts\simular_whatsapp.py
```

> Digite `oi`, depois os dados, confirme com `sim`, descreva o problema, e
> observe a máquina de estados andar: SAUDACAO → COLETA → CONFIRMACAO → PROBLEMA → CHAMADO.

**O que destacar na fala:**

1. A **arquitetura distribuída** (Caddy na VM + n8n/Redis no Docker + túnel SSH).
2. A **máquina de estados** com persistência em Redis (continuidade da conversa).
3. A **IA multimodal** (Gemini) fazendo transcrição + busca com *grounding*.
4. A **honestidade sobre o bloqueio**: a Meta impediu a validação com mensagem
   real (token/VOIP/app publicado), e o simulador foi a forma de provar que o
   fluxo funciona até onde a Meta permitiu.

**Evidência de que o webhook real funciona:** no painel da Meta, o botão
"Test" do campo `messages` entrega um payload que o n8n processa do início ao
fim — mostrando que a infra e o workflow estão corretos; só a entrega de
mensagens de produção é que a Meta negou.
