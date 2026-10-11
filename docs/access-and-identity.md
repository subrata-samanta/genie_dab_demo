# Access and identity

> The single most important fact in this document:
> **Genie answers every question as the identity that asks it.**
> In CI that is the service principal, not you. Your own access proves nothing about whether the
> deployed space will work — a question that answers perfectly in the Genie UI can return zero rows in
> the pipeline.

Every access failure this project has hit came from that one gap. They are listed at the end with the
symptom each one produces.

## The four gates

A deployment needs all four to be true, **in each environment separately**. Grants in dev say nothing
about QA.

### 1. Catalog grants

Genie refuses to *create* a space whose tables the agent cannot read, so this fails at `bundle deploy`,
before any question is asked.

```sql
GRANT `USE CATALOG`, `USE SCHEMA`, SELECT, EXECUTE
  ON CATALOG <catalog>
  TO `<application-id>`;
```

Catalog level inherits to every schema and table. `EXECUTE` is not optional: it covers the space's SQL
functions *and* the functions that row filters call.

### 2. Membership in every row-filter group

**The silent one.** A row filter *removes rows*; it does not deny access. The identity passes every
permission check, the query succeeds, and the answer is empty. Nothing in any log mentions a row filter.

Find what is filtered and which groups are admitted:

```sql
SELECT table_schema, table_name, filter_name
FROM   <catalog>.information_schema.row_filters;

SELECT routine_definition
FROM   <catalog>.information_schema.routines
WHERE  routine_name = '<the filter function>';
```

The function body shows which groups it admits — typically one broad group that sees everything and
several narrow ones that each see a slice. **Add the service principal to a group that admits every
row.** Group membership is account-wide, so one membership covers all three environments.

A narrow, slice-scoped group would make the benchmark gate fail: the expected answers in the benchmarks
are whole-business figures, and a principal that sees one slice computes different numbers.

### 3. Warehouse and space permissions

- `CAN USE` on the SQL warehouse named in `config/project.yml`
- `CAN MANAGE` on the Genie space, or on the folder it lives in. An adopted space needs this explicitly;
  a space the bundle creates inherits it

### 4. Clean GitHub settings

`DATABRICKS_HOST` and `DATABRICKS_CLIENT_ID` per environment, with **no trailing newline**. With
workload identity federation instead of a secret, the principal also needs a policy whose subject is
`repo:<owner>/<repo>:environment:<env>` — note that it names the **repository**, so every cloned repo
needs its own policies.

## Verify before you deploy

Checking as yourself proves nothing. Generate a short-lived secret for the service principal
(Settings → Identity and access → Service principals → *Secrets*), then:

```bash
export DATABRICKS_HOST=https://<workspace>.cloud.databricks.com
export DATABRICKS_CLIENT_ID=<application-id>
export DATABRICKS_CLIENT_SECRET=<the secret>
export DATABRICKS_AUTH_TYPE=oauth-m2m

python scripts/check_access.py --target dev
```

That is the same check the pipeline runs before every deploy. Delete the secret afterwards.

The decisive manual query, if you want to confirm by hand. Run it as yourself and as the service
principal: rows for you and nothing for it means a row filter, every time.

```sql
SELECT count(*) FROM <catalog>.<schema>.<a fact table>;

-- a metric view has to be read through MEASURE()
SELECT MEASURE(<a measure>) FROM <catalog>.<schema>.<a metric view>;
```

## The deployment folder

`root_path` deliberately contains no user name:

```yaml
root_path: ${var.deployment_root}/${bundle.name}/${bundle.target}
```

If it were `/Workspace/Users/${workspace.current_user.userName}/...`, the bundle's record of the space
would live in the *deploying identity's* home folder. A deploy by anyone else — a second service
principal, or a person running `bundle deploy` by hand — would find no record, conclude the space does
not exist, and **create a second one**, leaving the real space orphaned with its conversations.

Restrict write access on `deployment_root` to the service principal that deploys that environment.

`deploy_guard.py` is the backstop: it refuses any plan that would create a space whose title already
exists, and prints the `bundle deployment bind` command to adopt the real one instead. When you
intentionally change `deployment_root`, `bundle.name`, or the deploying principal, run that bind once per
environment.

## One service principal per environment

Databricks recommends a separate principal per environment, and separating the identity that *deploys*
from the identity that *runs*. A single principal across all three means the dev pipeline — which runs on
every merge, with no approval — holds production data access.

`check_access.py` warns when qa or prod is deployed by a person rather than a service principal. It
distinguishes them by how they authenticate: a service principal's user name is its application id (a
UUID), a person's is an email address.

## Access to the space itself

Managed as code, in `config/project.yml` → `space_permissions`. Deploying sets **exactly** that list and
removes anything granted by hand. See [configuration.md](configuration.md#access).

## Symptoms and their causes

Every row is a failure this pipeline actually hit. The pattern worth internalising: **none of the error
messages named the real cause.**

| What you see | What it actually is | Gate |
|---|---|---|
| Smoke test: `COMPLETED, 0 row(s)`, and Genie's SQL is correct | a row filter excludes every row for this identity. The query *succeeds*, so nothing reports an error | 2 |
| `403 PERMISSION_DENIED` … `Failed to fetch tables for the agent` at deploy | no catalog grants in **that** environment | 1 |
| `net/url: invalid control character in URL` | trailing newline in a GitHub environment variable | 4 |
| `UNRESOLVED_ALL_IN_GROUP_BY` with a one-line query in the message | usually a symptom, not a cause: Genie wrote ad-hoc SQL instead of reusing a trusted example. Check the row filter and grants first | — |
| `check_access.py` reports `[EMPTY]` | readable but no rows — almost always a row filter | 2 |
| The plan would `CREATE` a space that already exists | the bundle lost its record: `deployment_root`, `bundle.name` or the principal changed | — |
