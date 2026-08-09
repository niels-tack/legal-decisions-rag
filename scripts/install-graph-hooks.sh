#!/usr/bin/env bash
# Install code-review-graph git hooks into .git/hooks/.
#
# Each hook is copied from scripts/git-hooks/. If a hook already exists and
# wasn't installed by this script, the existing file is backed up first so
# nothing is lost.
#
# Usage:
#   bash scripts/install-graph-hooks.sh
#   just graph-hooks   (via justfile)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
HOOKS_SRC="$SCRIPT_DIR/git-hooks"
HOOKS_DEST="$REPO_ROOT/.git/hooks"

HOOKS=(post-commit post-checkout post-merge)

echo "Installing code-review-graph git hooks..."

for hook in "${HOOKS[@]}"; do
    src="$HOOKS_SRC/$hook"
    dest="$HOOKS_DEST/$hook"

    if [ ! -f "$src" ]; then
        echo "  [skip] $hook — source not found at $src"
        continue
    fi

    # Back up an existing hook that wasn't installed by us.
    if [ -f "$dest" ] && ! grep -q "code-review-graph" "$dest" 2>/dev/null; then
        backup="$dest.bak"
        echo "  [backup] existing $hook → $hook.bak"
        cp "$dest" "$backup"
    fi

    cp "$src" "$dest"
    chmod +x "$dest"
    echo "  [ok] installed $hook"
done

echo ""
echo "Done. Run 'just graph-build' to perform the initial full build."
