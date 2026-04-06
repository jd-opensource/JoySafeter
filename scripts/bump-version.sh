#!/usr/bin/env bash
#
# bump-version.sh — Bump project version, update CHANGELOG, commit and tag.
#
# Usage:
#   ./scripts/bump-version.sh <new-version>
#
# Example:
#   ./scripts/bump-version.sh 0.3.0
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# --- Arg parsing ---
if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <new-version>"
    echo "Example: $0 0.3.0"
    exit 1
fi

NEW_VERSION="$1"

# Strip leading 'v' if provided
NEW_VERSION="${NEW_VERSION#v}"

# --- Validate semver format ---
if ! [[ "$NEW_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[a-zA-Z0-9.]+)?$ ]]; then
    echo "Error: '$NEW_VERSION' is not a valid semver (expected X.Y.Z or X.Y.Z-pre)"
    exit 1
fi

TAG="v${NEW_VERSION}"

# --- Check we're in a git repo ---
if ! git -C "$ROOT_DIR" rev-parse --is-inside-work-tree &>/dev/null; then
    echo "Error: not inside a git repository"
    exit 1
fi

# --- Check tag doesn't already exist ---
if git -C "$ROOT_DIR" tag -l "$TAG" | grep -q "^${TAG}$"; then
    echo "Error: tag '$TAG' already exists"
    exit 1
fi

# --- Check working tree is clean ---
if ! git -C "$ROOT_DIR" diff --quiet || ! git -C "$ROOT_DIR" diff --cached --quiet; then
    echo "Error: working tree has uncommitted changes. Commit or stash them first."
    exit 1
fi

echo "Bumping version to ${NEW_VERSION} (tag: ${TAG})"
echo ""

# Track which files were modified
MODIFIED_FILES=()

# --- Portable sed in-place: write to temp then move ---
sed_inplace() {
    local file="$1"
    shift
    sed "$@" "$file" > "${file}.tmp" && mv "${file}.tmp" "$file"
}

# --- 1. Update backend/pyproject.toml ---
PYPROJECT="$ROOT_DIR/backend/pyproject.toml"
if [[ -f "$PYPROJECT" ]]; then
    sed_inplace "$PYPROJECT" -E 's/^version = ".*"/version = "'"$NEW_VERSION"'"/'
    MODIFIED_FILES+=("backend/pyproject.toml")
    echo "  Updated $PYPROJECT"
else
    echo "  Warning: $PYPROJECT not found, skipping"
fi

# --- 2. Update backend/app/__init__.py ---
INIT_PY="$ROOT_DIR/backend/app/__init__.py"
if [[ -f "$INIT_PY" ]]; then
    sed_inplace "$INIT_PY" -E 's/^__version__ = ".*"/__version__ = "'"$NEW_VERSION"'"/'
    MODIFIED_FILES+=("backend/app/__init__.py")
    echo "  Updated $INIT_PY"
else
    echo "  Warning: $INIT_PY not found, skipping"
fi

# --- 3. Update frontend/package.json (top-level "version" only) ---
PACKAGE_JSON="$ROOT_DIR/frontend/package.json"
if [[ -f "$PACKAGE_JSON" ]]; then
    # Anchor to 2-space indent to match only the top-level "version" field
    sed_inplace "$PACKAGE_JSON" -E 's/^(  "version": )".*"/\1"'"$NEW_VERSION"'"/'
    MODIFIED_FILES+=("frontend/package.json")
    echo "  Updated $PACKAGE_JSON"
else
    echo "  Warning: $PACKAGE_JSON not found, skipping"
fi

# --- 4. Update CHANGELOG.md via Claude Code ---
CHANGELOG="$ROOT_DIR/CHANGELOG.md"
TODAY=$(date +%Y-%m-%d)

# Find the previous tag to get the commit range
PREV_TAG=$(git -C "$ROOT_DIR" describe --tags --abbrev=0 2>/dev/null || echo "")

if [[ -n "$PREV_TAG" ]]; then
    COMMIT_RANGE="${PREV_TAG}..HEAD"
    echo "  Generating changelog for commits: ${PREV_TAG}..HEAD"
else
    COMMIT_RANGE="HEAD"
    echo "  Generating changelog for all commits (no previous tag found)"
fi

# Collect git log
GIT_LOG=$(git -C "$ROOT_DIR" log "$COMMIT_RANGE" --pretty=format:"- %s (%h)" --no-merges 2>/dev/null || echo "")

if [[ -z "$GIT_LOG" ]]; then
    echo "  Warning: no commits found since $PREV_TAG, using placeholder"
    CHANGELOG_BODY="_No changes recorded._"
else
    # Use Claude Code to generate structured CHANGELOG from commits (pipe via stdin to avoid ARG_MAX)
    echo "  Invoking Claude Code to generate release notes..."

    CHANGELOG_BODY=$(cat <<PROMPT_EOF | claude -p 2>/dev/null || echo ""
Based on the following git commits for release ${TAG}, generate a well-structured CHANGELOG section in markdown.

Rules:
- Group changes by category (e.g. Features, Bug Fixes, Refactoring, etc.) using ### headings
- Write in concise, user-facing language (not git-commit-ese)
- Use Chinese for descriptions to match the existing CHANGELOG style
- Output ONLY the markdown body (no version heading, no date, no fences)
- If a commit is trivial (typo, merge, formatting), you may omit it

Commits:
${GIT_LOG}
PROMPT_EOF
    )

    if [[ -z "$CHANGELOG_BODY" ]]; then
        echo "  Warning: Claude Code returned empty response, falling back to raw git log"
        CHANGELOG_BODY="$GIT_LOG"
    fi
fi

if [[ -f "$CHANGELOG" ]]; then
    ENTRY_HEADER="## ${TAG} — ${TODAY}"

    # Use ENVIRON to avoid awk -v backslash interpretation
    export CHANGELOG_BODY
    awk -v header="$ENTRY_HEADER" '
        /^---$/ && !done {
            print
            printf "\n%s\n\n%s\n\n---\n", header, ENVIRON["CHANGELOG_BODY"]
            done=1
            next
        }
        { print }
    ' "$CHANGELOG" > "${CHANGELOG}.tmp"
    mv "${CHANGELOG}.tmp" "$CHANGELOG"
    unset CHANGELOG_BODY
    MODIFIED_FILES+=("CHANGELOG.md")
    echo "  Updated $CHANGELOG (added ${TAG} section with AI-generated notes)"
else
    echo "  Warning: $CHANGELOG not found, skipping"
fi

echo ""

# --- 5. Git commit and tag (only add files that were actually modified) ---
if [[ ${#MODIFIED_FILES[@]} -eq 0 ]]; then
    echo "Error: no files were modified"
    exit 1
fi

cd "$ROOT_DIR"
git add "${MODIFIED_FILES[@]}"

git commit -m "release: ${TAG}

Bump version to ${NEW_VERSION} and update CHANGELOG."

git tag -a "$TAG" -m "Release ${TAG}"

echo ""
echo "Done! Version bumped to ${NEW_VERSION}, committed and tagged as ${TAG}."
echo ""
echo "Next steps:"
echo "  1. Review CHANGELOG.md — AI-generated notes may need minor edits"
echo "     If edits needed: git add CHANGELOG.md && git commit --amend --no-edit"
echo "  2. Push to trigger the release pipeline:"
echo "     git push && git push --tags"
