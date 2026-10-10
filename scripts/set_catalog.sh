#!/usr/bin/env bash
# Point the space JSON at a target's catalog before deploying to that target.
#
# The JSON is exported from the dev space, so its tables read the dev catalog (variable dev_catalog).
# Bundles do not substitute variables inside a file_path file, so this rewrites "<dev_catalog>." to
# "<the target's catalog>." in the pipeline's throw-away checkout. Never commit the result.
#
#     bash scripts/set_catalog.sh qa
set -euo pipefail

target="${1:?usage: scripts/set_catalog.sh <target>}"
space_file="src/genie_space.geniespace.json"

variables="$(databricks bundle validate -t "$target" -o json | jq -c '.variables')"
dev_catalog="$(jq -r '.dev_catalog.value' <<<"$variables")"
catalog="$(jq -r '.catalog.value' <<<"$variables")"
if [[ -z "$catalog" || "$catalog" == "null" || -z "$dev_catalog" || "$dev_catalog" == "null" ]]; then
  echo "catalog / dev_catalog not set for target $target" >&2
  exit 1
fi
if [[ "$catalog" == "$dev_catalog" ]]; then
  echo "Target $target reads the dev catalog ($catalog): nothing to rewrite"
  exit 0
fi
# Replace the catalog where it starts an identifier (optionally `quoted`), in data sources and in SQL.
# Written to a temporary file (not sed -i) so it works with GNU and macOS sed.
sed -E "s/([^A-Za-z0-9_])(\`?)${dev_catalog}(\`?)\./\1\2${catalog}\3./g" "$space_file" > "$space_file.tmp"
mv "$space_file.tmp" "$space_file"
if grep -q "[^A-Za-z0-9_]\`\{0,1\}${dev_catalog}\`\{0,1\}\." "$space_file"; then
  echo "the dev catalog $dev_catalog is still referenced after the rewrite" >&2
  exit 1
fi
echo "Space for target $target now reads catalog $catalog (was $dev_catalog)"
