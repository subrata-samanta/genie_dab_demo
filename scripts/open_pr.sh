#!/usr/bin/env bash
# Commit the exported space on a bot branch and open (or update) its pull request into main.
# Used by the bootstrap and dev-sync workflows; needs git and the GitHub CLI (gh, with GH_TOKEN).
#
#     bash scripts/open_pr.sh <branch> <pr title> <pr body file> <commit message>
#
# The branch always starts from main and holds one commit: the current export. Re-running it with a newer
# export replaces that commit (force push), so the pull request always shows main -> the live dev space.
set -euo pipefail

branch="${1:?branch}"; title="${2:?title}"; body_file="${3:?body file}"; message="${4:?commit message}"
base="${BASE_BRANCH:-main}"

git config user.name  "${GIT_AUTHOR_NAME:-genie-sync-bot}"
git config user.email "${GIT_AUTHOR_EMAIL:-41898282+github-actions[bot]@users.noreply.github.com}"
git checkout -q -B "$branch"
git add src/
git commit -q -m "$message"
git push -q --force origin "$branch"

number="$(gh pr list --head "$branch" --base "$base" --state open --json number | jq -r '.[0].number // empty')"
if [[ -n "$number" ]]; then
  gh pr edit "$number" --title "$title" --body-file "$body_file" > /dev/null
  echo "Updated pull request #$number"
else
  gh pr create --base "$base" --head "$branch" --title "$title" --body-file "$body_file"
  echo "Opened a pull request"
fi
