#!/usr/bin/env bash
# install.sh — DeerFlow SuperAgent runtime installer
# Runs once inside a fresh Debian bookworm LXC container.
# Idempotent: safe to re-run on an already-provisioned container.
set -euo pipefail

echo "[deer-flow] installing DeerFlow SuperAgent"

# ---------------------------------------------------------------------------
# 1. System dependencies
# ---------------------------------------------------------------------------
DEBIAN_FRONTEND=noninteractive apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends \
  python3 python3-venv git curl ca-certificates build-essential

# ---------------------------------------------------------------------------
# 2. Install uv (astral) if absent, and resolve its real path
# ---------------------------------------------------------------------------
# uv provisions Python 3.12 and the backend deps from backend/.python-version.
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi

# The installer drops uv into ~/.local/bin (or /root/.local/bin when run as
# root); make sure it is on PATH for the rest of this script.
export PATH="$HOME/.local/bin:/root/.local/bin:$PATH"

if ! command -v uv >/dev/null 2>&1; then
  echo "[deer-flow] FATAL: uv not found after install"
  exit 1
fi
UV_BIN="$(command -v uv)"

UV_VERSION=$(uv --version 2>/dev/null || echo "unknown")
echo "[deer-flow] installed: $UV_VERSION ($UV_BIN)"

# ---------------------------------------------------------------------------
# 3. Clone DeerFlow into /opt/deer-flow
# ---------------------------------------------------------------------------
if [ -d /opt/deer-flow/.git ]; then
  echo "[deer-flow] repo already present, pulling latest"
  git -C /opt/deer-flow pull --ff-only
else
  git clone --depth 1 https://github.com/bytedance/deer-flow /opt/deer-flow
fi

# ---------------------------------------------------------------------------
# 4. Provision the backend (Python 3.12 + deps) with uv
# ---------------------------------------------------------------------------
cd /opt/deer-flow/backend
"$UV_BIN" sync

# ---------------------------------------------------------------------------
# 5. Write config.yaml pointing DeerFlow at the taOS LiteLLM proxy
# ---------------------------------------------------------------------------
# Literal $ENV_VAR tokens are expanded by DeerFlow at load time from the env
# the deployer injects (TAOS_MODEL, OPENAI_API_KEY, OPENAI_BASE_URL).
# token_counting: char avoids DeerFlow's startup tiktoken cache network fetch,
# which matters in restricted containers.
cat > /opt/deer-flow/config.yaml <<'CONFIG'
models:
  - name: taos-default
    use: langchain_openai:ChatOpenAI
    model: $TAOS_MODEL
    api_key: $OPENAI_API_KEY
    base_url: $OPENAI_BASE_URL
    request_timeout: 600.0

memory:
  token_counting: char
CONFIG

# ---------------------------------------------------------------------------
# 6. Capture the deployer-injected env into an EnvironmentFile
# ---------------------------------------------------------------------------
# install.sh runs via `incus exec`, which DOES inherit the container's
# environment.* config, so OPENAI_BASE_URL / OPENAI_API_KEY / TAOS_MODEL are
# visible here. A systemd service does NOT inherit those automatically (it
# starts from a clean environment), so DeerFlow's config.yaml $VAR expansion
# would otherwise see empty values. Snapshot them into an EnvironmentFile the
# unit reads (the same pattern the Hermes framework uses).
cat > /opt/deer-flow/deer-flow.env <<ENVFILE
TAOS_MODEL=${TAOS_MODEL:-}
OPENAI_API_KEY=${OPENAI_API_KEY:-}
OPENAI_BASE_URL=${OPENAI_BASE_URL:-}
DEER_FLOW_CONFIG_PATH=/opt/deer-flow/config.yaml
PYTHONPATH=.
ENVFILE
chmod 600 /opt/deer-flow/deer-flow.env

# ---------------------------------------------------------------------------
# 7. Systemd unit
# ---------------------------------------------------------------------------
# Runs as root: the uv-managed venv lives under /opt and running as root avoids
# venv-permission complexity. The container itself is the isolation boundary.
mkdir -p /var/log/deer-flow

cat > /etc/systemd/system/deer-flow.service <<UNIT
[Unit]
Description=DeerFlow SuperAgent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/deer-flow/backend
EnvironmentFile=/opt/deer-flow/deer-flow.env
ExecStart=${UV_BIN} run uvicorn app.gateway.app:app --host 127.0.0.1 --port 8001
Restart=on-failure
RestartSec=5
StandardOutput=append:/var/log/deer-flow/deer-flow.log
StandardError=append:/var/log/deer-flow/deer-flow.log

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable deer-flow.service

echo "[deer-flow] install complete (service enabled, start deferred to deployer)"
echo "[deer-flow] backend serves the runs API on 127.0.0.1:8001"
echo "[deer-flow] deployer injects OPENAI_BASE_URL, OPENAI_API_KEY, TAOS_MODEL"
echo "             into the container env (inherited by the systemd service)"
