#!/usr/bin/env bash
#
# provision.sh — prvi boot svežeg Hetzner Cloud servera, Ubuntu 24.04 LTS.
#
# Pokreće se JEDNOM, kao root, odmah posle kreiranja servera:
#
#   ssh root@<IP>
#   curl -fsSL -o provision.sh <raw URL ove skripte>   # ili je nalepi preko scp
#   bash provision.sh mm
#
# Argument je ime korisnika koji se pravi (podrazumevano: mm).
# Skripta je idempotentna — ponovno pokretanje ne kvari ništa.

set -euo pipefail

DEPLOY_USER="${1:-mm}"
SWAP_GB=4

log() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }
warn() { printf '\n\033[1;33m!!  %s\033[0m\n' "$*"; }

if [[ $EUID -ne 0 ]]; then
  echo "Mora kao root." >&2
  exit 1
fi

# ---------------------------------------------------------------- 1. osnovno
log "Sistemski paketi"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq \
  ca-certificates curl gnupg git ufw fail2ban unattended-upgrades \
  htop ncdu tmux jq rsync

timedatectl set-timezone Europe/Belgrade

# ---------------------------------------------------------------- 2. korisnik
log "Korisnik ${DEPLOY_USER}"
if ! id -u "$DEPLOY_USER" >/dev/null 2>&1; then
  adduser --disabled-password --gecos "" "$DEPLOY_USER"
fi
usermod -aG sudo "$DEPLOY_USER"

# SSH ključ se preuzima od root-a — Hetzner ga je tamo već upisao.
if [[ -f /root/.ssh/authorized_keys ]]; then
  install -d -m 700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "/home/${DEPLOY_USER}/.ssh"
  install -m 600 -o "$DEPLOY_USER" -g "$DEPLOY_USER" \
    /root/.ssh/authorized_keys "/home/${DEPLOY_USER}/.ssh/authorized_keys"
else
  warn "Nema /root/.ssh/authorized_keys. Upiši ključ za ${DEPLOY_USER} PRE nego"
  warn "što se isključi lozinka, inače ostaješ zaključan napolju."
fi

# sudo bez lozinke — korisnik ionako nema lozinku, pristup je isključivo ključem
echo "${DEPLOY_USER} ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/90-${DEPLOY_USER}"
chmod 440 "/etc/sudoers.d/90-${DEPLOY_USER}"

# ---------------------------------------------------------------- 3. SSH
log "SSH: samo ključ, bez root prijave"
cat > /etc/ssh/sshd_config.d/99-hardening.conf <<'EOF'
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
ChallengeResponseAuthentication no
PubkeyAuthentication yes
X11Forwarding no
MaxAuthTries 3
ClientAliveInterval 120
ClientAliveCountMax 3
EOF
# Ubuntu 24.04 koristi socket aktivaciju; port ostaje 22 da se ne dira ssh.socket.
sshd -t
systemctl restart ssh

# ---------------------------------------------------------------- 4. firewall
log "Firewall"
ufw --force reset >/dev/null
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment 'ssh'
ufw allow 80/tcp comment 'http'
ufw allow 443/tcp comment 'https'
ufw --force enable

# Docker piše direktno u iptables i zaobilazi ufw. Zato su u compose-u svi
# interni servisi vezani na 127.0.0.1 — to je stvarna zaštita, ne ufw.
cat > /etc/fail2ban/jail.local <<'EOF'
[sshd]
enabled  = true
backend  = systemd
maxretry = 3
bantime  = 1h
findtime = 10m
EOF
systemctl enable --now fail2ban
systemctl restart fail2ban

# ---------------------------------------------------------------- 5. swap
if ! swapon --show | grep -q '/swapfile'; then
  log "Swap ${SWAP_GB} GB"
  fallocate -l "${SWAP_GB}G" /swapfile
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  sysctl -w vm.swappiness=10 >/dev/null
  echo 'vm.swappiness=10' > /etc/sysctl.d/99-swappiness.conf
fi

# ---------------------------------------------------------------- 6. kernel
log "Kernel parametri"
cat > /etc/sysctl.d/99-persona-os.conf <<'EOF'
# Postgres i Redis vole veće redove
net.core.somaxconn = 1024
net.ipv4.tcp_max_syn_backlog = 2048
# Redis: bez ovoga background save može da padne
vm.overcommit_memory = 1
# Chromium i Playwright otvaraju mnogo fajlova
fs.file-max = 200000
fs.inotify.max_user_watches = 524288
EOF
sysctl --system >/dev/null

cat > /etc/security/limits.d/99-persona-os.conf <<'EOF'
*  soft  nofile  65536
*  hard  nofile  65536
EOF

# ---------------------------------------------------------------- 7. docker
log "Docker Engine"
if ! command -v docker >/dev/null 2>&1; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y -qq \
    docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
usermod -aG docker "$DEPLOY_USER"

# Rotacija logova — bez ovoga Docker json log pojede disk za par nedelja.
cat > /etc/docker/daemon.json <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "50m", "max-file": "3" },
  "live-restore": true
}
EOF
systemctl enable --now docker
systemctl restart docker

# ---------------------------------------------------------------- 8. auto-update
log "Bezbednosne zakrpe automatski"
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
EOF

# ---------------------------------------------------------------- 9. folderi
install -d -o "$DEPLOY_USER" -g "$DEPLOY_USER" "/home/${DEPLOY_USER}/apps"
install -d -o "$DEPLOY_USER" -g "$DEPLOY_USER" "/home/${DEPLOY_USER}/backups"

# ---------------------------------------------------------------- gotovo
log "Gotovo"
cat <<EOF

  Korisnik      : ${DEPLOY_USER}
  Prijava       : ssh ${DEPLOY_USER}@$(curl -fsS --max-time 5 ifconfig.me || echo '<IP>')
  Root prijava  : isključena
  Lozinke       : isključene
  Otvoreni port : 22, 80, 443
  Docker        : $(docker --version)
  Compose       : $(docker compose version --short)

  PROVERI DA NOVA PRIJAVA RADI PRE NEGO ŠTO ZATVORIŠ OVU SESIJU.

  Sledeće:
    ssh ${DEPLOY_USER}@<IP>
    cd ~/apps && git clone <repo> mm-persona-os && cd mm-persona-os
    cp .env.prod.example .env.prod && nano .env.prod
    docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build

EOF
