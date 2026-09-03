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
SAUDACAO → COLETA → CONFIRMACAO → CHAMADO → ATENDIMENTO → ENCERRADO
```

1. **Saudação** — recebe o usuário e pede um áudio com Nome, E-mail e Celular.
2. **Coleta** — escuta o áudio (ou imagem da ocorrência) e transcreve com o Gemini.
3. **Confirmação** — devolve a transcrição e pergunta se está correta.
4. **Chamado** — ao confirmar, registra o chamado e orienta aguardar atendimento humano.
5. **Atendimento** — busca respostas em fontes públicas e valida se o usuário compreendeu (com nova busca se não).

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

## 8. Melhorias possíveis

- Adicionar **testes automatizados** do fluxo e monitoramento/alertas.
- Extração estruturada dos dados (nome/e-mail/celular) via saída JSON do Gemini.
