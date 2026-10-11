#!/usr/bin/env bash
# Record what an environment is now running, as a tag you can roll back to.
#
# One version number per version of the space, reused as that version promotes, so the tags read as a
# ladder:  genie-dev-v9  genie-qa-v9  genie-prod-v7  = dev and QA hold v9, prod still serves v7.
#
# Run straight after a successful deploy, NOT after the smoke test or the benchmark gate: the tag says
# what the environment IS RUNNING, which is what a rollback needs to know. QA is deployed before the gate
# runs, so a failed gate still leaves that version in QA - and the tag has to say so. Whether a version is
# any good is the run's status; prod can only ever receive one that passed, because the prod job needs qa.
#
# Writes two tags per environment:
#   genie-<env>-v<n>    never moves: the rollback point, and what "Use workflow from" lists
#   genie-<env>-current moves every deploy: what that environment is running right now
#
#     bash scripts/tag_release.sh qa
set -euo pipefail

env="${1:?usage: scripts/tag_release.sh <dev|qa|prod>}"
case "$env" in dev|qa|prod) ;; *) echo "unknown environment '$env'" >&2; exit 1 ;; esac

git fetch -q --tags origin 2>/dev/null || true
numbers() { sed -n 's/^genie-[a-z]*-v\([0-9]\{1,\}\)$/\1/p' | sort -n | tail -1; }

# This commit keeps the number it was already given in another environment; a new commit takes the next one.
version="$(git tag --points-at HEAD | numbers)"
if [[ -z "$version" ]]; then
  highest="$(git tag -l 'genie-*-v*' | numbers)"
  version=$(( ${highest:-0} + 1 ))
fi

tag="genie-${env}-v${version}"
if git rev-parse -q --verify "refs/tags/$tag" >/dev/null; then
  echo "$tag already exists (this version ran in $env before): keeping it"
else
  git tag "$tag"
  git push -q origin "$tag"
  echo "Tagged $tag"
fi

# The moving pointer. Not fatal: a protected-tag rule here must not fail a deployment that worked.
if git tag -f "genie-${env}-current" >/dev/null 2>&1 &&
   git push -q -f origin "genie-${env}-current" 2>/dev/null; then
  :
else
  echo "note: could not update genie-${env}-current (the version tag above is what matters)"
fi

# What every environment holds, so the run says where this version sits in the promotion ladder.
line=""
for e in dev qa prod; do
  v=""
  if git rev-parse -q --verify "refs/tags/genie-${e}-current" >/dev/null; then
    v="$(git tag --points-at "genie-${e}-current" | numbers)"
  fi
  if [[ -n "$v" ]]; then line+="  ${e}=v${v}"; else line+="  ${e}=none"; fi
done
echo "Deployed:${line}"
[[ -n "${GITHUB_STEP_SUMMARY:-}" ]] && echo "**${env} now runs v${version}** ·${line}" >> "$GITHUB_STEP_SUMMARY"
exit 0
