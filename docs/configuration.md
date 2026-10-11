# Configuration

Everything specific to one Genie space lives in **`config/project.yml`**. Every other file is the same in
every copy of this repository, which is what makes it a template: clone it, edit that one file, and the
workflows, scripts and tests work unchanged.

## The split

| File | Edited per space? | What it holds |
|---|---|---|
| `config/project.yml` | **yes — this one** | bundle name, title, warehouse, catalogs, access |
| `databricks.yml` | no | the promotion path and deployment folders |
| `resources/genie_space.genie_space.yml` | no | the resource, built from the variables |
| `src/genie_space.geniespace.json` | never by hand | the space's content, written by the workflows |

`config/project.yml` has two consumers: the bundle includes it (`include: config/*.yml`), and the Python
scripts read it through `space_lib.config()`. One file, one source of truth.

## `config/project.yml`

### `bundle.name`

A short unique name, e.g. `genie-finance-assistant`. It names the deployment folder and the record
Databricks keeps of the adopted space.

**Pick it once.** Changing it later makes the bundle forget which space it manages; the next deploy would
try to create a second one. (It will not succeed — `deploy_guard.py` refuses — but you will have to
`bundle deployment bind` it back.)

### The space

| Variable | |
|---|---|
| `space_title` | the title in the Genie list. The environment suffix is appended, so this is the name without `[DEV]` |
| `space_description` | one line, shown under the title |

### Where it runs

| Variable | |
|---|---|
| `targets.<env>.warehouse_id` | the SQL warehouse that environment's space runs on, as an id — **set one per target**. Warehouse ids are workspace-scoped, so each environment has its own even when the warehouses are named the same. Quote it, or an all-digit id is read as a number. Use a **serverless** warehouse — Databricks recommends never Classic or Pro for Genie |

### The workspace per environment

```yaml
targets:
  dev:
    workspace:
      host: https://<dev workspace>.cloud.databricks.com
```

The workspace each environment deploys to, and it is **authoritative**:

- **In CI** it takes precedence over that environment's `DATABRICKS_HOST`. A mis-set GitHub variable
  cannot redirect a deploy into another environment's workspace — the bundle decides where its content
  goes. The credentials still have to be valid in the pinned workspace, so a mismatched principal fails
  to authenticate rather than deploying somewhere unintended.
- **Locally**, a profile pointing at a different workspace is refused outright:
  `the host in the profile doesn't match the host configured in the bundle`.

Without the pin, the destination is whatever `DATABRICKS_HOST` happens to be — which is exactly the
failure mode worth removing. Delete the `workspace:` blocks only if you want that behaviour back.

A workspace per environment is the stronger isolation and what Databricks recommends. One shared
workspace also works — repeat the same host — but then a single compromised principal reaches every
environment's data.

### The data

| Variable | |
|---|---|
| `dev_catalog` | the catalog the dev space reads. Must match what is inside the exported JSON, or the format check fails |
| `targets.<env>.catalog` | the catalog for each environment |

With a workspace per environment the catalog may keep the **same name** everywhere; `set_catalog.sh` then
rewrites nothing and `title_suffix` becomes optional. Different names per environment work too, which is
required when the environments share a workspace.

`dev_catalog` is load-bearing: `set_catalog.sh` rewrites exactly that string when deploying to QA and
prod, and `check_space.py` enforces that the JSON references nothing else.

### Access

`space_permissions` is applied on **every deployment and is exact** — whatever is listed becomes the
space's access, and anything granted by hand in the UI is removed. That is the point: access is reviewed
in git rather than drifting in a dialog box.

```yaml
space_permissions:
  - level: CAN_MANAGE
    group_name: <release managers group>
  - level: CAN_RUN
    group_name: <readers group>
```

Valid levels for a Genie space: `CAN_READ`, `CAN_RUN`, `CAN_EDIT`, `CAN_MANAGE`.

The default applies to QA and prod; the `dev` target adds `CAN_EDIT` for the editors, because dev is the
only environment anyone should edit.

Two things keep this from locking anyone out: workspace admins and the deploying service principal keep
access through inheritance, and `mode: production` adds the deploying identity as `CAN_MANAGE`
automatically. **The groups must already exist** in the workspace, or the deployment fails.

### Where the deployment record lives

| Variable | Default | |
|---|---|---|
| `deployment_root` | `/Workspace/Applications` | parent folder for the bundle's record of the space |

Restrict write access on this folder to the service principal that deploys that environment. See
[access-and-identity.md](access-and-identity.md) for why it must not contain a user name.

## `databricks.yml`

Identical in every copy. It holds the bundle engine (`direct` — the Terraform engine does **not** support
`genie_spaces`), the include list, and the three targets.

Each target sets only `mode: production` and

```yaml
root_path: ${var.deployment_root}/${bundle.name}/${bundle.target}
```

Note what is **absent**: `${workspace.current_user.userName}`. See
[access-and-identity.md](access-and-identity.md#the-deployment-folder).

## `resources/genie_space.genie_space.yml`

The `genie_spaces` resource, built entirely from variables:

```yaml
resources:
  genie_spaces:
    genie_space:
      title: "${var.space_title}${var.title_suffix}"
      description: ${var.space_description}
      file_path: ../src/genie_space.geniespace.json
      warehouse_id: ${var.warehouse_id}
      permissions: ${var.space_permissions}
```

The resource key `genie_space` is a shared convention: `bundle generate --key genie_space` writes that
name, `deploy_guard.py` reads `resources.genie_spaces.genie_space` from the plan, and the workflows
extract the space id from `bundle summary` by the same path. Renaming it breaks all three.

## GitHub

Not in the repository, because it is per-workspace rather than per-space.

| Where | Setting |
|---|---|
| Environments `dev`, `qa`, `prod` (names exactly lower case) | `DATABRICKS_HOST`, `DATABRICKS_CLIENT_ID` |
| Secret per environment, only without federation | `DATABRICKS_CLIENT_SECRET` |
| `prod` environment | required reviewers; deployment branches and tags `main` and `genie-prod-v*` |
| `dev` / `qa` environments | if you restrict deployment branches, **allow the tags too** (`genie-dev-v*`), or resetting dev to an earlier version is blocked before the job starts |
| Repository or environment variable | `ACCURACY_THRESHOLD`, default `0.80` |
| Actions → General | *Allow GitHub Actions to create and approve pull requests* |
| Secret `GENIE_BOT_TOKEN` | recommended: without it, pull requests opened by the sync do not trigger their own checks |
| Branch protection on `main` | require a pull request and the checks **format** and **validate** |

**Paste these values with no trailing newline.** A newline in `DATABRICKS_HOST` breaks every CLI call in
that environment with an error that names a URL, not a setting.
