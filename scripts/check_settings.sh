#!/usr/bin/env bash
# Stop early, with a clear message, when the GitHub environment's Databricks settings are missing.
# Run at the start of every job that talks to Databricks; TARGET_ENV is the job's GitHub environment.
set -euo pipefail

env_name="${TARGET_ENV:-?}"

# A setting pasted into GitHub with a trailing newline reaches the CLI as "https://host\r\n" and fails
# with 'net/url: invalid control character in URL' in whatever step first calls the CLI, far from the
# cause. Strip stray whitespace here and re-export the clean value for the job's later steps.
trim() { printf '%s' "${1-}" | tr -d '\r\n' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'; }
cleaned=()
for name in DATABRICKS_HOST DATABRICKS_CLIENT_ID DATABRICKS_CLIENT_SECRET; do
  raw="${!name-}"
  [[ -n "$raw" ]] || continue
  clean="$(trim "$raw")"
  [[ "$clean" == "$raw" ]] && continue
  # The trimmed secret is a different string, so register it for masking too.
  [[ "$name" == "DATABRICKS_CLIENT_SECRET" ]] && echo "::add-mask::$clean"
  export "$name=$clean"
  [[ -n "${GITHUB_ENV:-}" ]] && printf '%s=%s\n' "$name" "$clean" >> "$GITHUB_ENV"
  cleaned+=("$name")
done
if (( ${#cleaned[@]} )); then
  echo "::warning title=Stray whitespace in the Databricks settings for '$env_name'::Trimmed ${cleaned[*]}; re-enter the value(s) without a trailing newline (Settings → Environments → $env_name)."
fi

missing=()
[[ -n "${DATABRICKS_HOST:-}" ]] || missing+=("DATABRICKS_HOST (the workspace URL, e.g. https://adb-123.azuredatabricks.net)")
[[ -n "${DATABRICKS_CLIENT_ID:-}" ]] || missing+=("DATABRICKS_CLIENT_ID (the application id of the $env_name service principal)")
if (( ${#missing[@]} )); then
  echo "::error title=Databricks settings missing for '$env_name'::Set them in GitHub: Settings → Environments → $env_name → Environment variables (or as repository variables)."
  echo "Missing for the GitHub environment '$env_name':"
  printf '  - %s\n' "${missing[@]}"
  echo
  echo "Where: Settings → Environments → $env_name → Environment variables → Add variable."
  echo "(Variables or secrets with these names both work. The environment name must be exactly '$env_name'.)"
  exit 1
fi

if [[ -z "${DATABRICKS_CLIENT_SECRET:-}" ]]; then
  if [[ -z "${ACTIONS_ID_TOKEN_REQUEST_URL:-}" ]]; then
    echo "::error::Passwordless login needs 'permissions: id-token: write' in the workflow, or set a DATABRICKS_CLIENT_SECRET secret for '$env_name'."
    exit 1
  fi
  echo "Databricks: $DATABRICKS_HOST as $DATABRICKS_CLIENT_ID, passwordless login (workload identity federation)."
  echo "If login fails: the service principal needs a GitHub federation policy with subject"
  echo "  repo:${GITHUB_REPOSITORY:-<owner>/<repo>}:environment:$env_name"
else
  echo "Databricks: $DATABRICKS_HOST as $DATABRICKS_CLIENT_ID, OAuth with the DATABRICKS_CLIENT_SECRET secret."
fi
