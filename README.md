# Genie space as code: dev → QA → prod, all through GitHub

This repository versions a Databricks **Genie space** and promotes it from dev to QA to prod with GitHub Actions
and Declarative Automation Bundles (`databricks bundle deploy`), following Databricks' recommended approach:
the `genie_spaces` bundle resource, separate workspaces, one service principal per environment with
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
                                 └─► QA gate again ─► ⏸ approval ─► prod deploy + smoke test ─► prod space
                                                                    └─► tag genie-prod-<time>
```

| Workflow | When | What it does |
|---|---|---|
| **1 · Bootstrap** | once, by hand | exports the **existing** dev space, adopts it (same URL, same conversations), opens the pull request with its first version |
| **2 · Sync dev edits** | hourly, or *Run workflow* | exports the dev space; opens or updates the pull request `genie/dev-sync` with the changes; closes it if dev matches `main` again |
| **PR checks** | every pull request | format checks, `bundle validate`, and for the sync pull request the benchmarks on the dev space |
| **3 · Release** | on merge to `main`; *Run workflow* | dev (+ smoke test) → QA (+ benchmark gate); with target `prod`: QA gate → approval → prod (+ smoke test, tag) |

---

## For editors (no git needed)

1. Improve the **dev** space in the Genie UI: instructions, trusted example SQL, sample questions, and
   **benchmark questions** with their correct SQL (they are the QA exam; Databricks suggests 2–4 phrasings per question).
2. That's it. Within the hour a pull request *Genie dev changes* appears in GitHub listing what you changed.
   Keep editing: the same pull request is updated.
3. In a hurry? GitHub → **Actions → 2 · Sync dev edits into a pull request → Run workflow**.

Edit only the **dev** space. QA and prod are read-only for everyone; changes made there are refused or overwritten.

## For reviewers

The pull request shows each change in words (➕ added, ➖ removed, ✏️ changed, with the exact change under
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
  waits for your approval, deploys prod, smoke-tests it and tags the commit `genie-prod-<time>`.
- **Roll back**: the same, but *Use workflow from* an earlier `genie-prod-*` **tag**. Prod gets that version
  (same space, same URL).
- If someone edited prod in the UI, the release **stops** and shows what the deploy would change. Re-make the
  change in dev, or rerun with **overwrite prod edits**.

---

## One-time setup (admin)

### 1. Databricks, per environment (dev, qa, prod)
1. **The data** the space reads exists in each environment's catalog (deploy it before the space: a space can't
   be deployed before its tables exist).
2. A **SQL warehouse** with the name in `databricks.yml` (`lookup: warehouse:`).
3. A **service principal** for GitHub Actions, with a **GitHub federation policy** (workload identity federation)
   whose subject is `repo:subrata-samanta/genie_dab_demo:environment:<dev|qa|prod>`. Give it: workspace access,
   Databricks SQL access, `CAN USE` on the warehouse, and `USE CATALOG` / `USE SCHEMA` / `SELECT` on that
   environment's catalog (the smoke test and the benchmarks run queries as it).
   **In dev also `CAN MANAGE` on the existing dev space** (so it can adopt and update it).
4. **Sharing**: the bundle does not manage who can use the spaces (no `permissions:` in
   `resources/genie_space.genie_space.yml` for now). The dev space keeps its sharing. QA and prod are created
   by the service principal, so share them once by hand (Share → *Can run* for users, who also need `SELECT`
   on the data). To manage access as code later, see the comment in that file.

### 2. This repository
Edit `databricks.yml`: `dev_catalog` and each target's `catalog`, and the warehouse name. The title and
description are in `resources/genie_space.genie_space.yml`.

### 3. GitHub settings
| Setting | Value |
|---|---|
| **Environments** `dev`, `qa`, `prod` (Settings → Environments; names exactly in lower case) | in **each**: `DATABRICKS_HOST` (workspace URL, e.g. `https://adb-123.azuredatabricks.net`) and `DATABRICKS_CLIENT_ID` (the service principal's application id). As *Environment variables* (or secrets: both work) |
| `prod` environment protection | **required reviewers**; deployment branches and tags: `main` and `genie-prod-*` |
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
| A bad version reached prod | run **3 · Release** from the previous `genie-prod-*` tag |

## Files
```
databricks.yml                          bundle, variables, targets dev / qa / prod
resources/genie_space.genie_space.yml   the Genie space resource: title, warehouse, file_path
src/genie_space.geniespace.json         the space's content (written by the workflows; created by bootstrap)
scripts/check_space.py                  format checks of the JSON
scripts/describe_changes.py             the plain-words change list in pull requests
scripts/deploy_guard.py                 reads `bundle plan`: keep / overwrite / refuse UI edits before deploying
scripts/set_catalog.sh                  points the JSON at the qa / prod catalog (bundles don't resolve variables in it)
scripts/open_pr.sh                      commits an export and opens or updates its pull request
tests/smoke_test.py                     can the deployed space answer (SQL + rows)?
tests/benchmark_gate.py                 Genie benchmark evaluation with a threshold
.github/workflows/                      bootstrap, dev-sync, pr-checks, release
```

## Good to know
- **Who changed what**: Genie doesn't record which editor made an edit; the pull request shows *what* changed and
  when it was captured. Ask editors to mention their change in the pull request if you need attribution.
- **Edit the JSON by hand only with care**: the sync always exports dev, so a change made only in git and not in
  dev is undone by the next sync pull request (the reviewer would see it as ➖/✏️). Make changes in dev.
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
