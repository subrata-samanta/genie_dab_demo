# Genie space as code: dev → QA → prod, all through GitHub

This repository versions a Databricks **Genie space** and promotes it from dev to QA to prod with GitHub Actions
and Declarative Automation Bundles (`databricks bundle deploy`), following Databricks' recommended approach:
the `genie_spaces` bundle resource, one workspace and one service principal per environment with
passwordless login (workload identity federation), trunk-based `main`, benchmarks as the quality gate, and
approved, tagged releases to prod.

**The people who improve the space never touch git.** They edit the dev space in the Genie UI, as today.
Every hour a workflow exports the dev space and, when it changed, opens a pull request that lists the
changes in plain words. A reviewer merges it, and the pipeline does the rest.

```
 EDITORS (Genie UI)            GITHUB                                         DATABRICKS
 ──────────────────            ──────                                         ──────────
 edit the dev space  ─┐
                      │  2 · Sync (hourly, or "Run workflow")
                      └──────► pull request "Genie dev changes (n)"
                                 ├─ format checks · bundle validate
                                 └─ benchmarks on the dev space ───────────►  dev space (as edited)
                               reviewer merges
                                 │
                               3 · Release (on merge) ──► dev   deploy + smoke test ──►  dev space
                                 │                     └► QA    deploy + benchmark gate ►  QA space
                               3 · Release (Run workflow, target prod)
                                 └─► QA gate again ─► approval ─► prod deploy + smoke test ─► prod space
                                                                    └─► tag genie-prod-v<n>
```

| Workflow | When | What it does |
|---|---|---|
| **1 · Bootstrap** | once, by hand | exports the **existing** dev space, adopts it (same URL, same conversations), opens the pull request with its first version |
| **2 · Sync dev edits** | hourly, or *Run workflow* | exports the dev space; opens or updates the pull request `genie/dev-sync` with the changes; closes it if dev matches `main` again |
| **PR checks** | every pull request | format checks, `bundle validate`, and for the sync pull request the benchmarks on the dev space |
| **3 · Release** | on merge to `main`; *Run workflow* | dev (+ smoke test) → QA (+ benchmark gate); with target `prod`: QA gate → approval → prod (+ smoke test, tag) |

**Detailed documentation is in [`docs/`](docs/)**: the flow end to end, every workflow and
script, every setting, the permission model, and the operations runbook.

---

## For editors (no git needed)

1. Improve the **dev** space in the Genie UI: instructions, trusted example SQL, sample questions, and
   **benchmark questions** with their correct SQL (they are the QA exam; Databricks suggests 2–4 phrasings per question).
2. That's it. Within the hour a pull request *Genie dev changes* appears in GitHub listing what you changed.
   Keep editing: the same pull request is updated.
3. In a hurry? GitHub → **Actions → 2 · Sync dev edits into a pull request → Run workflow**.

Edit only the **dev** space. QA and prod are read-only for everyone; changes made there are refused or overwritten.

## For reviewers

The pull request shows each change in words (`[+]` added, `[-]` removed, `[~]` changed, with the exact change under
*Exact changes*) and its checks:

| Check | Meaning |
|---|---|
| **format** | the JSON is valid and formatted as Databricks exports it, ids are valid, tables use the dev catalog |
| **validate** | `databricks bundle validate` against dev |
| **dev benchmarks** | the benchmark questions, run on the dev space (which holds exactly this pull request); accuracy must reach the threshold (80% by default) |

- **Approve and merge** → dev is updated and QA is deployed and benchmark-tested.
- **Reject a change**: ask the editor to undo it in dev (the pull request closes itself when dev matches `main`
  again), or run **3 · Release** with target `dev` and **discard dev edits** (dev is reset to `main`).

## For the release manager

- **Promote to prod**: **Actions → 3 · Release → Run workflow**, branch `main`, target `prod`. The run re-tests QA,
  waits for your approval, deploys prod and smoke-tests it.
- If someone edited prod in the UI, the release **stops** and shows what the deploy would change. Re-make the
  change in dev, or rerun with **overwrite prod edits**.

### Versions

Every deployment tags the commit, so each environment's history is a list you can pick from:

```
genie-dev-v9     genie-qa-v9     genie-prod-v7      <- dev and QA hold v9, prod still serves v7
```

One number per version of the space, reused as that version promotes, so `v9` is the same content
everywhere. `genie-<env>-current` moves with each deploy and says what that environment runs right now;
the numbered tags never move and are the rollback points. Each run's summary prints the ladder.

The tag is written **straight after the deploy**, before the smoke test and the benchmark gate — it says
what the environment *is running*, not what passed. QA is deployed before its gate runs, so a failed gate
still leaves that version in QA and the tag has to say so. Quality is the run's status, and prod can only
ever receive a version that passed, because the prod job requires the QA gate to have succeeded.

### Going back to an earlier version

Three different actions, not one. All three are **Actions → 3 · Release → Run workflow** with
*Use workflow from* set to the tag you want.

| What you want | Target | Also |
|---|---|---|
| **Roll back prod** — restore service to a known-good version | `prod` | pick a `genie-prod-v*` tag: it passed the gate by definition. Needs the usual approval |
| **Reset dev to a known version** — undo an editor's mess | `dev` | pick a `genie-dev-v*` tag **and tick *discard dev edits***, or the guard keeps the newer live edits and will not deploy |
| Re-deploy QA | `qa` | not a rollback — see below |

**QA has no rollback of its own, on purpose.** It is overwritten by every release, and by every prod
action: promoting or rolling back prod deploys that version to QA on the way through. So QA follows
whatever you do elsewhere.

**A dev reset destroys work in progress.** *Discard dev edits* throws away whatever the editors have
changed in the Genie UI since the last sync — tell them first. The run prints exactly what it discarded,
so there is a record. Afterwards the next sync notices dev no longer matches `main` and opens a pull
request to bring `main` back in line: merge it if the reset is permanent, close it if it was temporary.

---

## Use this repository for another Genie space

> Full field-by-field checklist: **[docs/new-space-checklist.md](docs/new-space-checklist.md)**.

This repository is a template: **one repository per Genie space**. Everything specific to a space lives in
`config/project.yml`; the workflows, scripts and tests are identical in every copy, so improvements made here
can be copied forward without re-doing any configuration.

1. **Copy the repository** (GitHub → *Use this template*, or clone and push to a new remote). Do not copy
   `src/*.geniespace.json` — bootstrap writes it for the new space.
2. **Edit `config/project.yml`** — all of it, and nothing else:

  | Setting | What to put |
  |---|---|
  | `bundle.name` | a short unique name, e.g. `genie-finance-assistant`. Databricks records the adopted space under it, so **pick it once**: changing it later makes the bundle forget the space and try to create a new one |
  | `space_title` | the title shown in the Genie list (the `[DEV]` / `[QA]` suffix is added for you) |
  | `space_description` | one line, shown under the title |
  | `targets.<env>.warehouse_id` | the warehouse id **per environment** — ids are workspace-scoped, so each one differs |
  | `dev_catalog` | the catalog the dev space actually reads — must match what is inside the exported JSON |
  | `targets.*.catalog` | the catalog for dev, qa and prod |
  | `space_permissions` | the groups that can run, edit and manage the space. They must already exist in the workspace, and deploying sets **exactly** this list |
  | `deployment_root` | usually leave as is. Write access on it should belong only to the deploying service principal |

3. **Set up Databricks and GitHub** for the new space: [One-time setup](#one-time-setup-admin) below — a
   service principal, its grants, its row-filter group, and the three GitHub environments.
4. **Bootstrap**: Actions → **1 · Bootstrap** with the id of the dev space to adopt, then merge the pull
   request it opens. This is what writes `src/genie_space.geniespace.json`.
5. **Check it parses**, now that the space file exists:

   ```bash
   databricks bundle validate -t dev     # then -t qa and -t prod
   ```

   > Run this **after** bootstrap, not before. The resource points at
   > `src/genie_space.geniespace.json`, which only bootstrap creates, so on a fresh clone `bundle
   > validate` fails with *failed to read serialized genie space from file_path*. That is expected
   > before step 4 and means nothing is wrong.

### What you do not need to change

The environments are fixed at **dev → qa → prod**: the names appear in the workflow jobs and must match the
GitHub environment names. The resource key `genie_space` and the file name `src/genie_space.geniespace.json`
are conventions the scripts and `bundle generate --key genie_space` share — renaming either breaks the
bootstrap, the deploy guard and the tests.

### If the first bootstrap fails the format check

`data sources must use the dev catalog …` means `dev_catalog` in `config/project.yml` does not match the
catalog the new space reads. Set it to the catalog named in the error and re-run.

---

## One-time setup (admin)

### How the environments are separated

Each environment is its own **Databricks workspace**, pinned in `config/project.yml` as
`targets.<env>.workspace.host`.

That pin is **authoritative**. In CI it takes precedence over the environment's `DATABRICKS_HOST`, so a
mis-set GitHub variable cannot redirect a deploy into another environment's workspace — the bundle
decides where its own content goes. Locally, running against a profile for a different workspace is
refused outright:

```
Error: cannot resolve bundle auth configuration: the host in the profile (...)
       doesn't match the host configured in the bundle (...)
```

Set `DATABRICKS_HOST` per GitHub environment anyway: it is what the Databricks CLI authenticates with,
and the credentials must be valid in the pinned workspace. If they are not, the run fails to
authenticate — still better than deploying somewhere unintended.

With a workspace per environment the catalog may keep the **same name** in each, since the workspace
already separates them — `set_catalog.sh` then does nothing, and `title_suffix` is optional.

Already running all three in one workspace? **[docs/move-to-separate-workspaces.md](docs/move-to-separate-workspaces.md)**
is the migration runbook.

Sharing one workspace across all three also works: repeat the same host, give the catalogs different
names, and keep the `[DEV]` / `[QA]` suffixes so the spaces are distinguishable in one list. It is the
weaker isolation — one compromised principal reaches every environment's data — so prefer separate
workspaces where your organisation has them.

### 1. Databricks, per environment (dev, qa, prod)
1. **The data** the space reads exists in each environment's catalog (deploy it before the space: a space can't
   be deployed before its tables exist).
2. A **SQL warehouse**, with its id set for that environment in `config/project.yml`
   (`targets.<env>.variables.warehouse_id`). Ids are workspace-scoped, so each environment has its own.
3. A **service principal** for GitHub Actions, with a **GitHub federation policy** (workload identity federation)
   whose subject is `repo:<owner>/<repo>:environment:<dev|qa|prod>`. Give it workspace access,
   Databricks SQL access, `CAN USE` on the warehouse, and on that environment's catalog:

   ```sql
   GRANT `USE CATALOG`, `USE SCHEMA`, SELECT, EXECUTE ON CATALOG <catalog> TO `<application-id>`;
   ```

   `EXECUTE` matters: it covers the space's SQL functions *and* the functions that row filters call.
   **In dev also `CAN MANAGE` on the existing dev space** (so it can adopt and update it).
4. **Row filters and column masks**: a row filter removes rows instead of denying access, so a principal that
   is not in the group it admits gets a successful query, zero rows and no error anywhere. Check what is
   filtered and which groups pass, then add the service principal to one:

   ```sql
   SELECT table_schema, table_name, filter_name FROM <catalog>.information_schema.row_filters;
   SELECT routine_definition FROM <catalog>.information_schema.routines WHERE routine_name = '<filter function>';
   ```

   The function body shows which groups it admits, usually one broad group that sees everything and several
   narrow ones that each see a slice. Add the service principal to a group that admits **every** row; group
   membership is account-wide, so one covers all three environments. A slice-scoped group would make the
   benchmark gate fail, because the expected answers in the benchmarks are whole-business figures.
5. **Sharing is code**: `space_permissions` in `config/project.yml` is applied on every deployment and is
   **exact** — whatever is listed becomes the space's access, and anything granted by hand in the UI is
   removed. The groups must exist in the workspace first or the deployment fails. Workspace admins and the
   deploying service principal keep access regardless (inherited), and `mode: production` adds the deploying
   identity as `CAN_MANAGE`, so a deployment cannot lock everyone out. dev grants `CAN_EDIT` to the editors;
   qa and prod are `CAN_RUN` only, because the way to change them is to edit dev and promote.
6. **A deployment folder per environment**: `deployment_root` (default `/Workspace/Applications`) holds the
   bundle's record of the space. Restrict write access on it to the service principal that deploys that
   environment. It deliberately does not contain the deploying user's name — see *Why `root_path` has no
   user in it* below.

### 1a. Why `root_path` has no user in it, and what to do when you move it

The bundle keeps its record of the space under `workspace.root_path`. If that path contains
`${workspace.current_user.userName}`, the record lives in the *deploying identity's* home folder — so a
deploy by anyone else (a second service principal, or a person running `bundle deploy` by hand) finds no
record, concludes the space does not exist, and **creates a second one**, leaving the real space orphaned
with its conversations. `deployment_root` therefore names a fixed folder instead.

`scripts/deploy_guard.py` refuses any plan that would create a space when one with the same title already
exists, and prints the command below — so this fails loudly instead of silently duplicating.

**Whenever you change `deployment_root`, `bundle.name`, or the deploying service principal**, the bundle
loses its record and must be pointed back at the existing space, once per environment:

```bash
databricks bundle deployment bind genie_space <space-id> -t dev  --auto-approve
databricks bundle deployment bind genie_space <space-id> -t qa   --auto-approve
databricks bundle deployment bind genie_space <space-id> -t prod --auto-approve
```

Each `<space-id>` is the last part of that environment's space URL (`.../genie/rooms/<id>`); the guard's
error message also prints the right one. Run it as the identity that will deploy that environment.

### 1b. Check the access as the service principal, before the first deployment
Genie runs every question as the service principal, not as you, so checking as yourself proves nothing: a
question that works in the Genie UI can return zero rows in CI. Generate a short-lived secret for it
(Settings → Identity and access → Service principals → *Secrets*), then:

```bash
export DATABRICKS_HOST=https://<workspace>.cloud.databricks.com
export DATABRICKS_CLIENT_ID=<application-id>
export DATABRICKS_CLIENT_SECRET=<the secret>
export DATABRICKS_AUTH_TYPE=oauth-m2m
```

| Query, run as the service principal | Expected | If not |
|---|---|---|
| `SHOW TABLES IN <catalog>.<schema>` | every fact and dimension the space uses is listed | a missing table has no `SELECT`: step 1.3 |
| `SELECT count(*) FROM <catalog>.<schema>.<a fact table>` | a non-zero count | zero means a row filter excludes every row: step 1.4 |
| `SELECT MEASURE(<a measure>) FROM <catalog>.<schema>.<a metric view>` | a value, not `NULL` | as above |

Then the real thing — the same questions CI asks:

```bash
export GENIE_SPACE_ID=$(databricks bundle summary -t dev -o json | jq -r '.resources.genie_spaces.genie_space.id')
python tests/smoke_test.py
```

Delete the secret when you are done.

### 2. This repository
Edit **`config/project.yml`** — the only file with anything space-specific in it. See
[Use this repository for another Genie space](#use-this-repository-for-another-genie-space) for the full list.

### 3. GitHub settings
| Setting | Value |
|---|---|
| **Environments** `dev`, `qa`, `prod` (Settings → Environments; names exactly in lower case) | in **each**: `DATABRICKS_HOST` (workspace URL, e.g. `https://adb-123.azuredatabricks.net`) and `DATABRICKS_CLIENT_ID` (the service principal's application id). As *Environment variables* (or secrets: both work) |
| `prod` environment protection | **required reviewers**; deployment branches and tags: `main` and `genie-prod-v*` |
| `dev` / `qa` environment protection | if you restrict deployment branches, **allow the tags too** (`genie-dev-v*`, `genie-qa-v*`), or resetting dev to an earlier version is blocked before it starts |
| Optional secret `DATABRICKS_CLIENT_SECRET` per environment | only if you can't use workload identity federation yet: the workflows then use OAuth with this secret instead |
| Optional variable `ACCURACY_THRESHOLD` (repository or environment) | the benchmark gate's threshold, default `0.80` |
| Actions → General → *Allow GitHub Actions to create and approve pull requests* | on |
| Secret `GENIE_BOT_TOKEN` (recommended) | a GitHub App or bot token with *contents* and *pull requests* write. Without it the sync still opens pull requests, but GitHub does not run their checks (pull requests opened with the built-in token don't trigger workflows) |
| Branch protection on `main` | require a pull request with an approval, and the checks **format** and **validate** |

### 4. Adopt the existing dev space
**Actions → 1 · Bootstrap → Run workflow** with the dev space's id (the last part of its URL,
`.../genie/rooms/<id>`). Review and merge the pull request it opens. The release workflow then gives the dev space
this repository's title and creates QA. From here on, editors just edit dev.

---

## Troubleshooting

| Message in the workflow log | Cause | Fix |
|---|---|---|
| `Databricks settings missing for 'dev'` (or `github-oidc auth: missing Host`) | the GitHub environment has no `DATABRICKS_HOST` / `DATABRICKS_CLIENT_ID` | Settings → Environments → `dev` → add both; check the environment name is exactly `dev` |
| `github-oidc auth: …` with the host set, or `invalid_client` / `401` | the service principal has no federation policy for this repository and environment, or a wrong client id | add a GitHub federation policy with subject `repo:<owner>/<repo>:environment:<env>` (or set the `DATABRICKS_CLIENT_SECRET` secret instead) |
| `genie space with ID … not found` | wrong space id, or the service principal can't see the space | copy the id from the space's URL; give the dev service principal `CAN MANAGE` on it |
| `Not bootstrapped yet` | expected before the first bootstrap | run **1 · Bootstrap** |
| Smoke test: `(COMPLETED, 0 row(s))` while the same question works in the UI | a **row filter** excludes every row for the service principal — the query succeeds, so nothing reports an error | add it to the row filter's group (step 1.4). Confirm first: `MEASURE(...)` returns `NULL` for it and a number for you |
| `403 PERMISSION_DENIED` … `Failed to fetch tables for the agent` on `bundle deploy` | no catalog grants for the service principal in *that* environment (grants are per catalog; dev working says nothing about qa) | the `GRANT` in step 1.3, against the target's catalog |
| `net/url: invalid control character in URL` | a GitHub environment variable was saved with a trailing newline | re-enter `DATABRICKS_HOST` / `DATABRICKS_CLIENT_ID` for that environment. `scripts/check_settings.sh` now trims them and warns, but fix the value |
| `UNRESOLVED_ALL_IN_GROUP_BY`, with a one-line query in the message | usually a symptom, not the cause: Genie wrote ad-hoc SQL instead of reusing a trusted example | check the row filter and grants first; it clears up once the data is visible |
| `the plan would CREATE a space, but '…' already exists` | the bundle lost its record of the space: `deployment_root`, `bundle.name` or the deploying service principal changed | bind it back, once per environment — see [Why `root_path` has no user in it](#1a-why-root_path-has-no-user-in-it-and-what-to-do-when-you-move-it) |
| `check_access.py` reports `[EMPTY]` | the identity can read the table but sees no rows — almost always a row filter | step 1.4 |
| The `prod` job says *skipped* | working as designed: prod only runs from **Run workflow** with target `prod`, never from a push to main | Actions → **3 · Release** → Run workflow → *Deploy up to* `prod` |

## What happens when…

| Situation | What happens |
|---|---|
| An editor changes dev | the hourly sync opens or updates the pull request |
| Nothing changed | the sync does nothing (no new commits, no noise) |
| The changes are undone in dev | the sync closes the pull request |
| A change makes answers wrong | the pull request's **dev benchmarks** check fails; the reviewer doesn't merge |
| An editor keeps editing after a merge, while the release runs | the release **does not overwrite** dev (their newer edits are kept); they come in the next sync pull request. QA still gets the merged version |
| Someone edits QA in the UI | the next release overwrites it (and says so) |
| Someone edits prod in the UI | the prod release stops; rerun with *overwrite prod edits* after deciding |
| A release would delete or recreate a space | it stops: the space's URL and conversations would be lost |
| A bad version reached prod | run **3 · Release** from the previous `genie-prod-v*` tag — see [Going back to an earlier version](#going-back-to-an-earlier-version) |

## Files
```
config/project.yml                      EDIT PER SPACE: name, title, warehouse, catalogs
databricks.yml                          the promotion path dev / qa / prod (same for every space)
resources/genie_space.genie_space.yml   the Genie space resource, built from config/project.yml
src/genie_space.geniespace.json         the space's content (written by the workflows; created by bootstrap)
scripts/check_space.py                  format checks of the JSON
scripts/check_access.py                 can the deploying identity read the space's data? (runs before each deploy)
scripts/describe_changes.py             the plain-words change list in pull requests
scripts/deploy_guard.py                 reads `bundle plan`: keep / overwrite / refuse UI edits; refuses to duplicate a space
scripts/set_catalog.sh                  points the JSON at the qa / prod catalog (bundles don't resolve variables in it)
scripts/tag_release.sh                  tags what each environment now runs (genie-<env>-v<n>)
scripts/open_pr.sh                      commits an export and opens or updates its pull request
tests/smoke_test.py                     can the deployed space answer (SQL + rows)?
tests/benchmark_gate.py                 Genie benchmark evaluation with a threshold
.github/workflows/                      bootstrap, dev-sync, pr-checks, release
```

## Good to know
- **Who changed what**: Genie doesn't record which editor made an edit; the pull request shows *what* changed and
  when it was captured. Ask editors to mention their change in the pull request if you need attribution.
- **Edit the JSON by hand only with care**: the sync always exports dev, so a change made only in git and not in
  dev is undone by the next sync pull request (the reviewer would see it as [-]/[~]). Make changes in dev.
- **Benchmarks are the gate**: with no benchmark questions that have a SQL answer, the gate fails. Genie's answers
  vary a little between runs; set the threshold accordingly, and re-run a failed check once before investigating.
  The benchmark API is in Beta.
- **Catalogs**: the JSON names the dev catalog; `scripts/set_catalog.sh` swaps it for each target's catalog. If
  your environments differ in schema names too, extend that script.

## References
- Declarative Automation Bundles resources, `genie_spaces`: https://docs.databricks.com/aws/en/dev-tools/bundles/resources
- Official example: https://github.com/databricks/bundle-examples/tree/main/knowledge_base/genie_space_nyc_taxi
- CI/CD best practices: https://docs.databricks.com/dev-tools/ci-cd/best-practices
- GitHub Actions with workload identity federation: https://docs.databricks.com/dev-tools/ci-cd/github · example: https://docs.databricks.com/aws/en/dev-tools/databricks-apps/cicd-github-actions
- Genie benchmarks: https://docs.databricks.com/aws/en/genie/benchmarks
