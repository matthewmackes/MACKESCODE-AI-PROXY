#!/bin/bash
# Test script for MDE LLM-PROXY Installer
# Runs without sudo to verify installation components

echo "=== MDE LLM-PROXY Installer Test ==="
echo

echo "1. Checking installed files..."
FILES_OK=0
TOTAL_FILES=0

check_file() {
    local file="$1"
    TOTAL_FILES=$((TOTAL_FILES + 1))
    if [ -e "$file" ]; then
        echo "  ✅ $file"
        FILES_OK=$((FILES_OK + 1))
        return 0
    else
        echo "  ❌ $file (missing)"
        return 1
    fi
}

echo "Main scripts:"
check_file "/usr/lib/matts-value-set/claude-DO.sh"
check_file "/usr/lib/matts-value-set/do-anthropic-proxy.py"
check_file "/usr/lib/matts-value-set/image-studio.py"
check_file "/usr/lib/matts-value-set/matts-console.py"

echo -e "\nWrapper scripts:"
check_file "/usr/lib/matts-value-set/claude-deepseek"
check_file "/usr/lib/matts-value-set/claude-deepseek-v4"
check_file "/usr/lib/matts-value-set/claude-glm"
check_file "/usr/lib/matts-value-set/claude-mistral"
check_file "/usr/lib/matts-value-set/claude-codex"
check_file "/usr/lib/matts-value-set/claude-sd35"

echo -e "\n2. Checking symlinks..."
SYMLINKS_OK=0
TOTAL_SYMLINKS=0

check_symlink() {
    local symlink="$1"
    local target="$2"
    TOTAL_SYMLINKS=$((TOTAL_SYMLINKS + 1))

    if [ -L "$symlink" ]; then
        local actual_target
        actual_target=$(readlink -f "$symlink" 2>/dev/null || echo "")
        if [ "$actual_target" = "$target" ]; then
            echo "  ✅ $symlink -> $target"
            SYMLINKS_OK=$((SYMLINKS_OK + 1))
        else
            echo "  ❌ $symlink points to wrong target: $actual_target"
        fi
    else
        echo "  ❌ $symlink (not a symlink)"
    fi
}

check_symlink "/usr/bin/claude-do" "/usr/lib/matts-value-set/claude-DO.sh"
check_symlink "/usr/bin/matts-value-set-proxy" "/usr/lib/matts-value-set/do-anthropic-proxy.py"
check_symlink "/usr/bin/matts-console" "/usr/lib/matts-value-set/matts-console.py"
check_symlink "/usr/bin/claude-deepseek" "/usr/lib/matts-value-set/claude-deepseek"
check_symlink "/usr/bin/claude-deepseek-v4" "/usr/lib/matts-value-set/claude-deepseek-v4"
check_file "/usr/bin/matts-image"  # Not checking symlink since it might be direct file

echo -e "\n3. Testing command execution..."
COMMANDS_OK=0
TOTAL_COMMANDS=0

test_command() {
    local cmd="$1"
    local expected="$2"
    TOTAL_COMMANDS=$((TOTAL_COMMANDS + 1))

    if command -v "$cmd" >/dev/null 2>&1; then
        echo "  ✅ $cmd is available"
        COMMANDS_OK=$((COMMANDS_OK + 1))

        # Try to run with --help
        if timeout 2 "$cmd" --help >/dev/null 2>&1; then
            echo "     (--help works)"
        else
            echo "     (--help failed, but command exists)"
        fi
    else
        echo "  ❌ $cmd not found"
    fi
}

test_command "claude-do" "main launcher"
test_command "claude-deepseek" "deepseek wrapper"
test_command "claude-glm" "glm wrapper"

echo -e "\n4. Testing profile script..."
if [ -f "/etc/profile.d/matts-value-set.sh" ]; then
    echo "  ✅ Profile script installed"

    # Check syntax
    if bash -n "/etc/profile.d/matts-value-set.sh" 2>/dev/null; then
        echo "     (Syntax OK)"
    else
        echo "     (Syntax check failed)"
    fi
else
    echo "  ❌ Profile script not installed"
fi

echo -e "\n5. Testing systemd service files..."
if [ -f "/usr/lib/systemd/system/matts-value-set-proxy.service" ]; then
    echo "  ✅ Proxy service file installed"
else
    echo "  ⚠️ Proxy service file not found (may need sudo to install)"
fi

if [ -f "/usr/lib/systemd/system/matts-console.service" ]; then
    echo "  ✅ Console service file installed"
else
    echo "  ⚠️ Console service file not found (may need sudo to install)"
fi

echo -e "\n=== Summary ==="
echo "Files: $FILES_OK/$TOTAL_FILES"
echo "Symlinks: $SYMLINKS_OK/$TOTAL_SYMLINKS"
echo "Commands: $COMMANDS_OK/$TOTAL_COMMANDS"

if [ $FILES_OK -eq $TOTAL_FILES ] && [ $SYMLINKS_OK -eq $TOTAL_SYMLINKS ]; then
    echo -e "\n✅ Installation test PASSED!"
    echo "The core components are installed correctly."
    echo
    echo "Next steps (require sudo):"
    echo "1. Complete user/group setup: sudo useradd -r -g matts -s /usr/sbin/nologin matts"
    echo "2. Install systemd services"
    echo "3. Set up data directories"
    echo "4. Start services: sudo systemctl start matts-value-set-proxy"
else
    echo -e "\n⚠️ Installation test PARTIAL"
    echo "Some components are missing or incorrect."
    echo "Run with sudo for complete installation."
fi

echo -e "\nTo see the welcome message on next login:"
echo "1. Ensure /etc/profile.d/matts-value-set.sh is installed"
echo "2. Log out and log back in"
echo "3. Or manually source: source /etc/profile.d/matts-value-set.sh"
