# MDE LLM-PROXY - Installation Guide

This directory contains installation files for MDE LLM-PROXY.

## Installation Options

### 1. RPM Package (Recommended for Fedora/RHEL/CentOS)

Build and install the RPM package:

```bash
# Build the RPM (requires rpm-build package)
cd /path/to/project
mkdir -p ~/rpmbuild/{SOURCES,SPECS}
cp install/matts-value-set.spec ~/rpmbuild/SPECS/
tar czf ~/rpmbuild/SOURCES/matts-value-set-1.0.0.tar.gz --exclude='.git' --exclude='*.pyc' *

# Build the RPM
rpmbuild -ba ~/rpmbuild/SPECS/matts-value-set.spec

# Install the RPM
sudo rpm -ivh ~/rpmbuild/RPMS/noarch/matts-value-set-1.0.0-1.*.noarch.rpm
```

### 2. Manual Installation (All Distributions)

Use the manual installer script:

```bash
cd /path/to/project/install
sudo ./install.sh
```

### 3. Manual Uninstallation

```bash
cd /path/to/project/install
sudo ./uninstall.sh
```

## Files Included

### Systemd Services
- `systemd/matts-value-set-proxy.service` - Proxy server (port 18081)
- `systemd/matts-console.service` - V2 React console (port 18182)

### Configuration
- `environment.conf` - Environment variables for services
- `matts-value-set.sh` - Bash profile script for welcome message

### Packaging
- `matts-value-set.spec` - RPM spec file
- `install.sh` - Manual installer script
- `uninstall.sh` - Manual uninstaller script

## Service Management

After installation:

```bash
# Start services
sudo systemctl start matts-value-set-proxy
sudo systemctl start matts-console

# Enable auto-start on boot
sudo systemctl enable matts-value-set-proxy
sudo systemctl enable matts-console  # Optional

# Check status
sudo systemctl status matts-value-set-proxy
sudo systemctl status matts-console

# View logs
sudo journalctl -u matts-value-set-proxy -f
sudo journalctl -u matts-console -f
```

## Features

### Auto-Restart (Watchdog)
Both services include systemd watchdog features:
- `Restart=always` - Auto-restart on failure
- `RestartSec=10` - Wait 10 seconds before restart
- `StartLimitInterval=60` - Rate limiting
- `StartLimitBurst=5` - Max 5 restarts in 60 seconds

### Security Hardening
Services run with security restrictions:
- Dedicated `matts` user/group
- `NoNewPrivileges=true`
- `ProtectSystem=strict`
- `PrivateTmp=true`
- `ProtectHome=true`

### Log Management
- Logs to journald (`journalctl`)
- JSONL logs in `/var/log/matts-value-set/`
- Usage tracking in `/var/log/matts-value-set/usage.jsonl`

### Bash Integration
Login welcome message shows:
- Service status (proxy & console)
- Access URLs with authentication tokens
- Available models
- Quick commands for common operations

Disable welcome message:
```bash
export MATTS_VALUE_SET_NO_WELCOME=1
# Add to ~/.bashrc to make permanent
```

## File Locations

### Installation Directories
- `/usr/lib/matts-value-set/` - Main scripts
- `/usr/bin/` - Command-line tools (symlinks)
- `/etc/matts-value-set/` - Configuration
- `/var/lib/matts-value-set/` - Data files
- `/var/log/matts-value-set/` - Log files
- `/usr/share/doc/matts-value-set/` - Documentation

### Command-Line Tools
- `claude-do` - Main launcher
- `matts-value-set-proxy` - Start proxy directly
- `matts-v2-console` / `matts-console` - Start the V2 React console directly
- `claude-deepseek`, `claude-glm`, `claude-mistral`, `claude-codex` - Model wrappers
- `matts-image` - Image generator CLI

## Configuration

### Environment Variables
Edit `/etc/matts-value-set/environment.conf`:

```bash
# Upstream inference endpoint
MATTS_VALUE_SET_BASE_URL="https://inference.do-ai.run"

# Default model
MATTS_VALUE_SET_MODEL="deepseek-3.2"

# Proxy configuration
MATTS_VALUE_SET_PROXY_HOST="127.0.0.1"
MATTS_VALUE_SET_PROXY_PORT="18081"

# Web console
MATTS_STUDIO_HOST="0.0.0.0"
MATTS_STUDIO_PORT="18182"
```

### Token Management
- Model access token: `/var/lib/matts-value-set/.mcnf-do-model-access-token`
- Console auth token: `/var/lib/matts-value-set/studio/console-auth-token` (auto-generated)

The launcher does not include a default model access key. Populate `MATTS_VALUE_SET_TOKEN_FILE` or run with `MATTS_VALUE_SET_ALLOW_KEY_OVERRIDE=1` and `MATTS_VALUE_SET_ACCESS_KEY` for an intentional one-run bootstrap.

### Model Registry

The active model registry is `config/models.json` by default, or `MATTS_MODEL_CONFIG_FILE` when overridden. Packaged installs seed the writable registry at `/var/lib/matts-value-set/config/models.json`. `--list-models`, proxy `/v1/models`, Code/Create selectors, Console LLM Management, Serverless catalog import, and model hero cards all use this registry plus runtime access audit state from `MATTS_MODEL_ACCESS_STATE_FILE`. Do not maintain a separate static model list in service configuration unless it is only a bootstrap fallback.

### DigitalOcean Permissions

DigitalOcean billing reports need `DIGITALOCEAN_TOKEN` and, for daily spend insights, `DIGITALOCEAN_ACCOUNT_URN`; the token needs billing read access. Dedicated Inference automation needs permissions to create, inspect, and destroy Dedicated Inference resources and issue access tokens. The Console preflight and lifecycle panels report missing permissions, account/balance status when available, region/GPU placement, and teardown countdowns.

## V2 Console Access

1. Start the V2 console:
   ```bash
   sudo systemctl start matts-console
   ```

2. Get the authentication token:
   ```bash
   sudo cat /var/lib/matts-value-set/studio/console-auth-token
   ```

3. Access the console:
   ```
   http://localhost:18182/?token=YOUR_TOKEN_HERE
   ```

4. Open the AgentBoard tab to inspect and control all local tmux sessions. It uses the existing console token and reads local tmux state plus proxy logs; no separate AgentBoard service is installed.
5. Open Console > LLM Management to audit the model key and sync allowed/forbidden model states before relying on Code/Create selectors.
6. Open Console > Inference Hosting Lifecycle to build, monitor, keep alive, or tear down Dedicated Inference.

## Troubleshooting

### Service Won't Start
Check logs:
```bash
sudo journalctl -u matts-value-set-proxy -xe
```

Common issues:
1. Missing dependencies: Install `python3-requests`
2. Port conflict: Check if ports 18081/18182 are already in use
3. Permission issues: Verify `matts` user can write to data/log directories

### Web Console Not Accessible
1. Check firewall:
   ```bash
   sudo firewall-cmd --add-port=18182/tcp --permanent
   sudo firewall-cmd --reload
   ```
2. Verify service is running:
   ```bash
   sudo systemctl status matts-console
   curl http://localhost:18182/v2/health  # Should return V2 health JSON
   ```

### Welcome Message Not Showing
1. Ensure `/etc/profile.d/matts-value-set.sh` exists
2. Check if `MATTS_VALUE_SET_NO_WELCOME` is set
3. Verify you're in an interactive shell

## Uninstallation

### RPM Package
```bash
sudo rpm -e matts-value-set
```

### Manual Uninstallation
```bash
cd /path/to/project/install
sudo ./uninstall.sh
```

The uninstaller will:
1. Stop and disable services
2. Remove installed files
3. Optionally remove data directories
4. Optionally remove matts user/group

## Support

For issues or questions:
1. Check logs: `sudo journalctl -u matts-value-set-proxy`
2. Verify installation: `sudo ./install.sh --check`
3. Review configuration: `/etc/matts-value-set/environment.conf`
