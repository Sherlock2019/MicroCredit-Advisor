#!/usr/bin/env bash
# MicroCredit Advisor POC launcher — local machine, WSL or an AWS EC2 instance.
#
#   ./start.sh                  start; on AWS EC2 the portal is served on the instance's public IP automatically
#   ./start.sh --public         expose the portal on 0.0.0.0:8480 on any machine; demo sign-in needs an access key
#   ./start.sh --local          keep the portal on 127.0.0.1 only, even on EC2
#   ./start.sh --ollama         use local Ollama models instead of the deterministic mock model
#   ./start.sh --install-docker install Docker first (Ubuntu or Amazon Linux 2023; uses sudo)
#   ./start.sh stop | status | logs | reset
#
# Everything runs in Docker Compose. No cloud services are created and nothing is billed by this script.
set -euo pipefail
cd "$(dirname "$0")"

PUBLIC=auto; OLLAMA=0; INSTALL=0; CMD=start
for arg in "$@"; do
  case "$arg" in
    --public) PUBLIC=1 ;;
    --local) PUBLIC=0 ;;
    --ollama) OLLAMA=1 ;;
    --install-docker) INSTALL=1 ;;
    stop|status|logs|reset) CMD=$arg ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "Unknown option: $arg (see --help)"; exit 2 ;;
  esac
done

say() { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# EC2 instance metadata (IMDSv2). Prints the public IPv4, or nothing when not on EC2 / no public IP.
ec2_public_ip() {
  local token
  token=$(curl -s -m 1 -X PUT http://169.254.169.254/latest/api/token -H "X-aws-ec2-metadata-token-ttl-seconds: 60" 2>/dev/null) || return 0
  [ -n "$token" ] || return 0
  curl -s -m 1 -f -H "X-aws-ec2-metadata-token: $token" http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || true
}

install_docker() {
  [ -r /etc/os-release ] || die "Cannot detect the OS; install Docker manually."
  . /etc/os-release
  case "$ID" in
    ubuntu|debian)
      sudo apt-get update -y && sudo apt-get install -y docker.io docker-compose-v2 openssl curl python3 ;;
    amzn)
      sudo dnf install -y docker openssl curl python3
      sudo mkdir -p /usr/local/lib/docker/cli-plugins
      sudo curl -fsSL "https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-linux-$(uname -m)" \
        -o /usr/local/lib/docker/cli-plugins/docker-compose
      sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose ;;
    *) die "Unsupported OS '$ID' for --install-docker; install Docker and the compose plugin manually." ;;
  esac
  sudo systemctl enable --now docker
  sudo usermod -aG docker "$USER" || true
  say "Docker installed. If 'permission denied' appears, log out and back in (docker group), then re-run ./start.sh"
}

[ "$INSTALL" = 1 ] && install_docker
command -v docker >/dev/null || die "Docker is not installed. Run: ./start.sh --install-docker"
DOCKER="docker"
if ! docker info >/dev/null 2>&1; then
  if sudo -n docker info >/dev/null 2>&1; then DOCKER="sudo docker"; else die "Cannot talk to Docker (is it running? are you in the docker group?)"; fi
fi
$DOCKER compose version >/dev/null 2>&1 || die "The Docker compose plugin is missing. Run: ./start.sh --install-docker"
COMPOSE="$DOCKER compose"

case "$CMD" in
  stop) $COMPOSE down; say "Stopped. Data is kept in Docker volumes (./start.sh reset deletes it)."; exit 0 ;;
  status) $COMPOSE ps; exit 0 ;;
  logs) $COMPOSE logs -f --tail=100; exit 0 ;;
  reset) read -r -p "Delete ALL demo data (database + uploaded files)? [y/N] " ok; [ "$ok" = y ] || exit 0
         $COMPOSE down -v; say "Reset done. Run ./start.sh to start with fresh demo data."; exit 0 ;;
esac

command -v python3 >/dev/null || die "python3 is required to create .env"
command -v curl >/dev/null || die "curl is required"
python3 scripts/make_env.py

PUBLIC_IP=$(ec2_public_ip)
if [ "$PUBLIC" = auto ]; then
  if [ -n "$PUBLIC_IP" ]; then PUBLIC=1; say "AWS EC2 detected (public IP $PUBLIC_IP): serving the portal publicly. Use --local to keep it on 127.0.0.1."
  else PUBLIC=0; fi
fi

# Demo access key for public mode. Default: betterworld (it is in this public repo, so it only deters casual visitors).
# Override per run: DEMO_ACCESS_KEY=something ./start.sh
KEY="${DEMO_ACCESS_KEY:-betterworld}"
export PORTAL_BIND=127.0.0.1 DEMO_ACCESS_KEY=""
if [ "$PUBLIC" = 1 ]; then
  export PORTAL_BIND=0.0.0.0 DEMO_ACCESS_KEY="$KEY"
fi
if [ "$OLLAMA" = 1 ]; then
  export MODEL_PROVIDER=ollama
  say "Using Ollama at ${OLLAMA_BASE_URL:-http://host.docker.internal:11434} (model ${OLLAMA_CHAT_MODEL:-qwen2.5:7b}); embeddings stay on the offline hash model."
fi

say "Building and starting containers (first run takes a few minutes)…"
$COMPOSE up -d --build

PORT=$(grep -E '^PORTAL_PORT=' .env | cut -d= -f2); PORT=${PORT:-8480}
say "Waiting for the platform to become ready…"
for i in $(seq 1 90); do
  if curl -fsS "http://127.0.0.1:${PORT}/portal-health" >/dev/null 2>&1 && \
     $COMPOSE exec -T api-gateway python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8400/ready',timeout=3)" >/dev/null 2>&1; then
    READY=1; break
  fi
  if [ "$($COMPOSE ps -a --format '{{.Service}} {{.State}} {{.ExitCode}}' | awk '$1=="migrate" && $2=="exited" && $3!="0"')" != "" ]; then
    $COMPOSE logs migrate | tail -30; die "Database migration or seeding failed (see above)."
  fi
  sleep 2
done
[ "${READY:-0}" = 1 ] || { $COMPOSE ps; die "Timed out waiting for readiness. Check: ./start.sh logs"; }

HOST=127.0.0.1
if [ "$PUBLIC" = 1 ]; then
  HOST=${PUBLIC_IP:-$(hostname -I | awk '{print $1}')}
fi

cat <<EOF

  MicroCredit Advisor is running (SYNTHETIC demo data).

  Portal ............ http://${HOST}:${PORT}
  Loan officer ...... http://${HOST}:${PORT}/#/finance
  Project map ....... http://${HOST}:${PORT}/#/map
  Farmer app mockup . http://${HOST}:${PORT}/farmer-mockup.html
  API docs .......... http://127.0.0.1:${GATEWAY_PORT:-8400}/docs   (this machine only)

  Demo accounts: choose one in the top-right menu (loan officer fatima.finance, credit reviewer kofi.credit, ...).
EOF
if [ "$PUBLIC" = 1 ]; then
  cat <<EOF
  Public mode: the portal asks once for the demo access key:  ${DEMO_ACCESS_KEY}
  Open TCP ${PORT} in the EC2 security group to YOUR IP only. Synthetic data only; do not enter real borrower data.
EOF
fi
echo "  Stop: ./start.sh stop     Logs: ./start.sh logs"
