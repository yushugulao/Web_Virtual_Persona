param(
  [string]$ServerHost = "<PUBLIC_SERVER_IP>",
  [string]$PublicIp = "<PUBLIC_SERVER_IP>",
  [string]$RootUser = "root",
  [string]$DeployUser = "deploy-admin",
  [string]$TunnelUser = "persona-tunnel",
  [string]$KeyDir = "secrets\public_tunnel",
  [switch]$UsePlink,
  [string]$PlinkHostKey = "SHA256:vLxMnYqRKcSC83sb7TjIDGAbWBkzGU0oU5jPzbD1FRc"
)

$ErrorActionPreference = "Stop"

$projectRoot = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")
Set-Location -LiteralPath $projectRoot

$keyRoot = Join-Path $projectRoot $KeyDir
New-Item -ItemType Directory -Force -Path $keyRoot | Out-Null

$deployKey = Join-Path $keyRoot "deploy_admin_ed25519"
$tunnelKey = Join-Path $keyRoot "persona_tunnel_ed25519"

function Ensure-KeyPair {
  param([string]$Path, [string]$Comment)
  if (-not (Test-Path -LiteralPath $Path)) {
    ssh-keygen -t ed25519 -f $Path -N '""' -C $Comment | Out-Null
  }
}

Ensure-KeyPair -Path $deployKey -Comment "web-avatar-deploy-admin"
Ensure-KeyPair -Path $tunnelKey -Comment "web-avatar-persona-tunnel"

$deployPub = (Get-Content -LiteralPath "$deployKey.pub" -Raw).Trim()
$tunnelPub = (Get-Content -LiteralPath "$tunnelKey.pub" -Raw).Trim()
$nginxConf = (Get-Content -LiteralPath (Join-Path $projectRoot "deploy\public\nginx-web-avatar.conf.example") -Raw).
  Replace("server_name <PUBLIC_SERVER_IP>;", "server_name $PublicIp;")

$remoteScriptTemplate = @'
set -euo pipefail

PUBLIC_IP='__PUBLIC_IP__'
DEPLOY_USER='__DEPLOY_USER__'
TUNNEL_USER='__TUNNEL_USER__'
DEPLOY_PUB='__DEPLOY_PUB__'
TUNNEL_PUB='__TUNNEL_PUB__'

if command -v apt-get >/dev/null 2>&1; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y nginx openssl
elif command -v dnf >/dev/null 2>&1; then
  dnf install -y nginx openssl
elif command -v yum >/dev/null 2>&1; then
  yum install -y nginx openssl
else
  echo 'No supported package manager found.' >&2
  exit 1
fi

ensure_user() {
  local name="$1"
  if ! id "$name" >/dev/null 2>&1; then
    useradd -m -s /bin/bash "$name"
  fi
  install -d -m 700 -o "$name" -g "$name" "/home/$name/.ssh"
}

install_key() {
  local name="$1"
  local key="$2"
  printf '%s\n' "$key" > "/home/$name/.ssh/authorized_keys"
  chown "$name:$name" "/home/$name/.ssh/authorized_keys"
  chmod 600 "/home/$name/.ssh/authorized_keys"
}

ensure_user "$DEPLOY_USER"
ensure_user "$TUNNEL_USER"
install_key "$DEPLOY_USER" "$DEPLOY_PUB"
install_key "$TUNNEL_USER" "$TUNNEL_PUB"

cat > "/etc/sudoers.d/web-avatar-deploy-admin" <<SUDOERS
$DEPLOY_USER ALL=(root) NOPASSWD:ALL
SUDOERS
chmod 440 "/etc/sudoers.d/web-avatar-deploy-admin"

install -d -m 755 /opt/web-avatar/frontend
install -d -m 700 /etc/nginx/ssl
install -d -m 755 /etc/ssh/sshd_config.d

openssl req -x509 -nodes -newkey rsa:2048 -sha256 -days 365 \
  -keyout /etc/nginx/ssl/web-avatar.key \
  -out /etc/nginx/ssl/web-avatar.crt \
  -subj "/CN=$PUBLIC_IP" \
  -addext "subjectAltName=IP:$PUBLIC_IP"

cat > /etc/nginx/conf.d/web-avatar.conf <<'NGINX_CONF'
__NGINX_CONF__
NGINX_CONF

cat > /etc/ssh/sshd_config.d/90-web-avatar-tunnel.conf <<'SSHD_CONF'
AllowTcpForwarding yes
GatewayPorts no
X11Forwarding no
SSHD_CONF

if command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
  firewall-cmd --permanent --add-service=ssh
  firewall-cmd --permanent --add-service=https
  firewall-cmd --reload
fi

if command -v ufw >/dev/null 2>&1 && ufw status | grep -qi active; then
  ufw allow OpenSSH
  ufw allow 443/tcp
fi

nginx -t
systemctl enable nginx
systemctl restart nginx
systemctl reload sshd 2>/dev/null || systemctl reload ssh 2>/dev/null || true

echo 'Web Avatar public ECS bootstrap complete.'
'@

$remoteScript = $remoteScriptTemplate.
  Replace("__PUBLIC_IP__", $PublicIp).
  Replace("__DEPLOY_USER__", $DeployUser).
  Replace("__TUNNEL_USER__", $TunnelUser).
  Replace("__DEPLOY_PUB__", $deployPub).
  Replace("__TUNNEL_PUB__", $tunnelPub).
  Replace("__NGINX_CONF__", $nginxConf)
$remoteScript = $remoteScript.TrimStart([char]0xFEFF)

Write-Host "Bootstrapping $ServerHost. Enter the root SSH password if prompted." -ForegroundColor Cyan
if ($UsePlink) {
  $rootPassword = $env:PERSONA_RAG_ECS_ROOT_PASSWORD
  if (-not $rootPassword) {
    throw "Set PERSONA_RAG_ECS_ROOT_PASSWORD in the current process before using -UsePlink."
  }
  $plink = Get-Command plink.exe -ErrorAction Stop
  $remoteScript | & $plink.Source -ssh -batch -hostkey $PlinkHostKey -pw $rootPassword "$RootUser@$ServerHost" "bash -s"
} else {
  $remoteScript | ssh -o StrictHostKeyChecking=accept-new "$RootUser@$ServerHost" "bash -s"
}

Write-Host ""
Write-Host "Local deploy key: $deployKey" -ForegroundColor Green
Write-Host "Local tunnel key: $tunnelKey" -ForegroundColor Green
Write-Host "Next: run scripts\deploy\publish_frontend_to_ecs.ps1 and scripts\deploy\start_public_reverse_tunnel.ps1" -ForegroundColor Green
