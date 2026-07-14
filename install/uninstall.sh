#!/bin/bash
# MDE LLM-PROXY - Uninstaller
# For manual removal

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
SUDOERS_DIR="/etc/sudoers.d"

echo -e "${BLUE}=== MDE LLM-PROXY Uninstaller ===${NC}"
echo

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Error: This script must be run as root${NC}"
    echo "Please run: sudo $0"
    exit 1
fi

# Confirm removal
read -p "Are you sure you want to uninstall MDE LLM-PROXY? [y/N] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Uninstall cancelled${NC}"
    exit 0
fi

# Stop and disable services
echo "Stopping services..."
systemctl stop matts-console.service 2>/dev/null || true
systemctl stop matts-value-set-proxy.service 2>/dev/null || true
systemctl disable matts-console.service 2>/dev/null || true
systemctl disable matts-value-set-proxy.service 2>/dev/null || true
if command -v tmux >/dev/null 2>&1; then
    tmux kill-session -t matts-irc-bridge 2>/dev/null || true
fi

# Remove symlinks
echo "Removing symlinks..."
rm -f "$BIN_DIR/claude-do"
rm -f "$BIN_DIR/matts-value-set-proxy"
rm -f "$BIN_DIR/matts-v2-console"
rm -f "$BIN_DIR/matts-console"
rm -f "$BIN_DIR/matts-image-studio"
rm -f "$BIN_DIR/matts-irc-bridge"
rm -f "$BIN_DIR/matts-startup-service"
rm -f "$BIN_DIR/matts-startup-helper"

for model in deepseek deepseek-v4 glm mistral codex sd35; do
    rm -f "$BIN_DIR/claude-$model"
done

rm -f "$BIN_DIR/matts-image" 2>/dev/null || true

# Remove installed files
echo "Removing installed files..."
rm -rf "$INSTALL_DIR"
rm -rf "$CONFIG_DIR"
rm -rf "$DOC_DIR"

# Remove systemd services
rm -f "$SYSTEMD_DIR/matts-value-set-proxy.service"
rm -f "$SYSTEMD_DIR/matts-console.service"

# Remove profile script
rm -f "$PROFILE_DIR/matts-value-set.sh"

# Remove privileged helper allowlist
rm -f "$SUDOERS_DIR/matts-value-set-startup"

# Remove log and data directories (ask first)
echo
read -p "Remove data directories ($DATA_DIR, $LOG_DIR)? Data will be lost. [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Removing data directories..."
    rm -rf "$DATA_DIR"
    rm -rf "$LOG_DIR"
else
    echo -e "${YELLOW}Keeping data directories${NC}"
    echo "  $DATA_DIR"
    echo "  $LOG_DIR"
fi

# Reload systemd
systemctl daemon-reload

# Remove user/group if no files owned by them
echo
read -p "Remove matts user and group? (Only if no other files are owned by them) [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    # Check if user/group own any files
    user_files=$(find / -user matts 2>/dev/null | grep -v "^/proc" | head -5)
    group_files=$(find / -group matts 2>/dev/null | grep -v "^/proc" | head -5)

    if [ -z "$user_files" ]; then
        echo "Removing matts user..."
        userdel matts 2>/dev/null || echo -e "${YELLOW}Could not remove matts user${NC}"
    else
        echo -e "${YELLOW}matts user still owns files, skipping:${NC}"
        echo "$user_files" | head -3
    fi

    if [ -z "$group_files" ]; then
        echo "Removing matts group..."
        groupdel matts 2>/dev/null || echo -e "${YELLOW}Could not remove matts group${NC}"
    else
        echo -e "${YELLOW}matts group still owns files, skipping:${NC}"
        echo "$group_files" | head -3
    fi
else
    echo -e "${YELLOW}Keeping matts user and group${NC}"
fi

echo -e "\n${GREEN}=== Uninstall Complete ===${NC}"
echo
echo "MDE LLM-PROXY has been uninstalled."
echo
echo "Note: If you want to completely remove all traces:"
echo "  1. Remove any remaining configuration in ~/.cache/matts-value-set/"
echo "  2. Remove tmux sessions: tmux kill-session -t matts-*"
echo "  3. Remove environment variables from your shell config"
echo
echo -e "${GREEN}Uninstall successful!${NC}"
