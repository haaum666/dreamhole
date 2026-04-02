"""Deploy backend to server via SSH."""
import paramiko
import os
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env.deploy"))

HOST = os.getenv("DEPLOY_HOST", "")
USER = os.getenv("DEPLOY_USER", "root")
PASS = os.getenv("DEPLOY_PASS", "")
REMOTE = "/opt/hh-extension"

FILES = [
    "backend/config.py",
    "backend/database.py",
    "backend/crawler.py",
    "backend/api.py",
    "backend/main.py",
    "backend/requirements.txt",
    "backend/.env",
]

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS)

def run(cmd):
    _, stdout, stderr = ssh.exec_command(cmd)
    out = stdout.read().decode()
    err = stderr.read().decode()
    if out: print(out)
    if err: print(err)

# Setup
run(f"mkdir -p {REMOTE}")
run("apt-get install -y postgresql postgresql-contrib python3-pip python3-venv 2>/dev/null | tail -5")
run("systemctl start postgresql")
run("""sudo -u postgres psql -c "CREATE USER hhuser WITH PASSWORD 'hhpass';" 2>/dev/null || true""")
run("""sudo -u postgres psql -c "CREATE DATABASE hhdb OWNER hhuser;" 2>/dev/null || true""")
run(f"python3 -m venv {REMOTE}/venv 2>/dev/null || true")

# Upload files
sftp = ssh.open_sftp()
local_base = os.path.dirname(os.path.abspath(__file__))
for f in FILES:
    local_path = os.path.join(local_base, f)
    remote_path = f"{REMOTE}/{os.path.basename(f)}"
    print(f"Uploading {f} -> {remote_path}")
    sftp.put(local_path, remote_path)
sftp.close()

# Install deps
run(f"{REMOTE}/venv/bin/pip install -r {REMOTE}/requirements.txt -q")

# Create systemd service
service = f"""[Unit]
Description=HH Extension Backend
After=network.target postgresql.service

[Service]
WorkingDirectory={REMOTE}
ExecStart={REMOTE}/venv/bin/python main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
"""
import tempfile, os as _os
with tempfile.NamedTemporaryFile(mode="w", suffix=".service", delete=False) as tmp:
    tmp.write(service)
    tmp_path = tmp.name

sftp2 = ssh.open_sftp()
sftp2.put(tmp_path, "/etc/systemd/system/hh-extension.service")
sftp2.close()
_os.unlink(tmp_path)

run("systemctl daemon-reload")
run("systemctl enable hh-extension")
run("systemctl restart hh-extension")
run("sleep 3 && systemctl status hh-extension --no-pager")

ssh.close()
print("Done!")
