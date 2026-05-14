#!/usr/bin/env bash
set -euo pipefail

REPO="${WEB_VIRTUAL_PERSONA_REPO:-yushugulao/Web_Virtual_Persona}"
BRANCH="${WEB_VIRTUAL_PERSONA_BRANCH:-main}"
DEST="${WEB_VIRTUAL_PERSONA_DIR:-$HOME/Web_Virtual_Persona}"
REPLACE="${WEB_VIRTUAL_PERSONA_REPLACE:-0}"
DRY_RUN=0

DEPLOY_ARGS=()
while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      DEPLOY_ARGS+=("$1")
      shift
      ;;
    --replace)
      REPLACE=1
      shift
      ;;
    *)
      DEPLOY_ARGS+=("$1")
      shift
      ;;
  esac
done

say() {
  printf '\n==> %s\n' "$1"
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1
}

ensure_bootstrap_tools() {
  local missing=()
  need_cmd python3 || missing+=("python3")
  { need_cmd curl || need_cmd wget; } || missing+=("curl")
  need_cmd tar || missing+=("tar")
  if [ "${#missing[@]}" -eq 0 ]; then
    return 0
  fi

  say "Installing bootstrap tools: ${missing[*]}"
  if [ "$DRY_RUN" = "1" ]; then
    return 0
  fi

  local sudo_cmd=""
  if [ "$(id -u)" -ne 0 ]; then
    sudo_cmd="sudo"
  fi

  if need_cmd apt-get; then
    $sudo_cmd apt-get update
    $sudo_cmd apt-get install -y ca-certificates curl tar python3
  elif need_cmd dnf; then
    $sudo_cmd dnf install -y ca-certificates curl tar python3
  elif need_cmd yum; then
    $sudo_cmd yum install -y ca-certificates curl tar python3
  elif need_cmd pacman; then
    $sudo_cmd pacman -Sy --noconfirm ca-certificates curl tar python
  else
    echo "Missing bootstrap tools (${missing[*]}), and no supported package manager was found." >&2
    exit 1
  fi
}

download_source() {
  local url="https://codeload.github.com/${REPO}/tar.gz/refs/heads/${BRANCH}"
  local tmp_dir
  tmp_dir="$(mktemp -d)"
  local archive="$tmp_dir/source.tar.gz"
  say "Downloading Web Virtual Persona from ${REPO}@${BRANCH}"
  if [ "$DRY_RUN" = "1" ]; then
    echo "Would download $url"
    echo "Would extract into $DEST"
    return 0
  fi
  if need_cmd curl; then
    curl -fL --progress-bar "$url" -o "$archive"
  else
    wget --progress=bar:force "$url" -O "$archive"
  fi
  local archive_root
  archive_root="$(tar -tzf "$archive" | head -n 1 | cut -d/ -f1)"
  tar -xzf "$archive" -C "$tmp_dir"
  local extracted="$tmp_dir/$archive_root"
  if [ -d "$DEST" ] && [ "$REPLACE" = "1" ]; then
    rm -rf "$DEST"
  fi
  if [ ! -d "$DEST" ]; then
    mkdir -p "$(dirname "$DEST")"
    mv "$extracted" "$DEST"
  else
    echo "Using existing project directory: $DEST"
  fi
}

main() {
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  ensure_bootstrap_tools
  download_source
  if [ "$DRY_RUN" = "1" ]; then
    return 0
  fi
  cd "$DEST"
  say "Starting deployment wizard"
  python3 scripts/deploy/portable_deploy.py "${DEPLOY_ARGS[@]}"
}

main
