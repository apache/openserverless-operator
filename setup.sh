#!/bin/bash
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
#
# Install the prerequisites required to run the operator tests.
#
# Supported platforms: macOS (Homebrew) and Ubuntu Linux / WSL2 with Ubuntu (apt).
#
# Usage:
#   ./setup.sh          install what is missing
#   ./setup.sh --check  only report what is missing, install nothing
#
set -euo pipefail

# versions - keep aligned with the Dockerfile and .github/workflows
KUSTOMIZE_VERSION="v4.5.7"   # Dockerfile
KIND_VERSION="v0.22.0"       # .github/workflows/check.yml
KUBECTL_VERSION="v1.23.0"    # Dockerfile
POETRY_VERSION="2.3.2"       # Dockerfile ARG POETRY_VERSION
PYTHON_VERSION="3.12"        # Dockerfile / pyproject.toml
TASK_VERSION="3.0.0"         # minimum - Taskfile.yml uses schema version 3

CHECK_ONLY="false"
if [ "${1:-}" = "--check" ]; then CHECK_ONLY="true"; fi

MISSING=0
INSTALLED=0

say()  { echo "==> $*"; }
ok()   { echo "  OK      $*"; }
miss() { echo "  MISSING $*"; }

#-----------------------------------------------------------------------------
# platform detection
#-----------------------------------------------------------------------------
detect_platform() {
  case "$(uname -s)" in
    Darwin) echo "mac" ;;
    Linux)
      if [ -f /etc/os-release ] && grep -qi '^ID=ubuntu' /etc/os-release; then
        echo "ubuntu"
      else
        echo "unsupported-linux"
      fi
      ;;
    *) echo "unsupported" ;;
  esac
}

PLATFORM="$(detect_platform)"

case "$PLATFORM" in
  mac)
    say "Detected macOS"
    if ! command -v brew >/dev/null 2>&1; then
      echo
      echo "ERROR: Homebrew is required on macOS but was not found."
      echo "Install it from https://brew.sh then run this script again:"
      echo '  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
      exit 1
    fi
    ;;
  ubuntu)
    say "Detected Ubuntu Linux"
    ;;
  unsupported-linux)
    echo
    echo "ERROR: this Linux distribution is not supported."
    echo "The tests are supported on Ubuntu. Please use Ubuntu, or a container/VM running Ubuntu."
    exit 1
    ;;
  *)
    echo
    echo "ERROR: unsupported operating system: $(uname -s)"
    echo
    echo "Running the tests requires one of:"
    echo "  - macOS         (with Homebrew)"
    echo "  - Ubuntu Linux  (with apt)"
    echo "  - Windows       via WSL2 with an Ubuntu distribution"
    echo
    echo "On Windows, install WSL2 with Ubuntu and run this script inside it:"
    echo "  wsl --install -d Ubuntu"
    exit 1
    ;;
esac

# WSL is Ubuntu underneath - just let the user know where they are
if [ "$PLATFORM" = "ubuntu" ] && grep -qi microsoft /proc/version 2>/dev/null; then
  say "Running under WSL - make sure Docker Desktop has WSL integration enabled"
fi

ARCH_RAW="$(uname -m)"
case "$ARCH_RAW" in
  x86_64|amd64) ARCH="amd64" ;;
  arm64|aarch64) ARCH="arm64" ;;
  *) echo "ERROR: unsupported architecture: $ARCH_RAW"; exit 1 ;;
esac

if [ "$PLATFORM" = "mac" ]; then OS="darwin"; else OS="linux"; fi

mkdir -p "$HOME/.local/bin"

#-----------------------------------------------------------------------------
# helpers
#-----------------------------------------------------------------------------
# need <command> <description> ; returns 0 if it must be installed
need() {
  if command -v "$1" >/dev/null 2>&1; then
    ok "$2 ($(command -v "$1"))"
    return 1
  fi
  miss "$2"
  MISSING=$((MISSING + 1))
  [ "$CHECK_ONLY" = "true" ] && return 1
  return 0
}

# like need, but stays quiet when present so the caller can report the version
need_quiet() {
  command -v "$1" >/dev/null 2>&1 && return 1
  miss "$2"
  MISSING=$((MISSING + 1))
  [ "$CHECK_ONLY" = "true" ] && return 1
  return 0
}

installed() { INSTALLED=$((INSTALLED + 1)); echo "  ...installed $1"; }

WARNINGS=0
warn() { WARNINGS=$((WARNINGS + 1)); echo "  WARN    $*"; }

# strip a leading v and keep only the leading numeric dotted version
normver() { echo "$1" | sed 's/^v//' | grep -oE '^[0-9]+(\.[0-9]+)*' || echo "0"; }

# vercmp A B -> prints "lt", "eq" or "gt" for A relative to B
vercmp() {
  local a b first
  a="$(normver "$1")"; b="$(normver "$2")"
  [ "$a" = "$b" ] && { echo "eq"; return; }
  first="$(printf '%s\n%s\n' "$a" "$b" | sort -V | head -1)"
  if [ "$first" = "$a" ]; then echo "lt"; else echo "gt"; fi
}

# check_version <name> <found-version> <expected-version> [min]
# accepts a newer version but warns; refuses an older one.
# pass "min" as the 4th argument when the expected version is only a minimum,
# in which case anything newer is fine and no warning is emitted.
check_version() {
  local name="$1" found="$2" want="$3" kind="${4:-pinned}"
  if [ -z "$found" ]; then
    warn "$name: could not determine the version (expected $want)"
    return
  fi
  case "$(vercmp "$found" "$want")" in
    eq) ok "$name $found" ;;
    gt) ok "$name $found"
        if [ "$kind" != "min" ]; then
          warn "$name $found is newer than the expected $want - it should work, but the CI and the Dockerfile use $want"
        fi ;;
    lt) if [ "$kind" = "min" ]
        then warn "$name $found is older than the minimum required $want - please upgrade it"
        else warn "$name $found is OLDER than the required $want - please upgrade it"
        fi
        MISSING=$((MISSING + 1)) ;;
  esac
}

apt_install() {
  sudo apt-get update -qq
  sudo apt-get install -y -qq "$@"
}

#-----------------------------------------------------------------------------
say "Checking prerequisites"
#-----------------------------------------------------------------------------

# --- base tools -------------------------------------------------------------
if need curl "curl"; then
  if [ "$PLATFORM" = "mac" ]; then brew install curl; else apt_install curl; fi
  installed curl
fi

if need git "git"; then
  if [ "$PLATFORM" = "mac" ]; then brew install git; else apt_install git; fi
  installed git
fi

# --- task (the build tool: every other step below is run through it) ---------
if need_quiet task "task"; then
  if [ "$PLATFORM" = "mac" ]; then
    brew install go-task/tap/go-task
  else
    curl -sL https://taskfile.dev/install.sh | sh -s -- -d -b "$HOME/.local/bin"
  fi
  installed task
  hash -r 2>/dev/null || true
  if ! command -v task >/dev/null 2>&1; then
    warn "task was installed in $HOME/.local/bin but is not on your PATH yet"
  fi
else
  check_version "task" "$(task --version 2>/dev/null | grep -oE 'v?[0-9]+(\.[0-9]+)+' | head -1)" "$TASK_VERSION" min
fi

# --- docker (not installed automatically: it needs a desktop app / daemon) ---
if command -v docker >/dev/null 2>&1; then
  ok "docker ($(command -v docker))"
else
  miss "docker"
  MISSING=$((MISSING + 1))
  if [ "$PLATFORM" = "mac" ]; then
    echo "          install Docker Desktop: https://docs.docker.com/desktop/install/mac-install/"
  else
    echo "          install with: curl -fsSL https://get.docker.com | sh"
    echo "          then: sudo usermod -aG docker \$USER   (log out and back in)"
  fi
fi

# --- python 3.12 ------------------------------------------------------------
if command -v python3 >/dev/null 2>&1 || command -v "python$PYTHON_VERSION" >/dev/null 2>&1; then
  PY_BIN="$(command -v "python$PYTHON_VERSION" || command -v python3)"
  check_version "python" "$("$PY_BIN" -c 'import sys; print("%d.%d"%sys.version_info[:2])')" "$PYTHON_VERSION"
else
  miss "python$PYTHON_VERSION"
  MISSING=$((MISSING + 1))
  if [ "$CHECK_ONLY" = "false" ]; then
    if [ "$PLATFORM" = "mac" ]; then
      brew install "python@$PYTHON_VERSION"
    else
      apt_install software-properties-common
      sudo add-apt-repository -y ppa:deadsnakes/ppa
      apt_install "python$PYTHON_VERSION" "python$PYTHON_VERSION-venv" "python$PYTHON_VERSION-dev"
    fi
    installed "python$PYTHON_VERSION"
  fi
fi

# --- poetry (the python package manager used by this project) ---------------
if need_quiet poetry "poetry"; then
  if [ "$PLATFORM" = "mac" ]; then
    brew install poetry
  else
    curl -sSL https://install.python-poetry.org | "python$PYTHON_VERSION" -
    echo "          note: ensure \$HOME/.local/bin is in your PATH"
  fi
  installed poetry
else
  command -v poetry >/dev/null 2>&1 && \
    check_version "poetry" "$(poetry --version 2>/dev/null | grep -oE '[0-9]+(\.[0-9]+)+' | head -1)" "$POETRY_VERSION"
fi

# --- kubectl ----------------------------------------------------------------
if need_quiet kubectl "kubectl"; then
  if [ "$PLATFORM" = "mac" ]; then
    brew install kubectl
  else
    curl -sL "https://dl.k8s.io/release/$KUBECTL_VERSION/bin/$OS/$ARCH/kubectl" \
      -o "$HOME/.local/bin/kubectl"
    chmod +x "$HOME/.local/bin/kubectl"
  fi
  installed kubectl
else
  check_version "kubectl" "$(kubectl version --client 2>/dev/null | grep -oE 'v?[0-9]+(\.[0-9]+)+' | head -1)" "$KUBECTL_VERSION"
fi

# --- kustomize --------------------------------------------------------------
if need_quiet kustomize "kustomize"; then
  if [ "$PLATFORM" = "mac" ]; then
    brew install kustomize
  else
    URL="https://github.com/kubernetes-sigs/kustomize/releases/download/kustomize%2F$KUSTOMIZE_VERSION/kustomize_${KUSTOMIZE_VERSION}_${OS}_${ARCH}.tar.gz"
    curl -sL "$URL" | tar xzf - -C "$HOME/.local/bin"
    chmod +x "$HOME/.local/bin/kustomize"
  fi
  installed kustomize
else
  check_version "kustomize" "$(kustomize version 2>/dev/null | grep -oE 'v?[0-9]+(\.[0-9]+)+' | head -1)" "$KUSTOMIZE_VERSION"
fi

# --- kind -------------------------------------------------------------------
if need_quiet kind "kind"; then
  if [ "$PLATFORM" = "mac" ]; then
    brew install kind
  else
    curl -sLo "$HOME/.local/bin/kind" \
      "https://kind.sigs.k8s.io/dl/$KIND_VERSION/kind-${OS}-${ARCH}"
    chmod +x "$HOME/.local/bin/kind"
  fi
  installed kind
else
  check_version "kind" "$(kind version 2>/dev/null | grep -oE 'v?[0-9]+(\.[0-9]+)+' | head -1)" "$KIND_VERSION"
fi

#-----------------------------------------------------------------------------
# summary
#-----------------------------------------------------------------------------
echo
if [ "$CHECK_ONLY" = "true" ]; then
  if [ "$MISSING" -eq 0 ]; then
    if [ "$WARNINGS" -gt 0 ]
    then say "All prerequisites are installed ($WARNINGS version warning(s))."
    else say "All prerequisites are installed."
    fi
  else
    say "$MISSING prerequisite(s) missing - run ./setup.sh to install them."
    exit 1
  fi
  exit 0
fi

case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) echo "NOTE: add \$HOME/.local/bin to your PATH:"
     echo "      echo 'export PATH=\$HOME/.local/bin:\$PATH' >> ~/.bashrc" ;;
esac

if [ "$WARNINGS" -gt 0 ]; then
  say "Setup complete ($INSTALLED installed, $WARNINGS warning(s))."
else
  say "Setup complete ($INSTALLED installed)."
fi
echo
echo "Next steps:"
echo "  task setup     install the python dependencies"
echo "  task utest     run the unit tests"
