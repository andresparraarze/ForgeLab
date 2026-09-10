#!/usr/bin/env bash
# Cut a release: move the CHANGELOG's Unreleased section under a version
# heading, commit it, and tag that commit.
#
#   scripts/release.sh patch|minor|major   # bump from the latest tag
#   scripts/release.sh 0.2.0               # or name the version outright
#   scripts/release.sh patch --push        # ...and push the commit + tag
#
# The version itself is NOT written anywhere: it is derived from the tag by
# hatch-vcs (see [tool.hatch.version]). That is the whole point — a literal in
# pyproject would be a second copy to forget. `git tag v0.1.0` IS the version
# bump; between tags the build reports 0.1.1.dev47+g<sha>, which is a truthful
# statement that it is 47 commits past 0.1.0 and not a release.
#
# So this script exists for the parts a tag does not do by itself: refusing to
# tag something red or dirty, and keeping the CHANGELOG honest.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
cd "$REPO"

# The gates run ruff/pyright/pytest by bare name, which on this project means
# the local venv has to be on PATH — a footgun worth absorbing here rather than
# failing three minutes into a release.
[ -d "$REPO/.venv/bin" ] && PATH="$REPO/.venv/bin:$PATH"
export PATH

ok()   { printf '\033[32m✔\033[0m %s\n' "$1"; }
fail() { printf '\033[31m✘ %s\033[0m\n' "$1" >&2; exit 1; }
step() { printf '\033[36m→ %s\033[0m\n' "$1"; }

BUMP="${1:-}"
PUSH="${2:-}"
[ -n "$BUMP" ] || fail "usage: scripts/release.sh patch|minor|major|X.Y.Z [--push]"

# --- work out the version first: the checks below take minutes, and an
#     unusable argument should not cost you those ------------------------------

LATEST="$(git tag --list 'v[0-9]*' --sort=-v:refname | head -1)"
case "$BUMP" in
  major|minor|patch)
    IFS=. read -r MA MI PA <<< "${LATEST#v}"
    MA="${MA:-0}"; MI="${MI:-0}"; PA="${PA:-0}"
    [ -n "$LATEST" ] || { MA=0; MI=1; PA=0; BUMP=first; }
    case "$BUMP" in
      major) MA=$((MA + 1)); MI=0; PA=0 ;;
      minor) MI=$((MI + 1)); PA=0 ;;
      patch) PA=$((PA + 1)) ;;
    esac
    VERSION="$MA.$MI.$PA"
    ;;
  [0-9]*.[0-9]*.[0-9]*) VERSION="$BUMP" ;;
  *) fail "unrecognized bump $BUMP (want major|minor|patch|X.Y.Z)." ;;
esac

TAG="v$VERSION"
if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
  fail "$TAG already exists."
fi
ok "releasing $TAG${LATEST:+ (from $LATEST)}"

# --- refuse to release something that is not releasable ----------------------

[ "$(git rev-parse --abbrev-ref HEAD)" = "main" ] \
  || fail "releases are cut from main (on $(git rev-parse --abbrev-ref HEAD))."
[ -z "$(git status --porcelain)" ] \
  || fail "working tree is dirty; commit or stash first."

step "Running the gates"
scripts/check.sh >/dev/null || fail "gates failed — not tagging a red tree."
ok "gates passed"

step "Verifying a real install"
scripts/verify-install.sh >/dev/null 2>&1 || fail "verify-install.sh failed."
ok "install verified"

# --- cut the CHANGELOG -------------------------------------------------------

step "Cutting the CHANGELOG"
grep -q '^## \[Unreleased\]' CHANGELOG.md || fail "CHANGELOG has no [Unreleased] section."
python3 scripts/cut_changelog.py "$VERSION" || fail "could not cut the CHANGELOG."
ok "CHANGELOG updated"

git add CHANGELOG.md
git commit -q -m "release: $VERSION

Cut by scripts/release.sh. The version is derived from this tag by hatch-vcs;
nothing in the tree records it."
git tag -a "$TAG" -m "ForgeLab $VERSION"
ok "committed and tagged $TAG"

if [ "$PUSH" = "--push" ]; then
  step "Pushing"
  git push origin main
  git push origin "$TAG"
  ok "pushed main and $TAG"
else
  echo
  echo "  Not pushed. To publish this release:"
  echo "    git push origin main && git push origin $TAG"
fi
