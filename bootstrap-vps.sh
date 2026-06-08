#!/usr/bin/env bash

set -Eeuo pipefail

REPO_URL="${REPO_URL:-https://github.com/i2Echo/doc-translator.git}"
BRANCH="${BRANCH:-main}"
INSTALL_DIR="${INSTALL_DIR:-/opt/doc-translator}"
OS_FAMILY=""
PACKAGE_MANAGER=""

log() {
  printf '==> %s\n' "$*"
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

require_root() {
  [[ "${EUID}" -eq 0 ]] || die "Please run this script as root, for example: sudo bash ./bootstrap-vps.sh"
}

require_repo_url() {
  [[ -n "${REPO_URL}" ]] || die "REPO_URL is required"
}

assert_supported_os() {
  [[ -f /etc/os-release ]] || die "Unsupported Linux distribution: /etc/os-release was not found"
  # shellcheck disable=SC1091
  . /etc/os-release

  case "${ID:-}" in
    ubuntu|debian)
      OS_FAMILY="debian"
      PACKAGE_MANAGER="apt-get"
      ;;
    almalinux|rocky|rhel|centos|ol)
      OS_FAMILY="rhel"
      if command -v dnf >/dev/null 2>&1; then
        PACKAGE_MANAGER="dnf"
      elif command -v yum >/dev/null 2>&1; then
        PACKAGE_MANAGER="yum"
      else
        die "Could not find dnf or yum on this RHEL-compatible host"
      fi
      ;;
    *)
      if [[ " ${ID_LIKE:-} " == *" debian "* ]]; then
        OS_FAMILY="debian"
        PACKAGE_MANAGER="apt-get"
      elif [[ " ${ID_LIKE:-} " == *" rhel "* || " ${ID_LIKE:-} " == *" fedora "* ]]; then
        OS_FAMILY="rhel"
        if command -v dnf >/dev/null 2>&1; then
          PACKAGE_MANAGER="dnf"
        elif command -v yum >/dev/null 2>&1; then
          PACKAGE_MANAGER="yum"
        else
          die "Could not find dnf or yum on this RHEL-compatible host"
        fi
      else
        die "This script currently supports Ubuntu/Debian and AlmaLinux/RHEL-compatible hosts only"
      fi
      ;;
  esac
}

ensure_prerequisites() {
  log "Installing bootstrap prerequisites"
  if [[ "${OS_FAMILY}" == "debian" ]]; then
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y \
      ca-certificates \
      git
    return
  fi

  "${PACKAGE_MANAGER}" makecache -y >/dev/null 2>&1 || true
  "${PACKAGE_MANAGER}" install -y \
    ca-certificates \
    git
}

prepare_install_dir() {
  mkdir -p "$(dirname "${INSTALL_DIR}")"
}

checkout_repo() {
  if [[ -d "${INSTALL_DIR}/.git" ]]; then
    log "Updating existing repository in ${INSTALL_DIR}"
    git -C "${INSTALL_DIR}" fetch origin "${BRANCH}" --depth 1
    git -C "${INSTALL_DIR}" checkout "${BRANCH}"
    git -C "${INSTALL_DIR}" pull --ff-only origin "${BRANCH}"
    return
  fi

  if [[ -e "${INSTALL_DIR}" ]]; then
    die "${INSTALL_DIR} already exists but is not a git repository"
  fi

  log "Cloning repository into ${INSTALL_DIR}"
  git clone --branch "${BRANCH}" --depth 1 "${REPO_URL}" "${INSTALL_DIR}"
}

run_deploy() {
  local deploy_script="${INSTALL_DIR}/deploy-vps.sh"
  [[ -f "${deploy_script}" ]] || die "Missing deploy-vps.sh in ${INSTALL_DIR}"

  log "Running project deployment script"
  exec bash "${deploy_script}"
}

main() {
  require_root
  require_repo_url
  assert_supported_os
  ensure_prerequisites
  prepare_install_dir
  checkout_repo
  run_deploy
}

main "$@"
