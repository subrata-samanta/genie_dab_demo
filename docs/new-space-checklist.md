# Setting up a new Genie space

## The short answer

**One file: `config/project.yml`.**

Nothing else in the repository changes. The workflows, scripts and tests are identical in every copy —
that is what makes this a template, and it means improvements made in one space can be copied forward
without redoing any configuration.

The work that actually takes time is outside the repository: the Databricks grants and the GitHub
environments. Budget your time accordingly.

---

## 1. Copy the repository

GitHub → **Use this template**, or clone and push to a new remote.

**Do not copy `src/genie_space.geniespace.json`.** Bootstrap writes it for the new space. If you bring
the old one along, the first format check fails on a catalog mismatch, and worse, a deploy could push the
old space's content into the new space.

Delete `src/*.geniespace.json` if your copy method brought it.

---

## 2. Edit `config/project.yml`

Every field, and what to put in it.

### `bundle.name`

```yaml
bundle:
  name: <short-unique-name>          # e.g. genie-supply-chain
```

A short unique name. It names the deployment folder and the record Databricks keeps of the adopted space.

> **Pick it once.** Changing it later makes the bundle forget which space it manages. The next deploy
> would try to create a second one — `deploy_guard.py` stops that, but you then have to
> `bundle deployment bind` every environment back.

### The space

```yaml
  space_title:
    default: "<Space Title>"                 # e.g. "Supply Chain Assistant"
  space_description:
    default: "<one line about what it answers>"
```

`space_title` is the name **without** the environment suffix — `[DEV]` and `[QA]` are appended
automatically, and prod gets none.

### The warehouse

```yaml
  warehouse_name:
    default: "<SQL warehouse name>"       # e.g. Serverless Starter Warehouse
```

A warehouse with this **name** must exist in every workspace you deploy to; it is looked up per
environment, so the id can differ. Use a **serverless** warehouse — Databricks recommends never Classic
or Pro for Genie.

Leave it as is if every environment already has a warehouse by that name.

### The catalogs

```yaml
  dev_catalog:
    default: <dev catalog>
targets:
  dev:
    variables:
      catalog: <dev catalog>
  qa:
    variables:
      catalog: <qa catalog>
  prod:
    variables:
      catalog: <prod catalog>
```

`dev_catalog` is load-bearing and easy to get wrong. It must match the catalog the **exported JSON
actually references**, because `set_catalog.sh` rewrites exactly that string when deploying to QA and
prod, and `check_space.py` rejects a space that references anything else.

You will usually not know it until after bootstrap. That is fine — see step 5.

### Who can use the space

```yaml
  space_permissions:
    default:                                      # qa and prod
      - level: CAN_MANAGE
        group_name: <release managers group>
      - level: CAN_RUN
        group_name: <readers group>
targets:
  dev:
    variables:
      space_permissions:                          # dev also lets the editors edit
        - level: CAN_MANAGE
          group_name: <release managers group>
        - level: CAN_EDIT
          group_name: <editors group>
        - level: CAN_RUN
          group_name: <readers group>
```

Three groups to replace. **They must already exist in the workspace** or the deployment fails.

Levels: `CAN_READ`, `CAN_RUN`, `CAN_EDIT`, `CAN_MANAGE`.

> Deploying sets **exactly** this list and removes anything granted by hand in the Genie UI. That is the
> point — access is reviewed in git. Nobody gets locked out: workspace admins and the deploying service
> principal keep access through inheritance, and `mode: production` adds the deploying identity as
> `CAN_MANAGE`.

### Leave these alone

```yaml
  deployment_root:
    default: /Workspace/Applications   # change only if your workspace has a convention
  title_suffix:                        # set per target, never by hand
  warehouse_id:                        # resolved from warehouse_name
```

If you do change `deployment_root`, restrict write access on it to the deploying service principal, and
remember it has the same "pick it once" consequence as `bundle.name`.

---

## 3. Do **not** edit these

| File | Why |
|---|---|
| `databricks.yml` | the promotion path; identical in every space |
| `resources/genie_space.genie_space.yml` | built from the variables above |
| `scripts/`, `tests/`, `.github/workflows/` | the pipeline, identical in every space |
| `src/genie_space.geniespace.json` | written by the workflows. A hand edit is rejected by the format check and would be overwritten by the next export anyway |

Three names are shared conventions — renaming any of them breaks bootstrap, the deploy guard and the
tests:

- the resource key `genie_space`
- the file name `src/genie_space.geniespace.json`
- the environment names `dev`, `qa`, `prod`, which must match the GitHub environment names

---

## 4. Outside the repository

This is the part that takes the time. Full detail in
[access-and-identity.md](access-and-identity.md); the checklist:

**Databricks, per environment:**

- [ ] the data exists in that environment's catalog (a space cannot deploy before its tables exist)
- [ ] a SQL warehouse named in `warehouse_name`
- [ ] a service principal, with `CAN USE` on the warehouse and these grants on the catalog:

  ```sql
  GRANT `USE CATALOG`, `USE SCHEMA`, SELECT, EXECUTE
    ON CATALOG <catalog>
    TO `<application-id>`;
  ```

- [ ] that principal added to any **row-filter group** — the silent failure: filtered rows produce a
      working pipeline and an empty answer
- [ ] `CAN MANAGE` on the dev space it will adopt
- [ ] the three permission groups exist

**GitHub:**

- [ ] environments `dev`, `qa`, `prod`, lower case, each with `DATABRICKS_HOST` and
      `DATABRICKS_CLIENT_ID` — **pasted with no trailing newline**
- [ ] `prod`: required reviewers; deployment branches and tags `main` and `genie-prod-v*`
- [ ] `dev` / `qa`: if you restrict deployment branches, allow `genie-dev-v*` / `genie-qa-v*` too, or
      resetting dev to an earlier version is blocked
- [ ] a federation policy per environment with subject `repo:<owner>/<repo>:environment:<env>` — it names
      the **repository**, so a new clone needs its own, or set `DATABRICKS_CLIENT_SECRET` instead
- [ ] branch protection on `main` requiring **format** and **validate**
- [ ] *Allow GitHub Actions to create and approve pull requests*
- [ ] `GENIE_BOT_TOKEN` (recommended — without it the sync's pull requests do not trigger their checks)

---

## 4a. Make sure the space has something to test with

**Nothing in this repository defines the test questions.** Both tests read the space itself, so a sparse
space produces a pipeline that passes without proving anything.

| Test | Where its questions come from |
|---|---|
| **Smoke test** | the space's **trusted example SQL** (first 3, skipping any with parameters); failing that, benchmark questions that have a SQL answer. Override with the `SMOKE_QUESTIONS` environment variable |
| **Benchmark gate** | the space's own **Benchmarks** tab, run by Databricks. Not read from this repository at all |

So before bootstrapping, the dev space should already have:

- [ ] **trusted example SQL** for the questions users really ask — these are both the smoke test's
      questions and, per Databricks, the strongest lever on answer quality
- [ ] **10–15 benchmark questions with a SQL answer**. Databricks suggests that many, and 80% accuracy
      before user acceptance testing — which is what `ACCURACY_THRESHOLD` defaults to

Without benchmarks the QA gate fails with *no benchmark could be graded automatically*, and the format
check warns about it. Without either, the smoke test fails with *there is nothing to ask* rather than
passing on an empty list.

Both are authored by the editors in the Genie UI. Bootstrap exports them; the hourly sync keeps them
current. Nothing to configure here.

## 5. Bootstrap, then validate — in that order

**Actions → 1 · Bootstrap**, with the id of the dev space to adopt (the last part of its URL,
`.../genie/rooms/<id>`). Merge the pull request it opens.

> `databricks bundle validate` **fails before bootstrap**, with
> *failed to read serialized genie space from file_path*. That is expected, not a misconfiguration: the
> resource points at a file only bootstrap creates. Validate afterwards.

If the bootstrap pull request fails the format check with

```
data sources must use the dev catalog 'sc_dev' ... found ['something_else']
```

then `dev_catalog` does not match the space. Set it to the catalog named in the error and re-run — this
is the normal way to discover the right value.

Then:

```bash
databricks bundle validate -t dev     # then -t qa and -t prod
```

---

## 6. Verify before trusting it

As the **service principal**, not as yourself — Genie answers as the identity that asks, so your own
access proves nothing:

```bash
export DATABRICKS_HOST=https://<workspace>.cloud.databricks.com
export DATABRICKS_CLIENT_ID=<application-id>
export DATABRICKS_CLIENT_SECRET=<a short-lived secret>
export DATABRICKS_AUTH_TYPE=oauth-m2m

python scripts/check_access.py --target dev
```

Expect every data source `[ok]`. An `[EMPTY]` means a row filter is hiding every row from the service
principal — fix that before going further, or the space will deploy and answer nothing.

Delete the secret when you are done.

---

## First-clone problems

| What you see | What it means |
|---|---|
| `failed to read serialized genie space from file_path` | you ran `bundle validate` before bootstrap — expected |
| `data sources must use the dev catalog …` | `dev_catalog` does not match the exported space |
| `already exists on main: the space is already bootstrapped` | bootstrap is one-time; this repo already has a space |
| `403 PERMISSION_DENIED … Failed to fetch tables for the agent` | no catalog grants for the principal in that environment |
| `net/url: invalid control character in URL` | a GitHub variable was saved with a trailing newline |
| Smoke test `COMPLETED, 0 row(s)` | a row filter excludes every row for the service principal |
| `SMOKE TEST FAILED: there is nothing to ask` | the space has no trusted example SQL and no benchmark with a SQL answer — add them in the Genie UI |
| `GATE FAILED: no benchmark could be graded automatically` | same cause: the space has no benchmark questions with an expected SQL answer |
| A group in `space_permissions` does not exist | create it, or remove it from the list |
