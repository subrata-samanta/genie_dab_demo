#!/usr/bin/env bash
# Stop early, with a clear message, when the GitHub environment's Databricks settings are missing.
# Run at the start of every job that talks to Databricks; TARGET_ENV is the job's GitHub environment.
set -euo pipefail

env_name="${TARGET_ENV:-?}"
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
