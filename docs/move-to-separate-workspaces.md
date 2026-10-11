# Moving QA and prod into their own workspaces

A migration runbook: today all three environments deploy into one workspace; this moves QA into a QA
workspace and prod into a prod workspace. Every step that has SQL has it here. Do one environment at a
time, QA first.

## Read this before you start

**A Genie space cannot be moved between workspaces.** Space ids are workspace-scoped, so the QA and prod
spaces in the new workspaces are *new spaces*: new URLs, and **no conversation history**. The content is
identical because it comes from git, but anyone who bookmarked the old prod space needs the new link.
Plan the announcement before you deploy, not after.

Dev is unaffected. Leave it where it is until QA and prod are proven.

Not everything here is SQL. Workspaces and account groups are created in the **account console**, catalog
bindings use the **CLI**, and the Genie spaces themselves are managed by the **pipeline**. Each step says
which.

---

## Step 0 — Discovery: write down what you have

Run in the **current** workspace. These queries produce the values every later step needs, so you do not
have to guess them.

```sql
-- Which metastore, and therefore whether the new workspaces can reach this data at all
SELECT current_metastore();

-- The catalogs this space reads
SHOW CATALOGS;

-- Which tables carry a row filter, and the function that guards them
SELECT table_schema, table_name, filter_name
FROM   <catalog>.information_schema.row_filters;

-- The groups that function admits - you must reproduce these in the new workspaces
SELECT routine_definition
FROM   <catalog>.information_schema.routines
WHERE  routine_name = '<filter function from the query above>';

-- What the CI principal is granted today, to reproduce it
SELECT grantee, privilege_type
FROM   <catalog>.information_schema.catalog_privileges
WHERE  catalog_name = '<catalog>';
```

Record: the metastore id, the catalog per environment, the row-filter function and the groups it admits,
and the privilege list for the CI principal.

### The decision this makes for you

`current_metastore()` returns something like `aws:us-west-2:<id>`. A metastore is per-region and can be
attached to many workspaces.

- **New workspaces on the same metastore** — the catalogs already exist and are reachable. No data to
  move. Simpler path.
- **A different metastore** — the data must be created there first, in a catalog with the name
  `config/project.yml` expects. A Genie space cannot deploy before its tables exist.

---

## Step 1 — Create the workspaces

**Account console.** No SQL. Create the QA and prod workspaces and attach each to a metastore. Note each
workspace URL and workspace id — you need the URL in `config/project.yml` and in GitHub, and the id for
catalog bindings in step 4.

---

## Step 2 — Groups: the step that silently breaks everything

**Account console → User management → Groups.** No SQL to create them; SQL to verify.

Check what you have now, in the current workspace:

```sql
SELECT is_account_group_member('<row-filter group>') AS account_group,
       is_member('<row-filter group>')               AS workspace_group;
```

If that returns `account_group = false, workspace_group = true`, the group is **workspace-local** — it
exists only in this workspace. That is the case in this deployment today, for all five groups the
repository depends on.

A workspace-local group does not exist in another workspace, and two things break there:

| | What happens |
|---|---|
| `space_permissions` | the deployment **fails**: the groups named in `config/project.yml` are not there |
| The row filter | **silently returns nothing.** The filter admits `is_account_group_member(g) OR is_member(g)`. The workspace-local group is absent so `is_member` is false, and `is_account_group_member` is false because it was never an account group. Every query succeeds and returns zero rows |

The second is the failure mode that cost this project the most time: a green pipeline that answers
nothing.

**Do:** recreate each group as an **account group** and assign it to the dev, QA and prod workspaces.
Keep the names identical — the row-filter function and `config/project.yml` both match on name. Then
re-run the query above **in each workspace, as that workspace's CI principal**:

```sql
SELECT current_user() AS whoami,
       is_account_group_member('<row-filter group>') AS account_group;
```

`account_group` must be `true` before you go further.

---

## Step 3 — Per workspace: principal, warehouse, grants

In **each** new workspace.

**Account console / workspace admin — no SQL:** create the CI service principal, give it workspace and
Databricks SQL access, create a **serverless** SQL warehouse, and grant the principal `CAN USE` on it.

Note the warehouse **id** — `/sql/warehouses/<id>` in the URL, or:

```bash
databricks warehouses list --profile <new workspace profile>
```

**SQL — the catalog grants**, run as a workspace admin in the new workspace:

```sql
GRANT `USE CATALOG`, `USE SCHEMA`, SELECT, EXECUTE
  ON CATALOG <catalog>
  TO `<application-id>`;
```

`EXECUTE` is not optional: it covers the space's SQL functions *and* the function the row filter calls.

**SQL — verify it took:**

```sql
SELECT grantee, privilege_type
FROM   <catalog>.information_schema.catalog_privileges
WHERE  catalog_name = '<catalog>'
  AND  grantee = '<application-id>';
```

Expect four rows: `USE_CATALOG`, `USE_SCHEMA`, `SELECT`, `EXECUTE`.

**SQL — confirm the row filter now admits this principal.** Run **as the principal**:

```sql
SELECT is_account_group_member('<row-filter group>');   -- must be true
SELECT count(*) FROM <catalog>.<schema>.<a filtered fact table>;   -- must be non-zero
```

A non-zero count here is what proves step 2 actually worked.

**Deployment folder — no SQL:** create `/Workspace/Applications/<bundle.name>/<target>` and restrict
write access to that principal.

---

## Step 4 — Optional: isolate the catalogs

**CLI, not SQL** — there is no `ALTER CATALOG … ISOLATION MODE` statement.

Catalogs are `OPEN` by default, meaning every workspace on the metastore can read them — including
production data from the dev workspace. Now that the workspaces are separate, binding each catalog to
its own workspace is what actually delivers the isolation you are doing this for.

```bash
# 1. stop the catalog being readable from every workspace
databricks catalogs update <catalog> --isolation-mode ISOLATED --profile <admin profile>

# 2. bind it to the workspace that should have it
databricks workspace-bindings update-bindings catalog <catalog> \
  --json '{"add":[{"workspace_id":<workspace id>,"binding_type":"BINDING_TYPE_READ_WRITE"}]}' \
  --profile <admin profile>

# 3. check
databricks workspace-bindings get-bindings catalog <catalog> --profile <admin profile>
```

Do this **after** the deployments work, so a binding mistake and a deployment mistake cannot be confused.

---

## Step 5 — GitHub environments

**GitHub settings.** No SQL. For `qa`, then `prod`:

- `DATABRICKS_HOST` — the new workspace URL, **no trailing newline, no trailing slash**
- `DATABRICKS_CLIENT_ID` — that workspace's service principal
- `DATABRICKS_CLIENT_SECRET`, or a federation policy with subject
  `repo:<owner>/<repo>:environment:<env>`

---

## Step 6 — Point the repository at the new workspace

In `config/project.yml`, for the target you are migrating:

```yaml
  qa:
    workspace:
      host: https://<qa workspace>.cloud.databricks.com
    variables:
      warehouse_id: "<qa warehouse id>"
      catalog: <qa catalog>
      title_suffix: " [QA]"
```

Both values change: the **host**, and the **warehouse id** — ids are workspace-scoped, so the old one
means nothing in the new workspace. If the catalog is named the same there, delete the `catalog:` line
and it inherits `dev_catalog`.

```bash
databricks bundle validate -t qa
```

---

## Step 7 — Verify as the service principal, before deploying

This is the step that catches every mistake above. Run it before any deployment.

```bash
export DATABRICKS_HOST=https://<qa workspace>.cloud.databricks.com
export DATABRICKS_CLIENT_ID=<qa application id>
export DATABRICKS_CLIENT_SECRET=<a short-lived secret>
export DATABRICKS_AUTH_TYPE=oauth-m2m

python scripts/check_access.py --target qa
```

| What it reports | What it means |
|---|---|
| refuses, printing two hosts | `DATABRICKS_HOST` and `config/project.yml` disagree — fix step 5 or 6 |
| a data source as an **error** | the grants in step 3 are missing or incomplete |
| a data source as **`[EMPTY]`** | readable but no rows: **step 2 is not done**. A deployment would succeed and answer nothing |
| every source `[ok]`, `Access OK for qa.` | proceed |

The same checks by hand, run as the principal in the new workspace:

```sql
SELECT current_user(), current_metastore();
SELECT is_account_group_member('<row-filter group>');          -- true
SHOW TABLES IN <catalog>.<schema>;                             -- every table the space uses
SELECT count(*) FROM <catalog>.<schema>.<a fact table>;        -- non-zero
SELECT MEASURE(<a measure>) FROM <catalog>.<schema>.<a metric view>;   -- not NULL
```

---

## Step 8 — Deploy QA

**Actions → 3 · Release → Run workflow**, target `qa`. No SQL.

The bundle has no record of a space in the new workspace, so the plan says **create** — correct here.
`deploy_guard.py` checks the new workspace for a space with the same title, finds none, and allows it.

> Stopped with *the plan would CREATE a space, but '…' already exists*? You are pointed at a workspace
> that already has that space — almost certainly the old one. Re-check step 6.

Then confirm the QA benchmark gate passes and the new space answers in the Genie UI.

---

## Step 9 — Repeat for prod

Steps 3, 5, 6, 7, then **Run workflow, target `prod`** — which re-runs the QA gate and waits for
approval. Afterwards, send the new prod space URL to its users.

---

## Step 10 — Retire the old spaces

No SQL — Genie UI. The old QA and prod spaces still exist in the dev workspace, still work, and still
read production data. Until they are gone, people keep using them and wonder why their changes never
appear.

1. Confirm the new spaces answer correctly and the pipeline is green.
2. Remove the old spaces' sharing first — unreachable, still recoverable.
3. Delete them once nobody has asked about them for a sensible period.

Do **not** delete the old bundle state folder in the dev workspace until the old spaces are gone; it is
what the bundle used to manage them.

---

## If a deployment goes wrong

Nothing here touches dev, and the old QA and prod spaces are untouched until step 10. To back out:
restore the previous `host` and `warehouse_id` in `config/project.yml` and re-run the release. Spaces
created in the new workspaces stay behind; delete them by hand.

## Afterwards

- The three `host` values are now genuinely different, so `check_access.py` guards something real: a
  wrong `DATABRICKS_HOST` in any environment is caught before a deploy.
- `set_catalog.sh` does nothing when the catalog is named the same in every workspace.
- `title_suffix` becomes optional — nothing can confuse two spaces in two different workspaces — though
  `[QA]` still helps anyone with access to several.
