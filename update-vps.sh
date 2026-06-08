#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.vps.yml)
SERVICES=(postgres redis api worker web)
STARTUP_TIMEOUT_SECONDS="${STARTUP_TIMEOUT_SECONDS:-600}"
BRANCH="${BRANCH:-}"
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
  [[ "${EUID}" -eq 0 ]] || die "Please run this script as root, for example: sudo bash ./update-vps.sh"
}

assert_project_root() {
  [[ -d "${PROJECT_ROOT}/.git" ]] || die "Missing git repository in ${PROJECT_ROOT}"
  [[ -f "${PROJECT_ROOT}/docker-compose.yml" ]] || die "Missing docker-compose.yml in ${PROJECT_ROOT}"
  [[ -f "${PROJECT_ROOT}/docker-compose.vps.yml" ]] || die "Missing docker-compose.vps.yml in ${PROJECT_ROOT}"
  [[ -f "${PROJECT_ROOT}/.env" ]] || die "Missing .env in ${PROJECT_ROOT}. Run deploy-vps.sh first."
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

resolve_branch() {
  if [[ -n "${BRANCH}" ]]; then
    printf '%s' "${BRANCH}"
    return
  fi

  git -C "${PROJECT_ROOT}" symbolic-ref --quiet --short HEAD \
    || die "Could not determine the current git branch. Export BRANCH and rerun the script."
}

assert_clean_worktree() {
  if [[ -n "$(git -C "${PROJECT_ROOT}" status --short)" ]]; then
    die "Working tree is not clean in ${PROJECT_ROOT}. Commit or stash local changes before updating."
  fi
}

update_repo() {
  local branch="$1"

  log "Fetching the latest code from origin/${branch}"
  git -C "${PROJECT_ROOT}" fetch origin "${branch}" --depth 1

  log "Checking out ${branch}"
  git -C "${PROJECT_ROOT}" checkout "${branch}"

  log "Applying the latest commit"
  git -C "${PROJECT_ROOT}" pull --ff-only origin "${branch}"
}

run_compose() {
  (
    cd "${PROJECT_ROOT}"
    "${COMPOSE_COMMAND[@]}" "${COMPOSE_FILES[@]}" "$@"
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

update_stack() {
  log "Validating docker compose configuration"
  run_compose config -q

  log "Rebuilding and restarting the stack with the updated code"
  run_compose up -d --build
}

show_summary() {
  local branch="$1"

  printf '\nUpdate complete.\n'
  printf 'Branch: %s\n' "${branch}"
  printf 'Project root: %s\n' "${PROJECT_ROOT}"
  printf '\nUseful commands:\n'
  printf '  cd %s && %s %s ps\n' "${PROJECT_ROOT}" "${COMPOSE_COMMAND[*]}" "${COMPOSE_FILES[*]}"
  printf '  cd %s && %s %s logs -f --tail 200\n' "${PROJECT_ROOT}" "${COMPOSE_COMMAND[*]}" "${COMPOSE_FILES[*]}"
}

main() {
  local branch

  require_root
  assert_project_root
  detect_compose_command
  assert_clean_worktree
  branch="$(resolve_branch)"
  update_repo "${branch}"
  update_stack
  wait_for_services
  show_summary "${branch}"
}

main "$@"
