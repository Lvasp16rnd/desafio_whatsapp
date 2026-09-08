#!/usr/bin/env bash
# =====================================================================
# setup.sh — Provisiona o ambiente do agente WhatsApp (n8n + Redis)
# Executar no Ubuntu/WSL2, na maquina onde o n8n vai rodar.
# Requisitos: Docker rodando + OpenSSH client.
#
# Uso:
#   ./scripts/setup.sh                # sobe tudo + abre a ponte SSH no final
#   ./scripts/setup.sh --skip-tunnel  # sobe apenas os containers
# =====================================================================

set -euo pipefail

ENV_FILE=".env"
SKIP_TUNNEL=false
[ "${1:-}" = "--skip-tunnel" ] && SKIP_TUNNEL=true

step() { printf '\n==> %s\n' "$1"; }
info() { printf '    %s\n' "$1"; }

# 1. Carregar .env (removendo CR, compativel com arquivo editado no Windows)
if [ -f "$ENV_FILE" ]; then
  step "Carregando $ENV_FILE"
  set -a
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%%$'\r'}"
    case "$line" in
      \#*|"") continue ;;
      *=*) export "$line" ;;
    esac
  done < "$ENV_FILE"
  set +a
else
  echo "AVISO: .env nao encontrado. Copie .env.example para .env e preencha." >&2
fi

# 2. Verificar Docker
step "Verificando Docker"
if ! command -v docker >/dev/null 2>&1; then
  echo "ERRO: docker nao encontrado. Instale o Docker." >&2
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "ERRO: Docker nao esta rodando. Inicie o Docker (Docker Desktop ou 'sudo service docker start')." >&2
  exit 1
fi
info "Docker OK"

# 3. Rede compartilhada (n8n <-> redis)
step "Criando rede agente-net"
docker network create agente-net >/dev/null 2>&1 || info "Rede ja existe (ok)"

# 4. Redis (estado da conversa)
step "Subindo Redis"
docker rm -f redis >/dev/null 2>&1 || true
docker run -d --name redis --network agente-net redis:alpine
info "Redis rodando na rede agente-net (porta 6379)"

# 5. n8n (orquestracao)
step "Subindo n8n"
docker rm -f n8n >/dev/null 2>&1 || true
docker run -d --name n8n \
  --network agente-net \
  -p 127.0.0.1:5678:5678 \
  -v n8n_data:/home/node/.n8n \
  -e N8N_SECURE_COOKIE=false \
  -e N8N_BLOCK_ENV_ACCESS_IN_NODE=false \
  -e GENERIC_TIMEZONE=America/Sao_Paulo \
  -e WHATSAPP_TOKEN="${WHATSAPP_TOKEN:-}" \
  -e WHATSAPP_PHONE_ID="${PHONE_NUMBER_ID:-}" \
  -e WHATSAPP_VERIFY_TOKEN="${VERIFY_TOKEN:-}" \
  -e GEMINI_API_KEY="${GEMINI_API_KEY:-}" \
  -e GEMINI_MODEL="${GEMINI_MODEL:-gemini-2.0-flash}" \
  docker.n8n.io/n8nio/n8n
info "n8n rodando em http://localhost:5678"

# 6. Ponte SSH reversa (VM -> PC)
step "Concluido!"
echo "Editor do n8n : http://localhost:5678"
echo "Webhook (via Caddy) : https://${DUCKDNS_SUBDOMAIN:-agenteautomacao}.duckdns.org/webhook/whatsapp"

if [ "$SKIP_TUNNEL" = true ]; then
  echo "Tunel pulado (--skip-tunnel)."
  exit 0
fi

VM_USER="${VM_USER:-ubuntu}"
VM_HOST="${VM_HOST:-}"
VM_SSH_KEY="${VM_SSH_KEY:-}"
VM_SSH_KEY="${VM_SSH_KEY/#\~/$HOME}"

if [ -z "$VM_HOST" ]; then
  echo "AVISO: VM_HOST vazio no .env. Abra a ponte SSH manualmente:" >&2
  echo "  ssh -N -R 5678:localhost:5678 -i sua-chave.pem $VM_USER@IP_DA_VM" >&2
  exit 1
fi

# Ajusta permissao da chave. Em mount Windows (/mnt/), o chmod nao funciona,
# entao copia a chave para ~/.ssh e usa a copia.
if [ -n "$VM_SSH_KEY" ] && [ -f "$VM_SSH_KEY" ]; then
  case "$VM_SSH_KEY" in
    /mnt/*)
      mkdir -p "$HOME/.ssh"
      local_key="$HOME/.ssh/$(basename "$VM_SSH_KEY")"
      cp "$VM_SSH_KEY" "$local_key"
      chmod 600 "$local_key"
      info "Chave em mount Windows detectada; copiada para $local_key"
      VM_SSH_KEY="$local_key"
      ;;
    *)
      chmod 600 "$VM_SSH_KEY"
      ;;
  esac
fi

step "Abrindo tunel SSH reverso para $VM_USER@$VM_HOST"
info "Deixe este terminal aberto durante a demonstracao. Ctrl+C para encerrar."

if [ -n "$VM_SSH_KEY" ]; then
  ssh -N -R 5678:localhost:5678 -i "$VM_SSH_KEY" \
    -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes \
    "$VM_USER@$VM_HOST"
else
  echo "AVISO: VM_SSH_KEY vazio; tentando sem chave (so funciona com outra autenticacao)." >&2
  ssh -N -R 5678:localhost:5678 \
    -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes \
    "$VM_USER@$VM_HOST"
fi
