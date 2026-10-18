#!/usr/bin/env bash
# Runs the commit-msg hook over every commit of a range (make lint-commits; CI: the PR's commits).
#
# Usage: scripts/lint-commits.sh [<base> [<head>]]   (default: origin/main HEAD)
#
# Merge commits are left out: GitHub's "Update branch" creates them and nobody writes their
# subject. fixup!/squash! subjects, which the hook lets through while a branch is being worked on,
# are rejected here: they are squashed before the PR (skill commit).
set -euo pipefail
export LC_ALL=C.UTF-8
base=${1:-origin/main}
head=${2:-HEAD}
root=$(git rev-parse --show-toplevel)

commits=()
while IFS= read -r sha; do commits+=("$sha"); done < <(git rev-list --reverse --no-merges "$base..$head")
if [[ ${#commits[@]} -eq 0 ]]; then
  echo "lint-commits: no commits in $base..$head" >&2
  exit 1
fi

msg=$(mktemp)
trap 'rm -f "$msg"' EXIT
status=0
for sha in "${commits[@]}"; do
  git log -1 --format=%B "$sha" >"$msg"
  subject=$(sed -n '1p' "$msg")
  case "$subject" in
    "fixup! "* | "squash! "*)
      echo "lint-commits: ${sha:0:7} '$subject': squash it before the PR (skill commit)" >&2
      status=1
      continue
      ;;
  esac
  if bash "$root/scripts/git-hooks/commit-msg" "$msg"; then
    echo "ok ${sha:0:7} $subject"
  else
    echo "lint-commits: ${sha:0:7} rejected" >&2
    status=1
  fi
done
exit $status
