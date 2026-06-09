#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${PROJECT_ROOT}/.env"
ENV_EXAMPLE_FILE="${PROJECT_ROOT}/.env.example"
VPS_ENV_EXAMPLE_FILE="${PROJECT_ROOT}/.env.vps.example"
STARTUP_TIMEOUT_SECONDS="${STARTUP_TIMEOUT_SECONDS:-600}"
COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.vps.yml)
COMPOSE_PARALLEL_LIMIT="${COMPOSE_PARALLEL_LIMIT:-1}"
SERVICES=(postgres redis api worker web)
NGINX_SITE_NAME="doc-translator"
OS_FAMILY=""
OS_ID=""
OS_MAJOR_VERSION=""
OS_CODENAME=""
PACKAGE_MANAGER=""
NGINX_SITE_PATH=""
NGINX_SITE_LINK=""
NGINX_DEFAULT_SITE_LINK=""
COMPOSE_COMMAND=()

log() {
  printf '==> %s\n' "$*"
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

has_command() {
  command -v "$1" >/dev/null 2>&1
}

require_root() {
  [[ "${EUID}" -eq 0 ]] || die "Please run this script as root, for example: sudo bash ./deploy-vps.sh"
}

assert_project_root() {
  [[ -f "${PROJECT_ROOT}/docker-compose.yml" ]] || die "Missing docker-compose.yml in ${PROJECT_ROOT}"
  [[ -f "${PROJECT_ROOT}/docker-compose.vps.yml" ]] || die "Missing docker-compose.vps.yml in ${PROJECT_ROOT}"
  [[ -f "${ENV_EXAMPLE_FILE}" ]] || die "Missing .env.example in ${PROJECT_ROOT}"
  [[ -f "${VPS_ENV_EXAMPLE_FILE}" ]] || die "Missing .env.vps.example in ${PROJECT_ROOT}"
}

load_os_release() {
  [[ -f /etc/os-release ]] || die "Unsupported Linux distribution: /etc/os-release was not found"
  # shellcheck disable=SC1091
  . /etc/os-release

  OS_ID="${ID:-}"
  OS_MAJOR_VERSION="${VERSION_ID%%.*}"

  case "${OS_ID}" in
    ubuntu|debian)
      OS_FAMILY="debian"
      PACKAGE_MANAGER="apt-get"
      OS_CODENAME="${VERSION_CODENAME:-${UBUNTU_CODENAME:-}}"
      [[ -n "${OS_CODENAME}" ]] || die "Could not determine the distribution codename from /etc/os-release"
      NGINX_SITE_PATH="/etc/nginx/sites-available/${NGINX_SITE_NAME}"
      NGINX_SITE_LINK="/etc/nginx/sites-enabled/${NGINX_SITE_NAME}"
      NGINX_DEFAULT_SITE_LINK="/etc/nginx/sites-enabled/default"
      ;;
    almalinux|rocky|rhel|centos|ol)
      OS_FAMILY="rhel"
      if has_command dnf; then
        PACKAGE_MANAGER="dnf"
      elif has_command yum; then
        PACKAGE_MANAGER="yum"
      else
        die "Could not find dnf or yum on this RHEL-compatible host"
      fi
      NGINX_SITE_PATH="/etc/nginx/conf.d/${NGINX_SITE_NAME}.conf"
      NGINX_SITE_LINK=""
      NGINX_DEFAULT_SITE_LINK=""
      ;;
    *)
      if [[ " ${ID_LIKE:-} " == *" debian "* ]]; then
        OS_FAMILY="debian"
        PACKAGE_MANAGER="apt-get"
        OS_CODENAME="${VERSION_CODENAME:-${UBUNTU_CODENAME:-}}"
        [[ -n "${OS_CODENAME}" ]] || die "Could not determine the distribution codename from /etc/os-release"
        NGINX_SITE_PATH="/etc/nginx/sites-available/${NGINX_SITE_NAME}"
        NGINX_SITE_LINK="/etc/nginx/sites-enabled/${NGINX_SITE_NAME}"
        NGINX_DEFAULT_SITE_LINK="/etc/nginx/sites-enabled/default"
      elif [[ " ${ID_LIKE:-} " == *" rhel "* || " ${ID_LIKE:-} " == *" fedora "* ]]; then
        OS_FAMILY="rhel"
        if has_command dnf; then
          PACKAGE_MANAGER="dnf"
        elif has_command yum; then
          PACKAGE_MANAGER="yum"
        else
          die "Could not find dnf or yum on this RHEL-compatible host"
        fi
        NGINX_SITE_PATH="/etc/nginx/conf.d/${NGINX_SITE_NAME}.conf"
        NGINX_SITE_LINK=""
        NGINX_DEFAULT_SITE_LINK=""
      else
        die "This script currently supports Ubuntu/Debian and AlmaLinux/RHEL-compatible VPS hosts only"
      fi
      ;;
  esac
}

package_update() {
  case "${OS_FAMILY}" in
    debian)
      apt-get update
      ;;
    rhel)
      "${PACKAGE_MANAGER}" makecache -y >/dev/null 2>&1 || true
      ;;
  esac
}

package_install() {
  case "${OS_FAMILY}" in
    debian)
      DEBIAN_FRONTEND=noninteractive apt-get install -y "$@"
      ;;
    rhel)
      "${PACKAGE_MANAGER}" install -y "$@"
      ;;
  esac
}

try_package_install() {
  case "${OS_FAMILY}" in
    debian)
      DEBIAN_FRONTEND=noninteractive apt-get install -y "$@" >/dev/null 2>&1
      ;;
    rhel)
      "${PACKAGE_MANAGER}" install -y "$@" >/dev/null 2>&1
      ;;
  esac
}

has_compose_command() {
  if has_command docker && docker compose version >/dev/null 2>&1; then
    return 0
  fi

  has_command docker-compose
}

detect_compose_command() {
  if has_command docker && docker compose version >/dev/null 2>&1; then
    COMPOSE_COMMAND=(docker compose)
    return
  fi

  if has_command docker-compose; then
    COMPOSE_COMMAND=(docker-compose)
    return
  fi

  die "Docker Compose was not found. Install docker compose plugin or docker-compose and rerun the script."
}

install_system_packages() {
  log "Installing system packages"
  package_update
  package_install \
    ca-certificates \
    curl \
    nginx \
    openssl

  if [[ "${OS_FAMILY}" == "rhel" ]] && ! has_command setsebool; then
    try_package_install policycoreutils-python-utils || try_package_install policycoreutils-python || true
  fi
}

install_certbot() {
  if has_command certbot; then
    log "Certbot is already available"
  else
    if [[ "${OS_FAMILY}" == "debian" ]]; then
      log "Installing Certbot for Nginx"
      package_update
      package_install \
        certbot \
        python3-certbot-nginx
    else
      log "Installing Certbot for Nginx on AlmaLinux/RHEL-compatible host"
      try_package_install epel-release || true
      package_update
      package_install snapd
      systemctl enable --now snapd.socket
      ln -sfn /var/lib/snapd/snap /snap
      if ! snap list certbot >/dev/null 2>&1; then
        snap install --classic certbot
      fi
      ln -sfn /snap/bin/certbot /usr/local/bin/certbot
    fi
  fi

  systemctl enable --now certbot.timer >/dev/null 2>&1 || true
}

install_docker() {
  if has_command docker && has_compose_command; then
    log "Docker and docker compose are already available"
    return
  fi

  log "Installing Docker Engine and docker compose plugin"
  if [[ "${OS_FAMILY}" == "debian" ]]; then
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL "https://download.docker.com/linux/${OS_ID}/gpg" -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc

    printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/%s %s stable\n' \
      "$(dpkg --print-architecture)" \
      "${OS_ID}" \
      "${OS_CODENAME}" > /etc/apt/sources.list.d/docker.list

    package_update
    package_install \
      containerd.io \
      docker-buildx-plugin \
      docker-ce \
      docker-ce-cli \
      docker-compose-plugin
  else
    cat > /etc/yum.repos.d/docker-ce.repo <<'EOF'
[docker-ce-stable]
name=Docker CE Stable - $basearch
baseurl=https://download.docker.com/linux/centos/$releasever/$basearch/stable
enabled=1
gpgcheck=1
gpgkey=https://download.docker.com/linux/centos/gpg
EOF

    package_update
    package_install \
      containerd.io \
      docker-ce \
      docker-ce-cli
    try_package_install docker-buildx-plugin || true
    try_package_install docker-compose-plugin || try_package_install docker-compose || true
  fi
}

ensure_swap() {
  local swap_file="/swapfile"

  if swapon --show --noheadings | grep -q .; then
    log "Swap is already available"
    return
  fi

  log "Creating 2G swap file for Docker builds"
  if has_command fallocate; then
    fallocate -l 2G "${swap_file}" || dd if=/dev/zero of="${swap_file}" bs=1M count=2048 status=none
  else
    dd if=/dev/zero of="${swap_file}" bs=1M count=2048 status=none
  fi
  chmod 600 "${swap_file}"
  mkswap "${swap_file}"
  swapon "${swap_file}"

  if ! grep -qE "^[^#[:space:]]+[[:space:]]+none[[:space:]]+swap[[:space:]]" /etc/fstab; then
    printf '%s none swap sw 0 0\n' "${swap_file}" >> /etc/fstab
  fi
}

ensure_docker_ready() {
  log "Ensuring Docker daemon is running"
  systemctl enable --now docker
  docker info >/dev/null 2>&1 || die "Docker daemon is not available"
  detect_compose_command
}

ensure_env_file() {
  local source_env_example

  if [[ -f "${ENV_FILE}" ]]; then
    log "Using existing .env file"
  else
    source_env_example="${VPS_ENV_EXAMPLE_FILE}"
    log "Creating .env from $(basename "${source_env_example}")"
    cp "${source_env_example}" "${ENV_FILE}"
  fi

  chmod 600 "${ENV_FILE}"
}

escape_sed_replacement() {
  printf '%s' "$1" | sed -e 's/[&|\\]/\\&/g'
}

get_env_value() {
  local key="$1"
  local line
  line="$(grep -E "^${key}=" "${ENV_FILE}" | tail -n 1 || true)"
  if [[ -z "${line}" ]]; then
    return 1
  fi

  printf '%s' "${line#*=}"
}

set_env_value() {
  local key="$1"
  local value="$2"
  local escaped_value

  escaped_value="$(escape_sed_replacement "${value}")"
  if grep -qE "^${key}=" "${ENV_FILE}"; then
    sed -i "s|^${key}=.*$|${key}=${escaped_value}|" "${ENV_FILE}"
  else
    printf '%s=%s\n' "${key}" "${value}" >> "${ENV_FILE}"
  fi
}

is_placeholder_value() {
  case "$1" in
    ""|"replace-with-a-long-random-secret"|"replace-me"|"change-this-password"|"admin@example.com")
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

prompt_value() {
  local key="$1"
  local prompt_text="$2"
  local default_value="${3:-}"
  local secret="${4:-false}"
  local current_value=""
  local value=""

  if [[ -n "${!key:-}" ]]; then
    printf '%s' "${!key}"
    return
  fi

  if current_value="$(get_env_value "${key}" 2>/dev/null)"; then
    if ! is_placeholder_value "${current_value}"; then
      printf '%s' "${current_value}"
      return
    fi
  fi

  if [[ ! -t 0 ]]; then
    if [[ -n "${default_value}" ]]; then
      printf '%s' "${default_value}"
      return
    fi

    die "Missing required value for ${key}. Export ${key} before running non-interactively."
  fi

  if [[ "${secret}" == "true" ]]; then
    read -r -s -p "${prompt_text}: " value
    printf '\n'
  elif [[ -n "${default_value}" ]]; then
    read -r -p "${prompt_text} [${default_value}]: " value
    value="${value:-${default_value}}"
  else
    read -r -p "${prompt_text}: " value
  fi

  [[ -n "${value}" ]] || die "${key} cannot be empty"
  printf '%s' "${value}"
}

detect_default_base_url() {
  local public_host="${PUBLIC_HOST:-}"

  if [[ -z "${public_host}" ]]; then
    public_host="$(hostname -I 2>/dev/null | awk '{print $1}')"
  fi

  if [[ -z "${public_host}" ]]; then
    public_host="127.0.0.1"
  fi

  printf 'http://%s' "${public_host}"
}

extract_url_scheme() {
  local url="$1"

  if [[ "${url}" == *"://"* ]]; then
    printf '%s' "${url%%://*}"
    return
  fi

  printf 'http'
}

extract_url_host() {
  local url="$1"
  local without_scheme="${url#*://}"
  local host_port="${without_scheme%%/*}"

  printf '%s' "${host_port%%:*}"
}

resolve_nginx_server_name() {
  local base_url="$1"
  local host

  host="$(extract_url_host "${base_url}")"
  if [[ -z "${host}" || "${host}" == "127.0.0.1" || "${host}" == "localhost" ]]; then
    printf '_'
    return
  fi

  printf '%s' "${host}"
}

resolve_nginx_upload_limit() {
  local max_upload_mb

  max_upload_mb="$(get_env_value MAX_UPLOAD_MB 2>/dev/null || true)"
  if [[ "${max_upload_mb}" =~ ^[0-9]+$ ]] && (( max_upload_mb > 0 )); then
    printf '%sm' "${max_upload_mb}"
    return
  fi

  printf '100m'
}

is_ip_address() {
  local host="$1"

  [[ "${host}" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ || "${host}" == *:* ]]
}

write_nginx_config() {
  local server_name="$1"
  local upload_limit="$2"
  local cert_fullchain_path="$3"
  local cert_privkey_path="$4"

  if [[ -n "${cert_fullchain_path}" && -n "${cert_privkey_path}" ]]; then
    cat > "${NGINX_SITE_PATH}" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${server_name};

    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name ${server_name};

    ssl_certificate ${cert_fullchain_path};
    ssl_certificate_key ${cert_privkey_path};
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_timeout 1d;
    ssl_session_cache shared:DocTranslatorSSL:10m;

    client_max_body_size ${upload_limit};

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
        proxy_request_buffering off;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
    return
  fi

  cat > "${NGINX_SITE_PATH}" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${server_name};

    client_max_body_size ${upload_limit};

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
        proxy_request_buffering off;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
}

resolve_tls_paths() {
  local host="$1"
  local fullchain_path=""
  local privkey_path=""

  if [[ -n "${host}" && "${host}" != "_" ]]; then
    fullchain_path="/etc/letsencrypt/live/${host}/fullchain.pem"
    privkey_path="/etc/letsencrypt/live/${host}/privkey.pem"
  fi

  if [[ -f "${fullchain_path}" && -f "${privkey_path}" ]]; then
    printf '%s\n%s\n' "${fullchain_path}" "${privkey_path}"
    return
  fi

  printf '\n\n'
}

configure_nginx() {
  local base_url
  local host
  local server_name
  local upload_limit
  local tls_paths
  local cert_fullchain_path
  local cert_privkey_path

  base_url="$(get_env_value APP_BASE_URL 2>/dev/null || printf 'http://localhost')"
  host="$(extract_url_host "${base_url}")"
  server_name="$(resolve_nginx_server_name "${base_url}")"
  upload_limit="$(resolve_nginx_upload_limit)"
  tls_paths="$(resolve_tls_paths "${host}")"
  cert_fullchain_path="$(printf '%s' "${tls_paths}" | sed -n '1p')"
  cert_privkey_path="$(printf '%s' "${tls_paths}" | sed -n '2p')"

  log "Configuring Nginx reverse proxy"
  write_nginx_config "${server_name}" "${upload_limit}" "${cert_fullchain_path}" "${cert_privkey_path}"
  if [[ -n "${NGINX_SITE_LINK}" ]]; then
    ln -sfn "${NGINX_SITE_PATH}" "${NGINX_SITE_LINK}"
  fi
  if [[ -n "${NGINX_DEFAULT_SITE_LINK}" ]]; then
    rm -f "${NGINX_DEFAULT_SITE_LINK}"
  fi

  nginx -t
  systemctl enable --now nginx
  systemctl reload nginx
}

configure_host_networking() {
  if [[ "${OS_FAMILY}" != "rhel" ]]; then
    return
  fi

  if has_command getenforce && has_command setsebool && [[ "$(getenforce)" != "Disabled" ]]; then
    log "Allowing Nginx to reach local upstreams under SELinux"
    setsebool -P httpd_can_network_connect 1
  fi

  if has_command firewall-cmd && systemctl is-active --quiet firewalld 2>/dev/null; then
    log "Opening HTTP and HTTPS in firewalld"
    firewall-cmd --permanent --add-service=http >/dev/null 2>&1 || true
    firewall-cmd --permanent --add-service=https >/dev/null 2>&1 || true
    firewall-cmd --reload >/dev/null 2>&1 || true
  fi
}

ensure_tls_certificate() {
  local base_url
  local scheme
  local host
  local server_name
  local certbot_email
  local tls_paths
  local cert_fullchain_path
  local cert_privkey_path

  base_url="$(get_env_value APP_BASE_URL 2>/dev/null || printf 'http://localhost')"
  scheme="$(extract_url_scheme "${base_url}")"
  if [[ "${scheme}" != "https" ]]; then
    return
  fi

  host="$(extract_url_host "${base_url}")"
  server_name="$(resolve_nginx_server_name "${base_url}")"
  if [[ "${server_name}" == "_" ]]; then
    die "APP_BASE_URL must use a public domain name when https is enabled"
  fi

  if is_ip_address "${host}"; then
    die "Let's Encrypt cannot issue certificates for IP addresses. Use a domain name in APP_BASE_URL."
  fi

  certbot_email="$(get_env_value CERTBOT_EMAIL 2>/dev/null || true)"
  if is_placeholder_value "${certbot_email}"; then
    certbot_email="$(get_env_value ADMIN_EMAIL 2>/dev/null || true)"
  fi
  if is_placeholder_value "${certbot_email}"; then
    die "Set CERTBOT_EMAIL or ADMIN_EMAIL to a real email address before enabling https"
  fi
  [[ -n "${certbot_email}" ]] || die "CERTBOT_EMAIL or ADMIN_EMAIL must be set before enabling https"

  tls_paths="$(resolve_tls_paths "${host}")"
  cert_fullchain_path="$(printf '%s' "${tls_paths}" | sed -n '1p')"
  cert_privkey_path="$(printf '%s' "${tls_paths}" | sed -n '2p')"
  if [[ -n "${cert_fullchain_path}" && -n "${cert_privkey_path}" ]]; then
    log "TLS certificate already exists for ${host}"
    install_certbot
    return
  fi

  install_certbot

  log "Obtaining TLS certificate for ${host}"
  certbot certonly \
    --nginx \
    --non-interactive \
    --agree-tos \
    --no-eff-email \
    --keep-until-expiring \
    --email "${certbot_email}" \
    -d "${host}"

  systemctl enable --now certbot.timer >/dev/null 2>&1 || true
}

configure_env() {
  local app_secret_key
  local app_base_url
  local app_base_url_scheme
  local model_base_url
  local model_api_key
  local model_name
  local admin_email
  local admin_password
  local admin_name
  local certbot_email

  log "Preparing production environment settings"

  app_secret_key="$(get_env_value APP_SECRET_KEY 2>/dev/null || true)"
  if is_placeholder_value "${app_secret_key}"; then
    app_secret_key="$(openssl rand -hex 32)"
  fi

  app_base_url="$(prompt_value APP_BASE_URL "Public base URL" "$(detect_default_base_url)")"
  model_base_url="$(prompt_value MODEL_BASE_URL "Model API base URL" "https://api.openai.com/v1")"
  model_api_key="$(prompt_value MODEL_API_KEY "Model API key" "" true)"
  model_name="$(prompt_value MODEL_NAME "Model name" "gpt-4.1-mini")"
  admin_email="$(prompt_value ADMIN_EMAIL "Admin email" "admin@example.com")"
  admin_password="$(prompt_value ADMIN_PASSWORD "Admin password" "" true)"
  admin_name="$(prompt_value ADMIN_NAME "Admin display name" "Administrator")"
  app_base_url_scheme="$(extract_url_scheme "${app_base_url}")"

  certbot_email="$(get_env_value CERTBOT_EMAIL 2>/dev/null || true)"
  if [[ "${app_base_url_scheme}" == "https" ]] || ! is_placeholder_value "${certbot_email}"; then
    certbot_email="$(prompt_value CERTBOT_EMAIL "TLS contact email" "${admin_email}")"
  fi

  set_env_value APP_ENV production
  set_env_value APP_BASE_URL "${app_base_url}"
  set_env_value APP_SECRET_KEY "${app_secret_key}"
  set_env_value API_BIND_HOST 127.0.0.1
  set_env_value WEB_BIND_HOST 127.0.0.1
  set_env_value CERTBOT_EMAIL "${certbot_email}"
  set_env_value MODEL_BASE_URL "${model_base_url}"
  set_env_value MODEL_API_KEY "${model_api_key}"
  set_env_value MODEL_NAME "${model_name}"
  set_env_value ADMIN_EMAIL "${admin_email}"
  set_env_value ADMIN_PASSWORD "${admin_password}"
  set_env_value ADMIN_NAME "${admin_name}"
}

run_compose() {
  (
    cd "${PROJECT_ROOT}"
    COMPOSE_PARALLEL_LIMIT="${COMPOSE_PARALLEL_LIMIT}" "${COMPOSE_COMMAND[@]}" "${COMPOSE_FILES[@]}" "$@"
  )
}

compose_command_text() {
  printf '%s' "${COMPOSE_COMMAND[*]}"
}

container_status() {
  local service_name="$1"
  local container_id

  container_id="$(run_compose ps -q "${service_name}")"
  if [[ -z "${container_id}" ]]; then
    printf 'missing'
    return
  fi

  docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${container_id}"
}

wait_for_services() {
  local deadline
  local pending
  local statuses
  local service_name
  local status

  log "Waiting for service health checks"
  deadline=$((SECONDS + STARTUP_TIMEOUT_SECONDS))
  while (( SECONDS < deadline )); do
    pending=0
    statuses=()

    for service_name in "${SERVICES[@]}"; do
      status="$(container_status "${service_name}")"
      statuses+=("${service_name}=${status}")

      if [[ "${status}" != "healthy" && "${status}" != "running" ]]; then
        pending=1
      fi
    done

    if (( pending == 0 )); then
      log "All services are healthy"
      return
    fi

    printf 'Waiting for services: %s\n' "${statuses[*]}"
    sleep 5
  done

  run_compose ps
  die "Timed out waiting for services to become healthy"
}

start_stack() {
  log "Validating docker compose configuration"
  run_compose config -q

  log "Building and starting the project stack"
  run_compose up -d --build
}

show_access_info() {
  local base_url
  local admin_email
  local compose_command

  base_url="$(get_env_value APP_BASE_URL 2>/dev/null || printf 'http://localhost:3000')"
  admin_email="$(get_env_value ADMIN_EMAIL 2>/dev/null || printf 'admin@example.com')"
  compose_command="$(compose_command_text)"

  printf '\nDeployment complete.\n'
  printf 'Web UI: %s\n' "${base_url}"
  printf 'Admin email: %s\n' "${admin_email}"
  printf '\nUseful commands:\n'
  printf '  cd %s && %s %s ps\n' "${PROJECT_ROOT}" "${compose_command}" "${COMPOSE_FILES[*]}"
  printf '  cd %s && %s %s logs -f --tail 200\n' "${PROJECT_ROOT}" "${compose_command}" "${COMPOSE_FILES[*]}"
}

main() {
  require_root
  assert_project_root
  load_os_release
  install_system_packages
  install_docker
  ensure_docker_ready
  ensure_swap
  ensure_env_file
  configure_env
  start_stack
  wait_for_services
  configure_host_networking
  configure_nginx
  ensure_tls_certificate
  configure_nginx
  show_access_info
}

main "$@"
