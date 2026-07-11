#!/bin/bash
# MDE LLM-PROXY - Manual Installer
# For systems without RPM package manager

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

INSTALL_DIR="/usr/lib/matts-value-set"
BIN_DIR="/usr/bin"
CONFIG_DIR="/etc/matts-value-set"
SYSTEMD_DIR="/usr/lib/systemd/system"
PROFILE_DIR="/etc/profile.d"
DATA_DIR="/var/lib/matts-value-set"
LOG_DIR="/var/log/matts-value-set"
DOC_DIR="/usr/share/doc/matts-value-set"

echo -e "${BLUE}=== MDE LLM-PROXY Installer ===${NC}"
echo

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Error: This script must be run as root${NC}"
    echo "Please run: sudo $0"
    exit 1
fi

# Detect distribution
if [ -f /etc/fedora-release ] || [ -f /etc/redhat-release ] || [ -f /etc/centos-release ]; then
    DISTRO="fedora"
elif [ -f /etc/debian_version ] || [ -f /etc/lsb-release ]; then
    DISTRO="debian"
else
    DISTRO="generic"
fi

echo "Detected distribution: $DISTRO"
echo

# Check dependencies
echo "Checking dependencies..."
missing_deps=()

check_dep() {
    if ! command -v "$1" >/dev/null 2>&1; then
        missing_deps+=("$1")
    fi
}

check_dep "python3"
check_dep "tmux"
check_dep "bash"

if [ ${#missing_deps[@]} -gt 0 ]; then
    echo -e "${YELLOW}Missing dependencies:${NC}"
    for dep in "${missing_deps[@]}"; do
        echo "  - $dep"
    done
    echo
    echo "Please install missing dependencies before continuing."
    if [ "$DISTRO" = "fedora" ]; then
        echo "Run: sudo dnf install python3 tmux bash"
    elif [ "$DISTRO" = "debian" ]; then
        echo "Run: sudo apt-get install python3 tmux bash"
    fi
    exit 1
fi

# Check Python requests module
if ! python3 -c "import requests" 2>/dev/null; then
    echo -e "${YELLOW}Python requests module not found${NC}"
    if [ "$DISTRO" = "fedora" ]; then
        echo "Installing: sudo dnf install python3-requests"
        dnf install -y python3-requests || {
            echo -e "${RED}Failed to install python3-requests${NC}"
            echo "You can install manually: pip3 install requests"
        }
    elif [ "$DISTRO" = "debian" ]; then
        echo "Installing: sudo apt-get install python3-requests"
        apt-get install -y python3-requests || {
            echo -e "${RED}Failed to install python3-requests${NC}"
            echo "You can install manually: pip3 install requests"
        }
    else
        echo "Please install: pip3 install requests"
    fi
fi

# Create directories
echo "Creating directories..."
mkdir -p "$INSTALL_DIR"
mkdir -p "$CONFIG_DIR"
mkdir -p "$SYSTEMD_DIR"
mkdir -p "$PROFILE_DIR"
mkdir -p "$DATA_DIR"/{studio,images}
mkdir -p "$LOG_DIR"
mkdir -p "$DOC_DIR"

# Get script location
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Install files
echo "Installing files..."

# Main scripts
cp "$PROJECT_DIR/claude-DO.sh" "$INSTALL_DIR/"
cp "$PROJECT_DIR/do-anthropic-proxy.py" "$INSTALL_DIR/"
cp "$PROJECT_DIR/image-studio.py" "$INSTALL_DIR/"
cp "$PROJECT_DIR/matts-v2-console.py" "$INSTALL_DIR/"
cp "$PROJECT_DIR/requirements-v2.txt" "$INSTALL_DIR/" 2>/dev/null || true

# Wrapper scripts
for script in claude-deepseek claude-deepseek-v4 claude-glm claude-mistral claude-codex claude-sd35; do
    if [ -f "$PROJECT_DIR/$script" ]; then
        cp "$PROJECT_DIR/$script" "$INSTALL_DIR/"
    fi
done

# Additional CLI tools
if [ -f "$PROJECT_DIR/matts-image" ]; then
    cp "$PROJECT_DIR/matts-image" "$INSTALL_DIR/"
fi

# Application packages, built V2 frontend, and read-only config (required at
# runtime: V2 imports backend.v2 and src.console services; launcher/proxy
# resolve config/ relative to the install dir).
rm -rf "$INSTALL_DIR/src" "$INSTALL_DIR/backend" "$INSTALL_DIR/frontend" "$INSTALL_DIR/config"
cp -r "$PROJECT_DIR/src" "$INSTALL_DIR/"
cp -r "$PROJECT_DIR/backend" "$INSTALL_DIR/"
mkdir -p "$INSTALL_DIR/frontend"
cp "$PROJECT_DIR/frontend/package.json" "$INSTALL_DIR/frontend/" 2>/dev/null || true
cp "$PROJECT_DIR/frontend/package-lock.json" "$INSTALL_DIR/frontend/" 2>/dev/null || true
if [ -d "$PROJECT_DIR/frontend/dist" ]; then
    cp -r "$PROJECT_DIR/frontend/dist" "$INSTALL_DIR/frontend/"
else
    echo "WARNING: frontend/dist is missing. Run 'npm run build --prefix frontend' before installing the V2 console service." >&2
fi
cp -r "$PROJECT_DIR/config" "$INSTALL_DIR/"

# Seed a writable model registry under the data dir. config/models.json is the
# runtime-editable source of truth, so it must not live under the read-only
# install prefix; environment.conf points MATTS_MODEL_CONFIG_FILE here.
mkdir -p "$DATA_DIR/config"
if [ ! -f "$DATA_DIR/config/models.json" ]; then
    if [ -f "$PROJECT_DIR/config/models.json" ]; then
        cp "$PROJECT_DIR/config/models.json" "$DATA_DIR/config/models.json"
    elif [ -f "$PROJECT_DIR/config/default-models.json" ]; then
        cp "$PROJECT_DIR/config/default-models.json" "$DATA_DIR/config/models.json"
    fi
fi

# Set permissions on scripts
chmod 755 "$INSTALL_DIR"/*.sh "$INSTALL_DIR"/*.py "$INSTALL_DIR"/claude-* 2>/dev/null || true
if [ -f "$INSTALL_DIR/matts-image" ]; then
    chmod 755 "$INSTALL_DIR/matts-image"
fi

# Create symlinks
echo "Creating symlinks..."
ln -sf ../lib/matts-value-set/claude-DO.sh "$BIN_DIR/claude-do"
ln -sf ../lib/matts-value-set/do-anthropic-proxy.py "$BIN_DIR/matts-value-set-proxy"
ln -sf ../lib/matts-value-set/matts-v2-console.py "$BIN_DIR/matts-v2-console"
ln -sf ../lib/matts-value-set/matts-v2-console.py "$BIN_DIR/matts-console"
ln -sf ../lib/matts-value-set/image-studio.py "$BIN_DIR/matts-image-studio"

for model in deepseek deepseek-v4 glm mistral codex sd35; do
    if [ -f "$INSTALL_DIR/claude-$model" ]; then
        ln -sf ../lib/matts-value-set/claude-$model "$BIN_DIR/claude-$model"
    fi
done

if [ -f "$INSTALL_DIR/matts-image" ]; then
    ln -sf ../lib/matts-value-set/matts-image "$BIN_DIR/matts-image"
fi

# Install configuration
cp "$SCRIPT_DIR/environment.conf" "$CONFIG_DIR/"
cp "$SCRIPT_DIR/profile.d/matts-value-set.sh" "$PROFILE_DIR/matts-value-set.sh"

# Install systemd services
cp "$SCRIPT_DIR/systemd/matts-value-set-proxy.service" "$SYSTEMD_DIR/"
cp "$SCRIPT_DIR/systemd/matts-console.service" "$SYSTEMD_DIR/"

# Install documentation
cp "$PROJECT_DIR/README.md" "$DOC_DIR/" 2>/dev/null || true
cp "$PROJECT_DIR/CLAUDE.md" "$DOC_DIR/" 2>/dev/null || true
cp "$PROJECT_DIR/LICENSE" "$DOC_DIR/" 2>/dev/null || true
cp "$PROJECT_DIR/CHANGELOG.md" "$DOC_DIR/" 2>/dev/null || true

# Create empty log files
touch "$LOG_DIR/proxy.jsonl"
touch "$LOG_DIR/usage.jsonl"

# Create matts user and group
echo "Creating service user..."
if ! getent group matts >/dev/null; then
    groupadd -r matts
fi

if ! getent passwd matts >/dev/null; then
    useradd -r -g matts -s /usr/sbin/nologin \
            -d "$DATA_DIR" -c "MDE LLM-PROXY Service User" matts
fi

# Set permissions
chown -R matts:matts "$DATA_DIR"
chown -R matts:matts "$LOG_DIR"
chmod 750 "$DATA_DIR"
chmod 750 "$LOG_DIR"
chmod 640 "$CONFIG_DIR/environment.conf"

# Create token file placeholder
if [ ! -f "$DATA_DIR/.mcnf-do-model-access-token" ]; then
    touch "$DATA_DIR/.mcnf-do-model-access-token"
    chmod 600 "$DATA_DIR/.mcnf-do-model-access-token"
    chown matts:matts "$DATA_DIR/.mcnf-do-model-access-token"
    echo "Configure a DigitalOcean model access key in $DATA_DIR/.mcnf-do-model-access-token before starting services."
fi

# Reload systemd
systemctl daemon-reload

# Enable proxy service
systemctl enable matts-value-set-proxy.service

echo -e "\n${GREEN}=== Installation Complete ===${NC}"
echo
echo "Services:"
echo "  Proxy:      matts-value-set-proxy.service (enabled)"
echo "  V2 Console: matts-console.service (can be started manually)"
echo
echo "Quick Start:"
echo "  1. Start services:"
echo "     sudo systemctl start matts-value-set-proxy"
echo "     sudo systemctl start matts-console"
echo
echo "  2. Access V2 console:"
echo "     http://localhost:18182/?token=(check /var/lib/matts-value-set/studio/console-auth-token)"
echo
echo "  3. Use Claude Code:"
echo "     claude-deepseek"
echo "     claude-glm"
echo "     claude-mistral"
echo "     claude-codex"
echo
echo "  4. Generate images:"
echo "     matts-image \"your prompt\""
echo
echo "Configuration:"
echo "  Edit: /etc/matts-value-set/environment.conf"
echo "  Logs: /var/log/matts-value-set/"
echo "  Data: /var/lib/matts-value-set/"
echo
echo "Next login will show a welcome message with status and URLs."
echo
echo -e "${GREEN}Installation successful!${NC}"
