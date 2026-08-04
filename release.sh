#!/bin/bash

set -euo pipefail

usage() {
    echo "Usage: ./release.sh X.Y.Z"
}

if [[ $# -ne 1 ]]; then
    usage >&2
    exit 2
fi

version=$1
semver='^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?(\+[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?$'
valid=1
if [[ $version =~ $semver ]]; then
    core=${version%%+*}
    if [[ $core == *-* ]]; then
        prerelease=${core#*-}
        IFS=. read -ra identifiers <<< "$prerelease"
        for identifier in "${identifiers[@]}"; do
            if [[ $identifier =~ ^[0-9]+$ && $identifier != "0" && $identifier == 0* ]]; then
                valid=0
            fi
        done
    fi
else
    valid=0
fi
if [[ $valid != 1 ]]; then
    echo "Error: version must be valid SemVer without a leading v" >&2
    exit 2
fi

root=$(git rev-parse --show-toplevel 2>/dev/null) || {
    echo "Error: release.sh must be run from a Git repository" >&2
    exit 1
}
cd "$root"

if [[ $(git branch --show-current) != "main" ]]; then
    echo "Error: releases must be created from main" >&2
    exit 1
fi
if [[ -n $(git status --porcelain) ]]; then
    echo "Error: working tree must be clean" >&2
    exit 1
fi
if git rev-parse -q --verify "refs/tags/v$version" >/dev/null; then
    echo "Error: tag v$version already exists" >&2
    exit 1
fi

current=$(<VERSION)
if [[ $(./term-cli --version) != "term-cli $current" ]] ||
   [[ $(./term-assist --version) != "term-assist $current" ]]; then
    echo "Error: embedded versions do not match VERSION" >&2
    exit 1
fi

if [[ $version != "$current" ]]; then
    VERSION_NEXT=$version python3 - <<'PY'
import os
import re
from pathlib import Path

version = os.environ["VERSION_NEXT"]
for name in ("term-cli", "term-assist"):
    path = Path(name)
    updated, count = re.subn(
        r'^__version__ = "[^"]+"$',
        f'__version__ = "{version}"',
        path.read_text(),
        flags=re.MULTILINE,
    )
    if count != 1:
        raise SystemExit(f"Expected exactly one __version__ in {name}")
    path.write_text(updated)
Path("VERSION").write_text(f"{version}\n")
PY
fi

pyright
./run-tests.sh

if [[ $version != "$current" ]]; then
    git add VERSION term-cli term-assist
    git diff --cached --check
    git commit -m "release: v$version"
    echo
    echo "Created the v$version version commit. Push it and wait for CI:"
    echo "  git push origin main"
    echo "Then rerun: ./release.sh $version"
    exit 0
fi

upstream=$(git rev-parse --verify '@{upstream}' 2>/dev/null) || {
    echo "Error: main must have an upstream branch before tagging" >&2
    exit 1
}
if [[ $(git rev-parse HEAD) != "$upstream" ]]; then
    echo "Error: push the version commit and wait for CI before tagging" >&2
    exit 1
fi

git tag -a "v$version" -m "term-cli v$version"

echo
echo "Created v$version. Publish it with:"
echo "  git push origin v$version"
