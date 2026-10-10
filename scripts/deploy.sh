#!/usr/bin/env bash
# Deploy the bundle to a target.
#
# The Genie space lives in the bundle's resources folder (parent_path defaults to ${workspace.resource_path}).
# Databricks does not create that folder when the bundle creates or moves a space into it (404 "Tree node ...
# does not exist"), e.g. when the adopted dev space is moved there on its first deployment. So create it first.
#
#     bash scripts/deploy.sh dev
set -euo pipefail

target="${1:?usage: scripts/deploy.sh <target>}"
resource_path="$(databricks bundle validate -t "$target" -o json | jq -r '.workspace.resource_path')"
databricks workspace mkdirs "${resource_path#/Workspace}"
databricks bundle deploy -t "$target" --auto-approve
