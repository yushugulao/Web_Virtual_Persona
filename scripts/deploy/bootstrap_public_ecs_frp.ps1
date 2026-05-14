param(
  [string]$ServerHost = "<PUBLIC_SERVER_IP>",
  [string]$PublicIp = "<PUBLIC_SERVER_IP>",
  [string]$RootUser = "root",
  [string]$DeployUser = "deploy-admin",
  [string]$KeyDir = "secrets\public_tunnel",
  [string]$FrpVersion = "0.68.0",
  [int]$FrpBindPort = 7000,
  [switch]$UsePlink,
  [string]$PlinkHostKey = ""
)

$ErrorActionPreference = "Stop"

$projectRoot = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")
Set-Location -LiteralPath $projectRoot

$keyRoot = Join-Path $projectRoot $KeyDir
New-Item -ItemType Directory -Force -Path $keyRoot | Out-Null

$deployKey = Join-Path $keyRoot "deploy_admin_ed25519"
$frpTokenPath = Join-Path $keyRoot "frp_token.txt"

function Ensure-KeyPair {
  param([string]$Path, [string]$Comment)
  if (-not (Test-Path -LiteralPath $Path)) {
    ssh-keygen -t ed25519 -f $Path -N '""' -C $Comment | Out-Null
  }
}

function Ensure-Token {
  param([string]$Path)
  if (Test-Path -LiteralPath $Path) {
    return (Get-Content -LiteralPath $Path -Raw).Trim()
  }
  $bytes = New-Object byte[] 32
  $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  try {
    $rng.GetBytes($bytes)
  } finally {
    $rng.Dispose()
  }
  $token = -join ($bytes | ForEach-Object { $_.ToString("x2") })
  Set-Content -LiteralPath $Path -Value $token -Encoding ascii
  return $token
}

Ensure-KeyPair -Path $deployKey -Comment "web-avatar-deploy-admin"
$deployPub = (Get-Content -LiteralPath "$deployKey.pub" -Raw).Trim()
$frpToken = Ensure-Token -Path $frpTokenPath

$nginxConf = (Get-Content -LiteralPath (Join-Path $projectRoot "deploy\public\nginx-web-avatar.conf.example") -Raw).
  Replace("server_name <PUBLIC_SERVER_IP>;", "server_name $PublicIp;")
$frpsConf = (Get-Content -LiteralPath (Join-Path $projectRoot "deploy\public\frps-web-avatar.toml.example") -Raw).
  Replace("__FRP_TOKEN__", $frpToken).
  Replace("bindPort = 7000", "bindPort = $FrpBindPort")

$remoteScriptTemplate = @'
set -euo pipefail

PUBLIC_IP='__PUBLIC_IP__'
DEPLOY_USER='__DEPLOY_USER__'
DEPLOY_PUB='__DEPLOY_PUB__'
FRP_VERSION='__FRP_VERSION__'
FRP_BIND_PORT='__FRP_BIND_PORT__'

if command -v apt-get >/dev/null 2>&1; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y nginx openssl curl tar gzip ca-certificates
elif command -v dnf >/dev/null 2>&1; then
  dnf install -y nginx openssl curl tar gzip ca-certificates
elif command -v yum >/dev/null 2>&1; then
  yum install -y nginx openssl curl tar gzip ca-certificates
else
  echo 'No supported package manager found.' >&2
  exit 1
fi

if ! id "$DEPLOY_USER" >/dev/null 2>&1; then
  useradd -m -s /bin/bash "$DEPLOY_USER"
fi
install -d -m 700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "/home/$DEPLOY_USER/.ssh"
printf '%s\n' "$DEPLOY_PUB" > "/home/$DEPLOY_USER/.ssh/authorized_keys"
chown "$DEPLOY_USER:$DEPLOY_USER" "/home/$DEPLOY_USER/.ssh/authorized_keys"
chmod 600 "/home/$DEPLOY_USER/.ssh/authorized_keys"

cat > "/etc/sudoers.d/web-avatar-deploy-admin" <<SUDOERS
$DEPLOY_USER ALL=(root) NOPASSWD:ALL
SUDOERS
chmod 440 "/etc/sudoers.d/web-avatar-deploy-admin"

install -d -m 755 /opt/web-avatar/frontend
install -d -m 700 /etc/nginx/ssl
install -d -m 755 /etc/frp

FRP_ARCHIVE="/tmp/frp_${FRP_VERSION}_linux_amd64.tar.gz"
FRP_DIR="/tmp/frp_${FRP_VERSION}_linux_amd64"
curl -fsSL "https://github.com/fatedier/frp/releases/download/v${FRP_VERSION}/frp_${FRP_VERSION}_linux_amd64.tar.gz" -o "$FRP_ARCHIVE"
rm -rf "$FRP_DIR"
tar -xzf "$FRP_ARCHIVE" -C /tmp
install -m 755 "$FRP_DIR/frps" /usr/local/bin/frps

cat > /etc/frp/frps.toml <<'FRPS_CONF'
__FRPS_CONF__
FRPS_CONF
chmod 600 /etc/frp/frps.toml

cat > /etc/systemd/system/frps.service <<'FRPS_SERVICE'
[Unit]
Description=frp server for Web Avatar public tunnel
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/frps -c /etc/frp/frps.toml
Restart=always
RestartSec=5s
LimitNOFILE=1048576

[Install]
WantedBy=multi-user.target
FRPS_SERVICE

openssl req -x509 -nodes -newkey rsa:2048 -sha256 -days 365 \
  -keyout /etc/nginx/ssl/web-avatar.key \
  -out /etc/nginx/ssl/web-avatar.crt \
  -subj "/CN=$PUBLIC_IP" \
  -addext "subjectAltName=IP:$PUBLIC_IP"

cat > /etc/nginx/conf.d/web-avatar.conf <<'NGINX_CONF'
__NGINX_CONF__
NGINX_CONF

if command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
  firewall-cmd --permanent --add-service=ssh
  firewall-cmd --permanent --add-service=https
  firewall-cmd --permanent --add-port="${FRP_BIND_PORT}/tcp"
  firewall-cmd --reload
fi

if command -v ufw >/dev/null 2>&1 && ufw status | grep -qi active; then
  ufw allow OpenSSH
  ufw allow 443/tcp
  ufw allow "${FRP_BIND_PORT}/tcp"
fi

/usr/local/bin/frps verify -c /etc/frp/frps.toml
nginx -t
systemctl daemon-reload
systemctl enable frps
systemctl restart frps
systemctl enable nginx
systemctl restart nginx

echo 'Web Avatar public ECS frp bootstrap complete.'
'@

$remoteScript = $remoteScriptTemplate.
  Replace("__PUBLIC_IP__", $PublicIp).
  Replace("__DEPLOY_USER__", $DeployUser).
  Replace("__DEPLOY_PUB__", $deployPub).
  Replace("__FRP_VERSION__", $FrpVersion).
  Replace("__FRP_BIND_PORT__", [string]$FrpBindPort).
  Replace("__FRPS_CONF__", $frpsConf).
  Replace("__NGINX_CONF__", $nginxConf)
$remoteScript = $remoteScript.TrimStart([char]0xFEFF)

Write-Host "Bootstrapping frps and Nginx on $ServerHost. Enter the root SSH password if prompted." -ForegroundColor Cyan
if ($UsePlink) {
  $rootPassword = $env:PERSONA_RAG_ECS_ROOT_PASSWORD
  if (-not $rootPassword) {
    throw "Set PERSONA_RAG_ECS_ROOT_PASSWORD in the current process before using -UsePlink."
  }
  $plink = Get-Command plink.exe -ErrorAction Stop
  $plinkArgs = @("-ssh", "-batch", "-pw", $rootPassword)
  if ($PlinkHostKey) {
    $plinkArgs += @("-hostkey", $PlinkHostKey)
  }
  $remoteScript | & $plink.Source @plinkArgs "$RootUser@$ServerHost" "bash -s"
} else {
  $remoteScript | ssh -o StrictHostKeyChecking=accept-new "$RootUser@$ServerHost" "bash -s"
}

Write-Host ""
Write-Host "Local deploy key: $deployKey" -ForegroundColor Green
Write-Host "Local frp token: $frpTokenPath" -ForegroundColor Green
Write-Host "Next: publish frontend, start local backend, then run scripts\deploy\start_public_frp_tunnel.ps1" -ForegroundColor Green
