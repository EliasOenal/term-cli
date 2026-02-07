#!/bin/sh
# install.sh — Installer for term-cli and term-assist
# BSD License — see LICENSE
#
# Usage:
#   ./install.sh                  Install to ~/.local/bin (user-local)
#   ./install.sh --system         Install to /usr/local/bin (system-wide, sudo)
#   ./install.sh --prefix DIR     Install to custom directory
#   ./install.sh --uninstall      Remove installed files
#
# Remote install:
#   curl -fsSL https://raw.githubusercontent.com/EliasOenal/term-cli/main/install.sh | bash
#   curl -fsSL https://raw.githubusercontent.com/EliasOenal/term-cli/main/install.sh | bash -s -- --system

set -e

# ── Constants ──────────────────────────────────────────────────────────

REPO_RAW_URL="https://raw.githubusercontent.com/EliasOenal/term-cli/main"
CURL_URL="$REPO_RAW_URL/install.sh"

BINS="term-cli term-assist"
SKILL_SRC="skills/term-cli/SKILL.md"

# Agent skill directories (relative to $HOME)
SKILL_DIRS="
.config/opencode/skills/term-cli
.claude/skills/term-cli
.copilot/skills/term-cli
.gemini/skills/term-cli
.agents/skills/term-cli
.openclaw/skills/term-cli
"

SKILL_NAMES="opencode claude copilot gemini codex openclaw"

# ── Globals ────────────────────────────────────────────────────────────

PREFIX=""
SYSTEM_INSTALL=0
NO_SKILL=0
SKILL_FILTER=""
UNINSTALL=0
SOURCE_MODE=""   # "local" or "download"
TMPDIR_CLEANUP=""

# ── Helpers ────────────────────────────────────────────────────────────

info()  { printf "  %s\n" "$*"; }
warn()  { printf "  WARNING: %s\n" "$*" >&2; }
err()   { printf "ERROR: %s\n" "$*" >&2; exit 1; }
bold()  { printf "\033[1m%s\033[0m\n" "$*"; }

cleanup() {
    if [ -n "$TMPDIR_CLEANUP" ] && [ -d "$TMPDIR_CLEANUP" ]; then
        rm -rf "$TMPDIR_CLEANUP"
    fi
}
trap cleanup EXIT

# Run a command with sudo if --system, otherwise directly
maybe_sudo() {
    if [ "$SYSTEM_INSTALL" = "1" ]; then
        sudo "$@"
    else
        "$@"
    fi
}

# Download a file from GitHub to a local path
download_file() {
    url="$1"
    dest="$2"
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$url" -o "$dest"
    elif command -v wget >/dev/null 2>&1; then
        wget -qO "$dest" "$url"
    else
        err "Neither curl nor wget found. Cannot download files."
    fi
}

# Map agent short name to skill dir (relative to $HOME)
skill_dir_for_agent() {
    case "$1" in
        opencode) echo ".config/opencode/skills/term-cli" ;;
        claude)   echo ".claude/skills/term-cli" ;;
        copilot)  echo ".copilot/skills/term-cli" ;;
        gemini)   echo ".gemini/skills/term-cli" ;;
        codex)    echo ".agents/skills/term-cli" ;;
        openclaw) echo ".openclaw/skills/term-cli" ;;
        *)        return 1 ;;
    esac
}

# Get the list of skill dirs to install to (filtered or all)
get_skill_dirs() {
    if [ -n "$SKILL_FILTER" ]; then
        old_ifs="$IFS"
        IFS=","
        for agent in $SKILL_FILTER; do
            dir=$(skill_dir_for_agent "$agent") || {
                warn "Unknown agent: $agent (known: $SKILL_NAMES)"
                continue
            }
            echo "$dir"
        done
        IFS="$old_ifs"
    else
        echo "$SKILL_DIRS"
    fi
}

# Print context-aware command hint
hint_cmd() {
    flag="$1"
    if [ "$SOURCE_MODE" = "local" ]; then
        echo "  ./install.sh $flag"
    else
        echo "  curl -fsSL $CURL_URL | bash -s -- $flag"
    fi
}

# ── Argument Parsing ──────────────────────────────────────────────────

usage() {
    cat <<'USAGE'
Usage: install.sh [OPTIONS]

Install term-cli and term-assist.

Options:
  --system          Install binaries to /usr/local/bin (requires sudo)
  --prefix DIR      Override binary install directory
  --no-skill        Skip skill file installation
  --skill NAMES     Install skills only for listed agents (comma-separated)
                    Known agents: opencode, claude, copilot, gemini, codex, openclaw
  --uninstall       Remove installed files
  -h, --help        Show this help message
USAGE
    exit 0
}

while [ $# -gt 0 ]; do
    case "$1" in
        --system)    SYSTEM_INSTALL=1; shift ;;
        --prefix)    [ -n "${2:-}" ] || err "--prefix requires a directory argument"
                     PREFIX="$2"; shift 2 ;;
        --no-skill)  NO_SKILL=1; shift ;;
        --skill)     [ -n "${2:-}" ] || err "--skill requires a comma-separated list"
                     SKILL_FILTER="$2"; shift 2 ;;
        --uninstall) UNINSTALL=1; shift ;;
        -h|--help)   usage ;;
        *)           err "Unknown option: $1 (use --help for usage)" ;;
    esac
done

# ── Determine Bin Directory ───────────────────────────────────────────

if [ "$SYSTEM_INSTALL" = "1" ] && [ -n "$PREFIX" ]; then
    err "--system and --prefix cannot be used together"
fi

if [ -n "$PREFIX" ]; then
    BIN_DIR="$PREFIX"
elif [ "$SYSTEM_INSTALL" = "1" ]; then
    BIN_DIR="/usr/local/bin"
else
    BIN_DIR="$HOME/.local/bin"
fi

# ── Determine Source Mode ─────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd)" || SCRIPT_DIR=""

if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/term-cli" ] && [ -f "$SCRIPT_DIR/term-assist" ]; then
    SOURCE_MODE="local"
    SRC_DIR="$SCRIPT_DIR"
else
    SOURCE_MODE="download"
    SRC_DIR=$(mktemp -d)
    TMPDIR_CLEANUP="$SRC_DIR"
    mkdir -p "$SRC_DIR/skills/term-cli"
fi

# ── Prerequisites ─────────────────────────────────────────────────────

check_prereqs() {
    bold "Checking prerequisites..."

    # Python 3
    if command -v python3 >/dev/null 2>&1; then
        py_version=$(python3 -c 'import sys; print("{}.{}.{}".format(*sys.version_info[:3]))')
        py_major=$(echo "$py_version" | cut -d. -f1)
        py_minor=$(echo "$py_version" | cut -d. -f2)
        if [ "$py_major" -ge 3 ] && [ "$py_minor" -ge 8 ]; then
            info "python3 found ($py_version)"
        else
            err "Python 3.8+ required, found $py_version"
        fi
    else
        err "python3 not found. Please install Python 3.8+ first."
    fi

    # tmux
    if command -v tmux >/dev/null 2>&1; then
        tmux_version=$(tmux -V | sed 's/[^0-9.]//g')
        info "tmux found ($tmux_version)"
    else
        warn "tmux not found. Install it before using term-cli:"
        info "  brew install tmux        # macOS"
        info "  apt install tmux         # Debian/Ubuntu"
        info "  dnf install tmux         # Fedora/RHEL"
        info "  pacman -S tmux           # Arch"
    fi

    echo ""
}

# ── Download ──────────────────────────────────────────────────────────

download_sources() {
    bold "Downloading from GitHub..."

    download_file "$REPO_RAW_URL/term-cli" "$SRC_DIR/term-cli"
    info "Downloaded term-cli"

    download_file "$REPO_RAW_URL/term-assist" "$SRC_DIR/term-assist"
    info "Downloaded term-assist"

    if [ "$NO_SKILL" != "1" ]; then
        download_file "$REPO_RAW_URL/$SKILL_SRC" "$SRC_DIR/$SKILL_SRC"
        info "Downloaded SKILL.md"
    fi

    echo ""
}

# ── Install ───────────────────────────────────────────────────────────

install_binaries() {
    bold "Installing binaries to $BIN_DIR/..."

    maybe_sudo mkdir -p "$BIN_DIR"

    for bin in $BINS; do
        src="$SRC_DIR/$bin"
        dest="$BIN_DIR/$bin"
        if [ -f "$dest" ]; then
            info "Replacing $dest"
        else
            info "Installing $dest"
        fi
        # Copy via temp file to handle case where src and dest are the same inode
        tmp="$BIN_DIR/.$bin.tmp.$$"
        maybe_sudo cp "$src" "$tmp"
        maybe_sudo mv "$tmp" "$dest"
        maybe_sudo chmod 755 "$dest"
    done

    echo ""
}

install_skills() {
    if [ "$NO_SKILL" = "1" ]; then
        return
    fi

    bold "Installing skill files..."

    skill_src="$SRC_DIR/$SKILL_SRC"
    if [ ! -f "$skill_src" ]; then
        warn "Skill file not found at $skill_src, skipping"
        echo ""
        return
    fi

    get_skill_dirs | while read -r dir; do
        # Skip empty lines
        [ -z "$dir" ] && continue
        dest="$HOME/$dir/SKILL.md"
        mkdir -p "$HOME/$dir"
        if [ -f "$dest" ]; then
            info "Replacing $dest"
        else
            info "Installing $dest"
        fi
        # Copy via temp file to handle case where src and dest are the same inode
        tmp="$HOME/$dir/.SKILL.md.tmp.$$"
        cp "$skill_src" "$tmp"
        mv "$tmp" "$dest"
        chmod 644 "$dest"
    done

    echo ""
}

# ── Uninstall ─────────────────────────────────────────────────────────

do_uninstall() {
    bold "Uninstalling term-cli..."
    echo ""

    # Remove binaries
    bold "Removing binaries from $BIN_DIR/..."
    for bin in $BINS; do
        dest="$BIN_DIR/$bin"
        if [ -f "$dest" ]; then
            info "Removing $dest"
            maybe_sudo rm "$dest"
        else
            info "Not found, skipping: $dest"
        fi
    done
    echo ""

    # Remove skill files
    if [ "$NO_SKILL" != "1" ]; then
        bold "Removing skill files..."
        get_skill_dirs | while read -r dir; do
            [ -z "$dir" ] && continue
            dest="$HOME/$dir/SKILL.md"
            if [ -f "$dest" ]; then
                info "Removing $dest"
                rm "$dest"
            else
                info "Not found, skipping: $dest"
            fi
        done
        echo ""
    fi

    bold "Done! term-cli has been uninstalled."
}

# ── Post-Install Hints ────────────────────────────────────────────────

print_path_hint() {
    # Resolve BIN_DIR for comparison (handles ~/.local/bin vs $HOME/.local/bin)
    resolved_bin_dir="$BIN_DIR"
    case "$resolved_bin_dir" in
        "$HOME"*) ;; # already absolute
        "~"*)  resolved_bin_dir="$HOME${resolved_bin_dir#\~}" ;;
    esac

    case ":$PATH:" in
        *":$resolved_bin_dir:"*) return ;;
    esac

    bold "NOTE: $BIN_DIR is not in your PATH."
    echo ""

    # Show shell config instructions for ~/.local/bin
    case "$resolved_bin_dir" in
        "$HOME/.local/bin")
            info "Add it to your shell configuration:"
            echo ""
            info "  # For bash (add to ~/.bashrc):"
            info "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc"
            echo ""
            info "  # For zsh (add to ~/.zshrc):"
            info "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc"
            echo ""
            info "Then restart your shell or run: source ~/.bashrc (or ~/.zshrc)"
            ;;
        *)
            info "Add it to your PATH:"
            info "  export PATH=\"$BIN_DIR:\$PATH\""
            ;;
    esac
    echo ""
}

print_summary() {
    bold "Done! Installed term-cli and term-assist to $BIN_DIR/"
    echo ""

    print_path_hint

    if [ "$SYSTEM_INSTALL" != "1" ] && [ -z "$PREFIX" ]; then
        info "To install system-wide instead:"
        hint_cmd "--system"
        echo ""
    fi

    info "To uninstall:"
    if [ "$SYSTEM_INSTALL" = "1" ]; then
        hint_cmd "--uninstall --system"
    elif [ -n "$PREFIX" ]; then
        hint_cmd "--uninstall --prefix $BIN_DIR"
    else
        hint_cmd "--uninstall"
    fi
    echo ""
}

# ── Main ──────────────────────────────────────────────────────────────

main() {
    echo ""
    bold "term-cli installer"
    echo ""

    if [ "$UNINSTALL" = "1" ]; then
        do_uninstall
        return
    fi

    check_prereqs

    if [ "$SOURCE_MODE" = "download" ]; then
        download_sources
    fi

    install_binaries
    install_skills
    print_summary
}

main
