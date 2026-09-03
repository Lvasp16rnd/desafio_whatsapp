# =====================================================================
# setup.ps1 — Provisiona o ambiente do agente WhatsApp (n8n + Redis)
#
# Executar no PowerShell (Windows), na máquina onde o n8n vai rodar.
# Requisitos: Docker Desktop rodando + OpenSSH client (padrão no Win10+).
#
# Uso:
#   .\scripts\setup.ps1             # sobe tudo + abre a ponte SSH no final
#   .\scripts\setup.ps1 -SkipTunnel # sobe apenas os containers
# =====================================================================

[CmdletBinding()]
param(
    [string]$EnvFile = ".env",
    [switch]$SkipTunnel
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Info([string]$msg) { Write-Host "    $msg" -ForegroundColor Gray }

# ---------------------------------------------------------------------
# 1. Carrega variáveis do .env (se existir)
# ---------------------------------------------------------------------
if (Test-Path -LiteralPath $EnvFile) {
    Write-Step "Carregando $EnvFile"
    Get-Content -LiteralPath $EnvFile | ForEach-Object {
        if ($_ -match '^\s*([^#][^=]*?)\s*=\s*(.*)$') {
            $key = $matches[1].Trim()
            $val = $matches[2].Trim()
            [Environment]::SetEnvironmentVariable($key, $val, "Process")
        }
    }
} else {
    Write-Warning ".env nao encontrado. Copie .env.example para .env e preencha os valores."
}

# ---------------------------------------------------------------------
# 2. Verifica Docker
# ---------------------------------------------------------------------
Write-Step "Verificando Docker"
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker nao encontrado. Instale o Docker Desktop."
}
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Docker nao esta rodando. Inicie o Docker Desktop."
}
Write-Info "Docker OK"

# ---------------------------------------------------------------------
# 3. Rede compartilhada (n8n <-> redis)
# ---------------------------------------------------------------------
Write-Step "Criando rede agente-net"
docker network create agente-net *> $null
if ($LASTEXITCODE -ne 0) { Write-Info "Rede ja existe (ok)" }

# ---------------------------------------------------------------------
# 4. Redis (estado da conversa)
# ---------------------------------------------------------------------
Write-Step "Subindo Redis"
docker rm -f redis *> $null
docker run -d --name redis --network agente-net redis:alpine
if ($LASTEXITCODE -ne 0) { throw "Falha ao subir o Redis" }
Write-Info "Redis rodando na rede agente-net (porta 6379)"

# ---------------------------------------------------------------------
# 5. n8n (orquestracao)
# ---------------------------------------------------------------------
Write-Step "Subindo n8n"
docker rm -f n8n *> $null
docker run -d --name n8n `
  --network agente-net `
  -p 127.0.0.1:5678:5678 `
  -v n8n_data:/home/node/.n8n `
  -e N8N_SECURE_COOKIE=false `
  -e GENERIC_TIMEZONE=America/Sao_Paulo `
  -e N8N_DEFAULT_BINARY_DATA_MODE=filesystem `
  -e WHATSAPP_TOKEN=$env:WHATSAPP_TOKEN `
  -e WHATSAPP_PHONE_ID=$env:PHONE_NUMBER_ID `
  -e WHATSAPP_VERIFY_TOKEN=$env:VERIFY_TOKEN `
  -e GEMINI_API_KEY=$env:GEMINI_API_KEY `
  docker.n8n.io/n8nio/n8n
if ($LASTEXITCODE -ne 0) { throw "Falha ao subir o n8n" }
Write-Info "n8n rodando em http://localhost:5678"

# ---------------------------------------------------------------------
# 6. Ponte SSH reversa (VM -> PC)
# ---------------------------------------------------------------------
Write-Step "Concluido!"
Write-Host "Editor do n8n : http://localhost:5678"
Write-Host "Webhook (via Caddy) : https://$env:DUCKDNS_SUBDOMAIN.duckdns.org/webhook/whatsapp"

if (-not $SkipTunnel) {
    $vmUser = if ($env:VM_USER) { $env:VM_USER } else { "opc" }
    $vmHost = if ($env:VM_HOST) { $env:VM_HOST } else { "137.131.151.6" }

    Write-Step "Abrindo tunel SSH reverso para $vmUser@$vmHost"
    Write-Info "Deixe este terminal aberto durante a demonstracao. Ctrl+C para encerrar."
    ssh -N -R 5678:localhost:5678 "$vmUser@$vmHost" `
        -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes
}
