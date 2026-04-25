#!/usr/bin/env bash
# Release helper for the Nubly Home Assistant integration.
#
# Usage: ./scripts/release.sh <version>
# Example: ./scripts/release.sh 0.1.1
#
# Bumps custom_components/nubly/manifest.json, commits, and creates a git tag.
# After running, push with:
#   git push
#   git push --tags
# The pushed tag triggers .github/workflows/release.yml to publish a GitHub Release.

set -euo pipefail

VERSION="${1:-}"

if [[ -z "$VERSION" ]]; then
    echo "Usage: $0 <version>" >&2
    echo "Example: $0 0.1.1" >&2
    exit 1
fi

# Accept X.Y.Z or X.Y.Z-prerelease (e.g. 1.0.0-rc1).
if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[A-Za-z0-9.]+)?$ ]]; then
    echo "Error: '$VERSION' is not a valid semver version (e.g. 0.1.1, 1.0.0-rc1)" >&2
    exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MANIFEST="$REPO_ROOT/custom_components/nubly/manifest.json"

if [[ ! -f "$MANIFEST" ]]; then
    echo "Error: manifest not found at $MANIFEST" >&2
    exit 1
fi

if [[ -n "$(git -C "$REPO_ROOT" status --porcelain)" ]]; then
    echo "Error: working tree has uncommitted changes — commit or stash first." >&2
    git -C "$REPO_ROOT" status --short
    exit 1
fi

if git -C "$REPO_ROOT" rev-parse --verify "v$VERSION" >/dev/null 2>&1; then
    echo "Error: tag v$VERSION already exists" >&2
    exit 1
fi

python3 - "$MANIFEST" "$VERSION" <<'PY'
import json
import sys

manifest_path, version = sys.argv[1], sys.argv[2]
with open(manifest_path, encoding="utf-8") as f:
    data = json.load(f)
data["version"] = version
with open(manifest_path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
PY

echo "Updated manifest to version $VERSION"

git -C "$REPO_ROOT" add "$MANIFEST"
git -C "$REPO_ROOT" commit -m "chore: release v$VERSION"
git -C "$REPO_ROOT" tag "v$VERSION"

echo
echo "Release v$VERSION committed and tagged locally."
echo "Push with:"
echo "  git push"
echo "  git push --tags"
