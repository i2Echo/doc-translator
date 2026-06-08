#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${PROJECT_ROOT}/.env"
ENV_EXAMPLE_FILE="${PROJECT_ROOT}/.env.example"
VPS_ENV_EXAMPLE_FILE="${PROJECT_ROOT}/.env.vps.example"
STARTUP_TIMEOUT_SECONDS="${STARTUP_TIMEOUT_SECONDS:-600}"
COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.vps.yml)
SERVICES=(postgres redis api worker web)
NGINX_SITE_NAME="doc-translator"
NGINX_SITE_PATH="/etc/nginx/sites-available/${NGINX_SITE_NAME}"
NGINX_SITE_LINK="/etc/nginx/sites-enabled/${NGINX_SITE_NAME}"
NGINX_DEFAULT_SITE_LINK="/etc/nginx/sites-enabled/default"

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

  case "${ID:-}" in
    ubuntu|debian)
      ;;
    *)
      die "This script currently supports Ubuntu and Debian VPS hosts only"
      ;;
  esac

  OS_ID="${ID}"
  OS_CODENAME="${VERSION_CODENAME:-${UBUNTU_CODENAME:-}}"
  [[ -n "${OS_CODENAME}" ]] || die "Could not determine the distribution codename from /etc/os-release"
}

install_system_packages() {
  log "Installing system packages"
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y \
    ca-certificates \
    curl \
    nginx \
    openssl
}

install_docker() {
  if has_command docker && docker compose version >/dev/null 2>&1; then
    log "Docker and docker compose are already available"
    return
  fi

  log "Installing Docker Engine and docker compose plugin"
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL "https://download.docker.com/linux/${OS_ID}/gpg" -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc

  printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/%s %s stable\n' \
    "$(dpkg --print-architecture)" \
    "${OS_ID}" \
    "${OS_CODENAME}" > /etc/apt/sources.list.d/docker.list

  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y \
    containerd.io \
    docker-buildx-plugin \
    docker-ce \
    docker-ce-cli \
    docker-compose-plugin
}

ensure_docker_ready() {
  log "Ensuring Docker daemon is running"
  systemctl enable --now docker
  docker info >/dev/null 2>&1 || die "Docker daemon is not available"
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

write_nginx_config() {
  local server_name="$1"
  local upload_limit="$2"
  local proxy_scheme="$3"
  local cert_fullchain_path="$4"
  local cert_privkey_path="$5"

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
        proxy_set_header X-Forwarded-Proto ${proxy_scheme};
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
        proxy_set_header X-Forwarded-Proto ${proxy_scheme};
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
  local scheme
  local host
  local server_name
  local upload_limit
  local tls_paths
  local cert_fullchain_path
  local cert_privkey_path

  base_url="$(get_env_value APP_BASE_URL 2>/dev/null || printf 'http://localhost')"
  scheme="$(extract_url_scheme "${base_url}")"
  host="$(extract_url_host "${base_url}")"
  server_name="$(resolve_nginx_server_name "${base_url}")"
  upload_limit="$(resolve_nginx_upload_limit)"
  tls_paths="$(resolve_tls_paths "${host}")"
  cert_fullchain_path="$(printf '%s' "${tls_paths}" | sed -n '1p')"
  cert_privkey_path="$(printf '%s' "${tls_paths}" | sed -n '2p')"

  log "Configuring Nginx reverse proxy"
  write_nginx_config "${server_name}" "${upload_limit}" "${scheme}" "${cert_fullchain_path}" "${cert_privkey_path}"
  ln -sfn "${NGINX_SITE_PATH}" "${NGINX_SITE_LINK}"
  rm -f "${NGINX_DEFAULT_SITE_LINK}"

  nginx -t
  systemctl enable --now nginx
  systemctl reload nginx

  if [[ "${scheme}" == "https" && ( -z "${cert_fullchain_path}" || -z "${cert_privkey_path}" ) ]]; then
    log "APP_BASE_URL uses https, but TLS certificate files were not found. Run Certbot, then rerun deploy-vps.sh."
  fi
}

configure_env() {
  local app_secret_key
  local app_base_url
  local model_base_url
  local model_api_key
  local model_name
  local admin_email
  local admin_password
  local admin_name

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

  set_env_value APP_ENV production
  set_env_value APP_BASE_URL "${app_base_url}"
  set_env_value APP_SECRET_KEY "${app_secret_key}"
  set_env_value API_BIND_HOST 127.0.0.1
  set_env_value WEB_BIND_HOST 127.0.0.1
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
    docker compose "${COMPOSE_FILES[@]}" "$@"
  )
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

  base_url="$(get_env_value APP_BASE_URL 2>/dev/null || printf 'http://localhost:3000')"
  admin_email="$(get_env_value ADMIN_EMAIL 2>/dev/null || printf 'admin@example.com')"

  printf '\nDeployment complete.\n'
  printf 'Web UI: %s\n' "${base_url}"
  printf 'Admin email: %s\n' "${admin_email}"
  printf '\nUseful commands:\n'
  printf '  cd %s && docker compose %s ps\n' "${PROJECT_ROOT}" "${COMPOSE_FILES[*]}"
  printf '  cd %s && docker compose %s logs -f --tail 200\n' "${PROJECT_ROOT}" "${COMPOSE_FILES[*]}"
}

main() {
  require_root
  assert_project_root
  load_os_release
  install_system_packages
  install_docker
  ensure_docker_ready
  ensure_env_file
  configure_env
  start_stack
  wait_for_services
  configure_nginx
  show_access_info
}

main "$@"
