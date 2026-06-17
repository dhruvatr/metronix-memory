#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! command -v uv >/dev/null 2>&1; then
  echo "Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

# --- Docker pre-check: detect, offer install, verify daemon ---

DOCKER_CMD="docker"
NEED_SUDO_DOCKER=false

if ! command -v docker >/dev/null 2>&1; then
  echo ""
  echo "Docker is required to run Metatron Core but was not found." >&2
  if [[ "$(uname -s)" == "Linux" ]]; then
    echo "Install Docker Engine automatically? (will ask for sudo) [Y/n] " >&2
    read -r REPLY
    if [[ -z "$REPLY" ]] || [[ "$REPLY" =~ ^[Yy] ]]; then
      echo "Installing Docker Engine..." >&2
      curl -fsSL https://get.docker.com | sh
      echo "Docker installed. Adding user to docker group..." >&2
      sudo usermod -aG docker "$USER" 2>/dev/null || true
      # In current shell group membership hasn't taken effect — use sudo for now
      NEED_SUDO_DOCKER=true
      DOCKER_CMD="sudo docker"
    else
      echo "Install manually:  curl -fsSL https://get.docker.com | sh" >&2
      exit 1
    fi
  elif [[ "$(uname -s)" == "Darwin" ]]; then
    if command -v brew >/dev/null 2>&1; then
      echo "Install Docker Desktop via Homebrew? [Y/n] " >&2
      read -r REPLY
      if [[ -z "$REPLY" ]] || [[ "$REPLY" =~ ^[Yy] ]]; then
        echo "Installing Docker Desktop..." >&2
        brew install --cask docker
        echo "" >&2
        echo "Docker Desktop installed. Now you MUST launch it manually:" >&2
        echo "  open /Applications/Docker.app" >&2
        echo "  Wait for the whale icon to appear in the menu bar." >&2
        echo "  Then re-run: ./install/bootstrap.sh" >&2
        exit 0
      else
        echo "Install manually:  brew install --cask docker" >&2
        exit 1
      fi
    else
      echo "Homebrew not found. Install Docker Desktop manually:" >&2
      echo "  https://www.docker.com/products/docker-desktop/" >&2
      echo "Download, install, launch, and wait for the whale icon in the menu bar." >&2
      exit 1
    fi
  else
    echo "Download Docker Desktop from https://www.docker.com/products/docker-desktop/" >&2
    exit 1
  fi
fi

# --- Daemon reachable check ---
if ! $DOCKER_CMD info >/dev/null 2>&1; then
  echo "" >&2
  echo "Docker daemon is not reachable." >&2
  if [[ "$(uname -s)" == "Linux" ]]; then
    if ! systemctl is-active --quiet docker 2>/dev/null; then
      echo "Docker service is not running. Start it:" >&2
      echo "  sudo systemctl start docker" >&2
    fi
    if ! groups "$USER" | grep -q docker 2>/dev/null; then
      echo "User '$USER' may not be in the 'docker' group." >&2
      echo "Run: sudo usermod -aG docker $USER" >&2
      echo "Then log out and back in (or run: newgrp docker)." >&2
    fi
  elif [[ "$(uname -s)" == "Darwin" ]]; then
    echo "Launch Docker.app from Applications and wait for the whale icon." >&2
  fi
  exit 1
fi

cd "$REPO_ROOT/installer"
exec uv run --project . python -m metatron_installer "$@"
