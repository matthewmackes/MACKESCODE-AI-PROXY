#!/bin/bash
# Matts Value Set Claude Code Proxy - Bash Login Integration
# Source this file from /etc/profile.d/matts-value-set.sh

# Skip if disabled
if [ "${MATTS_VALUE_SET_NO_WELCOME:-0}" = "1" ]; then
    return 0
fi

# Only show in interactive shells
case $- in
    *i*) ;;
    *) return 0 ;;
esac

# Function to check service status
_matts_status() {
    local service="$1"
    if systemctl is-active --quiet "$service" 2>/dev/null; then
        echo -e "\033[0;32m●\033[0m $service: \033[0;32mACTIVE\033[0m"
    elif systemctl is-enabled --quiet "$service" 2>/dev/null; then
        echo -e "\033[0;33m○\033[0m $service: \033[0;33mINACTIVE\033[0m"
    else
        echo -e "\033[0;31m×\033[0m $service: \033[0;31mNOT INSTALLED\033[0m"
    fi
}

# Function to get auth token
_matts_get_token() {
    local token_file="/var/lib/matts-value-set/studio/console-auth-token"
    if [ -f "$token_file" ]; then
        cat "$token_file" 2>/dev/null | head -1 | tr -d '[:space:]'
    else
        echo "NOT_GENERATED_YET"
    fi
}

# Function to get web console URL
_matts_get_url() {
    local token
    token=$(_matts_get_token)
    if [ "$token" = "NOT_GENERATED_YET" ]; then
        echo "http://localhost:18181/?token=(generate-with-first-start)"
    else
        echo "http://localhost:18181/?token=${token}"
    fi
}

# Show welcome message if Matts Value Set is installed
if command -v claude-do >/dev/null 2>&1; then
    echo -e "\n\033[1;36m=== Matts Value Set Claude Code Proxy ===\033[0m"

    # Service status
    echo -e "\033[1;34mServices:\033[0m"
    _matts_status "matts-value-set-proxy"
    _matts_status "matts-console"

    # Access information
    echo -e "\n\033[1;34mAccess:\033[0m"
    echo "Proxy API:      http://127.0.0.1:18081/v1/"
    echo "Web Console:    $(_matts_get_url)"

    # Quick commands
    echo -e "\n\033[1;34mQuick Commands:\033[0m"
    echo "Start services: sudo systemctl start matts-value-set-proxy matts-console"
    echo "Stop services:  sudo systemctl stop matts-value-set-proxy matts-console"
    echo "Status:         sudo systemctl status matts-value-set-proxy"
    echo "Logs:           sudo journalctl -u matts-value-set-proxy -f"
    echo "Launch Claude:  claude-deepseek, claude-glm, claude-mistral, claude-codex"

    # Model registry
    echo -e "\n\033[1;34mModel Registry:\033[0m"
    echo "List models:    claude-do --list-models"
    echo "Manage models:  Web Console > LLM Management"

    # Token location
    echo -e "\n\033[1;34mConfiguration:\033[0m"
    echo "Token file:     /var/lib/matts-value-set/.mcnf-do-model-access-token"
    echo "Usage logs:     /var/log/matts-value-set/usage.jsonl"
    echo "Config:         /etc/matts-value-set/environment.conf"

    # Tips
    echo -e "\n\033[1;34mTips:\033[0m"
    echo "• Disable this message: export MATTS_VALUE_SET_NO_WELCOME=1"
    echo "• Generate images: matts-image \"your prompt\""
    echo "• View web console: xdg-open $(_matts_get_url)"

    echo -e "\033[1;36m===========================================\033[0m"
fi
