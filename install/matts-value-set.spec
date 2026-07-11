Name:           matts-value-set
Version:        1.0.0
Release:        1%{?dist}
Summary:        MDE LLM-PROXY - Local Anthropic-compatible proxy for various LLM models
License:        MIT
URL:            https://github.com/user/matts-value-set-proxy
Source0:        %{name}-%{version}.tar.gz

BuildRequires:  python3-devel
Requires:       python3
Requires:       python3-requests
Requires:       tmux
Requires:       bash
Requires(post): systemd
Requires(postun): systemd

BuildArch:      noarch

%description
MDE LLM-PROXY is a local Anthropic API-compatible proxy server
that translates Anthropic Messages API calls to OpenAI-compatible endpoints for
various LLM models. It provides:

- Local proxy server on port 18081
- Web console on port 18181 with authentication
- Cost tracking and budget enforcement
- Integration with Claude Code CLI
- Global model registry support for Serverless and Dedicated Inference models

Run `claude-do --list-models` or open Console > LLM Management to inspect the
active registry, access state, pricing, and routing policy.

%prep
%setup -q

%build
# No compilation needed for Python scripts

%install
# Create directory structure
mkdir -p %{buildroot}/usr/lib/matts-value-set
mkdir -p %{buildroot}/usr/bin
mkdir -p %{buildroot}/etc/matts-value-set
mkdir -p %{buildroot}/usr/lib/systemd/system
mkdir -p %{buildroot}/etc/profile.d
mkdir -p %{buildroot}/var/log/matts-value-set
mkdir -p %{buildroot}/var/lib/matts-value-set/{studio,images}
mkdir -p %{buildroot}/%{_docdir}/%{name}

# Install main scripts
install -m 755 claude-DO.sh %{buildroot}/usr/lib/matts-value-set/
install -m 755 do-anthropic-proxy.py %{buildroot}/usr/lib/matts-value-set/
install -m 755 image-studio.py %{buildroot}/usr/lib/matts-value-set/
install -m 755 matts-console.py %{buildroot}/usr/lib/matts-value-set/

# Install wrapper scripts
for script in claude-deepseek claude-deepseek-v4 claude-glm claude-mistral claude-codex claude-sd35; do
    if [ -f "$script" ]; then
        install -m 755 "$script" %{buildroot}/usr/lib/matts-value-set/
    fi
done

# Install matts-image CLI
if [ -f "matts-image" ]; then
    install -m 755 matts-image %{buildroot}/usr/lib/matts-value-set/
fi

# Install application package, templates, and read-only config (required at
# runtime; the console imports src.console.* and serves templates/).
cp -r src %{buildroot}/usr/lib/matts-value-set/
cp -r templates %{buildroot}/usr/lib/matts-value-set/
cp -r config %{buildroot}/usr/lib/matts-value-set/

# Seed the writable model registry under the data dir (source of truth must be
# writable; environment.conf points MATTS_MODEL_CONFIG_FILE here).
mkdir -p %{buildroot}/var/lib/matts-value-set/config
if [ -f config/models.json ]; then
    install -m 644 config/models.json %{buildroot}/var/lib/matts-value-set/config/models.json
elif [ -f config/default-models.json ]; then
    install -m 644 config/default-models.json %{buildroot}/var/lib/matts-value-set/config/models.json
fi

# Create symlinks in /usr/bin
ln -sf ../lib/matts-value-set/claude-DO.sh %{buildroot}/usr/bin/claude-do
ln -sf ../lib/matts-value-set/do-anthropic-proxy.py %{buildroot}/usr/bin/matts-value-set-proxy
ln -sf ../lib/matts-value-set/matts-console.py %{buildroot}/usr/bin/matts-console
ln -sf ../lib/matts-value-set/image-studio.py %{buildroot}/usr/bin/matts-image-studio

# Create symlinks for wrapper scripts
for model in deepseek deepseek-v4 glm mistral codex sd35; do
    if [ -f "claude-$model" ]; then
        ln -sf ../lib/matts-value-set/claude-$model %{buildroot}/usr/bin/claude-$model
    fi
done

if [ -f "matts-image" ]; then
    ln -sf ../lib/matts-value-set/matts-image %{buildroot}/usr/bin/matts-image
fi

# Install systemd services
install -m 644 install/systemd/matts-value-set-proxy.service %{buildroot}/usr/lib/systemd/system/
install -m 644 install/systemd/matts-console.service %{buildroot}/usr/lib/systemd/system/

# Install environment configuration
install -m 640 install/environment.conf %{buildroot}/etc/matts-value-set/
install -m 755 install/profile.d/matts-value-set.sh %{buildroot}/etc/profile.d/

# Install documentation
install -m 644 README.md %{buildroot}/%{_docdir}/%{name}/
install -m 644 CLAUDE.md %{buildroot}/%{_docdir}/%{name}/
install -m 644 LICENSE %{buildroot}/%{_docdir}/%{name}/
install -m 644 CHANGELOG.md %{buildroot}/%{_docdir}/%{name}/

# Create empty log files
touch %{buildroot}/var/log/matts-value-set/proxy.jsonl
touch %{buildroot}/var/log/matts-value-set/usage.jsonl

%post
# Create matts user and group
if ! getent group matts >/dev/null; then
    groupadd -r matts
fi

if ! getent passwd matts >/dev/null; then
    useradd -r -g matts -s /usr/sbin/nologin \
            -d /var/lib/matts-value-set -c "MDE LLM-PROXY Service User" matts
fi

# Set permissions
chown -R matts:matts /var/lib/matts-value-set
chown -R matts:matts /var/log/matts-value-set
chmod 750 /var/lib/matts-value-set
chmod 750 /var/log/matts-value-set
chmod 640 /etc/matts-value-set/environment.conf

# Create token file placeholder on first run
if [ ! -f /var/lib/matts-value-set/.mcnf-do-model-access-token ]; then
    touch /var/lib/matts-value-set/.mcnf-do-model-access-token
    chmod 600 /var/lib/matts-value-set/.mcnf-do-model-access-token
    chown matts:matts /var/lib/matts-value-set/.mcnf-do-model-access-token
fi

# Reload systemd daemon
systemctl daemon-reload

# Enable proxy service by default (console can be started manually)
systemctl enable matts-value-set-proxy.service

%preun
# Stop services before removal
systemctl stop matts-console.service || true
systemctl stop matts-value-set-proxy.service || true

%postun
# Reload systemd after removal
systemctl daemon-reload

# Remove user/group if package is being erased
if [ "$1" -eq 0 ]; then
    # Remove user and group if they exist and no files are owned by them
    if [ "$(find / -user matts 2>/dev/null | wc -l)" -eq 0 ]; then
        userdel matts 2>/dev/null || true
    fi

    if [ "$(find / -group matts 2>/dev/null | wc -l)" -eq 0 ]; then
        groupdel matts 2>/dev/null || true
    fi
fi

%files
%dir /usr/lib/matts-value-set
%dir /etc/matts-value-set
%dir /var/lib/matts-value-set
%dir /var/log/matts-value-set
%dir /var/lib/matts-value-set/studio
%dir /var/lib/matts-value-set/images

# Main scripts
/usr/lib/matts-value-set/claude-DO.sh
/usr/lib/matts-value-set/do-anthropic-proxy.py
/usr/lib/matts-value-set/image-studio.py
/usr/lib/matts-value-set/matts-console.py

# Wrapper scripts
/usr/lib/matts-value-set/claude-deepseek
/usr/lib/matts-value-set/claude-deepseek-v4
/usr/lib/matts-value-set/claude-glm
/usr/lib/matts-value-set/claude-mistral
/usr/lib/matts-value-set/claude-codex
/usr/lib/matts-value-set/claude-sd35

# Additional CLI tools
/usr/lib/matts-value-set/matts-image

# Application package, templates, and read-only config
/usr/lib/matts-value-set/src
/usr/lib/matts-value-set/templates
/usr/lib/matts-value-set/config

# Writable model registry seed (source of truth; may be edited at runtime)
%dir /var/lib/matts-value-set/config
%config(noreplace) /var/lib/matts-value-set/config/models.json

# Symlinks
/usr/bin/claude-do
/usr/bin/matts-value-set-proxy
/usr/bin/matts-console
/usr/bin/matts-image-studio
/usr/bin/claude-deepseek
/usr/bin/claude-deepseek-v4
/usr/bin/claude-glm
/usr/bin/claude-mistral
/usr/bin/claude-codex
/usr/bin/claude-sd35
/usr/bin/matts-image

# Systemd services
/usr/lib/systemd/system/matts-value-set-proxy.service
/usr/lib/systemd/system/matts-console.service

# Configuration
/etc/matts-value-set/environment.conf

# Profile script
/etc/profile.d/matts-value-set.sh

# Documentation
%doc %{_docdir}/%{name}/README.md
%doc %{_docdir}/%{name}/CLAUDE.md
%doc %{_docdir}/%{name}/LICENSE
%doc %{_docdir}/%{name}/CHANGELOG.md

# Log files (created empty)
/var/log/matts-value-set/proxy.jsonl
/var/log/matts-value-set/usage.jsonl

%changelog
* Mon Jul 7 2026 MDE LLM-PROXY <matts@example.com> 1.0.0-1
- Initial RPM package
- Systemd service integration
- Web console with authentication
- Cost tracking and budget enforcement
- Bash login welcome integration
