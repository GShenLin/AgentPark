#!/usr/bin/env bash
set -euo pipefail

# Run as root after extracting the deployment bundle into /opt/agentpark-coordinator.
cd /opt/agentpark-coordinator
getent passwd agentpark >/dev/null || useradd --system --home-dir /var/lib/agentpark-signaling --shell /sbin/nologin agentpark
install -d -m 0750 -o root -g agentpark /etc/agentpark
install -d -m 0700 -o agentpark -g agentpark /var/lib/agentpark-signaling
python3.11 -m venv .venv
.venv/bin/python -m pip install --disable-pip-version-check -r deploy/peer-network/requirements.txt
python3.11 - <<'PY'
import os
import secrets
from pathlib import Path
path = Path('/etc/agentpark/signaling.env')
if not path.exists():
    content = '\n'.join([
        'AGENTPARK_PORTAL_PASSWORD=' + secrets.token_urlsafe(24),
        'AGENTPARK_SIGNALING_HOST=127.0.0.1',
        'AGENTPARK_SIGNALING_PORT=8790',
        'AGENTPARK_PORTAL_WEB_ROOT=/opt/agentpark-coordinator/webui/dist',
    ]) + '\n'
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as handle:
        handle.write(content)
PY
install -m 0644 deploy/peer-network/agentpark-signaling.service /etc/systemd/system/agentpark-signaling.service
python3.11 deploy/peer-network/configure_turn.py --public-ip "${AGENTPARK_PUBLIC_IP:?Set the public IPv4}" --private-ip "${AGENTPARK_PRIVATE_IP:?Set the relay interface IPv4}"
install -m 0644 deploy/peer-network/agentpark-turn.service /etc/systemd/system/agentpark-turn.service
chmod 0750 /etc/agentpark
systemctl daemon-reload
if systemctl list-unit-files agentpark-stun.service --no-legend | grep -q agentpark-stun; then
    systemctl disable --now agentpark-stun
fi
systemctl enable --now agentpark-signaling agentpark-turn
systemctl restart agentpark-signaling agentpark-turn
systemctl is-active agentpark-signaling agentpark-turn
curl --fail --silent http://127.0.0.1:8790/ >/dev/null || {
    sleep 2
    curl --fail --silent http://127.0.0.1:8790/ >/dev/null
}
