# Moving QA and prod into their own workspaces

A migration runbook: today all three environments deploy into one workspace; this moves QA into a QA
workspace and prod into a prod workspace. Do it one environment at a time, QA first.

## Read this before you start

**A Genie space cannot be moved between workspaces.** Space ids are workspace-scoped, so the QA and prod
spaces in the new workspaces are *new spaces*: new URLs, and **no conversation history**. The content is
identical because it comes from git, but anyone who bookmarked the old prod space needs the new link.
Plan the announcement before you deploy, not after.

Dev is unaffected. Leave it where it is until QA and prod are proven.

### Two decisions that change the work

**1. Do the new workspaces share this metastore?** This one is `74e0adce-a23a-493c-bc32-a0af6f7b0c32`.
A metastore is per-region and can be attached to many workspaces.

- **Same metastore** (new workspaces in the same region): the catalogs already exist and are reachable —
  all three are currently `isolation=OPEN`, meaning any workspace on the metastore can see them. No data
  to move. This is the simpler path.
- **Different metastore** (different region, or a deliberate split): the data must be created in the new
  metastore first, and a catalog with the name in `config/project.yml` must exist there.

**2. One service principal, or one per workspace?** One per workspace is the recommendation and the
reason to do this at all — today a single principal reaches every environment's data. A workspace-local
service principal exists only in its workspace; an account-level one can be assigned to several.

---

## Step 1 — Create the workspaces

Create the QA and prod workspaces and attach each to a metastore. Note each workspace URL; you need it
in two places later (`config/project.yml` and the GitHub environment).

## Step 2 — Groups: the one that bites

**Check this before anything else.** All five groups this repository depends on are currently
**workspace-local**, not account groups:

```
freshcart-genie-deployers    WorkspaceGroup
freshcart-genie-developers   WorkspaceGroup
freshcart-business-users     WorkspaceGroup
fc_all_regions               WorkspaceGroup
fc_crm_admins                WorkspaceGroup
```

A workspace-local group **does not exist in another workspace**. Left as they are, two things break in
the new workspaces, one loudly and one silently:

| | What happens |
|---|---|
| `space_permissions` | the deployment **fails**: the groups named in `config/project.yml` do not exist there |
| The row filter | **silently returns nothing.** `rls_region` admits `is_account_group_member('fc_all_regions') OR is_member('fc_all_regions')`. `is_member` tests the *workspace-local* group, which is absent, and the account check is false because the group is not an account group. Every query succeeds and returns zero rows |

The second is the failure mode that cost the most time on this project: a working pipeline that answers
nothing.

**Do this:** recreate the five groups as **account groups** (Account console → User management → Groups)
and assign them to the dev, QA and prod workspaces. Keep the names identical — the row filter function
and `config/project.yml` both match on name.

Then confirm, in each workspace:

```sql
SELECT is_account_group_member('fc_all_regions');   -- run as the service principal
```

## Step 3 — Per workspace: principal, warehouse, data access

In **each** new workspace:

1. **A service principal** for CI. Give it workspace access and Databricks SQL access.
2. **A SQL warehouse** — serverless. Note its **id** (`/sql/warehouses/<id>` in the URL, or
   `databricks warehouses list`). Give the principal `CAN USE`.
3. **Catalog grants**, in that workspace, for that principal:

   ```sql
   GRANT `USE CATALOG`, `USE SCHEMA`, SELECT, EXECUTE
     ON CATALOG <catalog>
     TO `<application-id>`;
   ```

4. **Row-filter group membership**: add the principal to `fc_all_regions` (now an account group).
5. The **deployment folder** `/Workspace/Applications/genie-dab-demo/<target>` — restrict write access to
   that principal.

> Different metastore? Create the data and the catalog there first. A Genie space cannot be deployed
> before its tables exist.

## Step 4 — Optional: isolate the catalogs

All three catalogs are `isolation=OPEN` today, so every workspace on the metastore can read them —
including prod data from the dev workspace. Now that workspaces are separate, binding each catalog to
its workspace is what actually delivers the isolation you are doing this for:

Catalog → **Permissions → Workspaces** → set to isolated, bind `freshcart_qa` to the QA workspace and
`freshcart` to prod.

Do this **after** the deployments work, so a binding mistake and a deployment mistake cannot be confused.

## Step 5 — GitHub environments

For `qa` and then `prod`:

- `DATABRICKS_HOST` — the new workspace URL, **no trailing newline, no trailing slash**
- `DATABRICKS_CLIENT_ID` — that workspace's service principal
- `DATABRICKS_CLIENT_SECRET`, or a federation policy with subject
  `repo:<owner>/<repo>:environment:<env>`

## Step 6 — Point the repository at the new workspaces

In `config/project.yml`, for the target you are migrating:

```yaml
  qa:
    workspace:
      host: https://<qa workspace>.cloud.databricks.com
    variables:
      warehouse_id: "<qa warehouse id>"
      catalog: freshcart_qa
      title_suffix: " [QA]"
```

Both values change: the **host**, and the **warehouse id** (ids are workspace-scoped, so the old one is
meaningless in the new workspace).

If the catalog is named the same in the new workspace, delete the `catalog:` line — it then inherits
`dev_catalog`.

Check before pushing:

```bash
databricks bundle validate -t qa
```

## Step 7 — Verify as the service principal, before deploying

```bash
export DATABRICKS_HOST=https://<qa workspace>.cloud.databricks.com
export DATABRICKS_CLIENT_ID=<qa application id>
export DATABRICKS_CLIENT_SECRET=<a short-lived secret>
export DATABRICKS_AUTH_TYPE=oauth-m2m

python scripts/check_access.py --target qa
```

This is the step that catches every mistake above, before anything is deployed:

- host set here but not in `config/project.yml`, or the reverse → it refuses and prints both
- missing catalog grants → the data source is reported as an error
- **`[EMPTY]`** on a data source → the group work in step 2 is not done. Fix it now; a deployment would
  succeed and answer nothing

Expect every data source `[ok]` and `Access OK for qa.`

## Step 8 — Deploy

**Actions → 3 · Release → Run workflow**, target `qa`.

The bundle has no record of a space in the new workspace, so the plan says **create** — correct here.
`deploy_guard.py` checks the new workspace for a space with the same title, finds none, and allows it.

> If the guard stops with *the plan would CREATE a space, but '…' already exists*, you are pointed at a
> workspace that already has that space — almost certainly the old one. Re-check step 6.

Then confirm: the QA benchmark gate passes, and the new space answers in the Genie UI.

## Step 9 — Repeat for prod

Steps 3, 5, 6, 7, then **Run workflow, target `prod`** — which re-runs the QA gate and waits for
approval. Afterwards, send the new prod space URL to its users.

## Step 10 — Retire the old spaces

The old QA and prod spaces still exist in the dev workspace, still work, and still read production data.
Until they are gone, people will keep using them and wonder why their changes never appear.

1. Confirm the new spaces answer correctly and the release pipeline is green.
2. Remove the old spaces' sharing first (keeps them recoverable while nobody can reach them).
3. Delete them once nobody has asked about them for a sensible period.

Do **not** delete the old bundle state folder in the dev workspace until the old spaces are gone —
it is what the bundle used to manage them.

---

## If a deployment goes wrong

Nothing here is destructive to dev, and the old QA and prod spaces are untouched until step 10. To back
out: restore the previous `host` and `warehouse_id` in `config/project.yml` and re-run the release. The
spaces created in the new workspaces stay behind; delete them by hand.

## Afterwards

- The three `host` values in `config/project.yml` are now genuinely different, so
  `check_access.py` guards something real: a wrong `DATABRICKS_HOST` in any environment is caught before
  a deploy.
- `set_catalog.sh` does nothing when the catalog is named the same in every workspace.
- `title_suffix` becomes optional — nothing can confuse two spaces in two different workspaces — though
  keeping `[QA]` is still helpful for anyone with access to several.
