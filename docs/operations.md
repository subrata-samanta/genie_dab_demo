# Operations

Day-to-day runbook. For why any of it works this way, see [architecture.md](architecture.md).

## Versions

Every deployment tags the commit. One number per version of the space, reused as it promotes:

```
genie-dev-v9     genie-qa-v9     genie-prod-v7
```

Read as: dev and QA hold v9, prod still serves v7 — so two versions are waiting to be promoted.

`genie-<env>-current` moves with each deploy and says what an environment runs *now*; the numbered tags
never move and are what you roll back to. Every run's summary prints the ladder.

The tag is written **straight after the deploy**, before the smoke test and the benchmark gate. It says
what the environment *is running*, not what passed — QA is deployed before its gate runs, so a failed
gate still leaves that version in QA and the tag has to say so. Quality is the run's status; prod can
only receive a version that passed, because its job requires the QA job to have succeeded.

## Promote to prod

**Actions → 3 · Release → Run workflow**, branch `main`, *Deploy up to* `prod`.

The run re-tests QA with that exact content, waits for an approver, deploys prod, tags it and smoke-tests
it. If someone edited the prod space in the UI, the release **stops** and shows what would change —
re-make the change in dev, or rerun with *overwrite prod edits*.

## Going back to an earlier version

Three different actions, not one. All are **Actions → 3 · Release → Run workflow** with *Use workflow
from* set to a tag.

| What you want | Target | Also |
|---|---|---|
| **Roll back prod** — restore service | `prod` | pick a `genie-prod-v*` tag: it passed the gate by definition. Needs the usual approval |
| **Reset dev** — undo an editor's mess | `dev` | pick a `genie-dev-v*` tag **and tick *discard dev edits*** |
| Re-deploy QA | `qa` | not a rollback — see below |

**QA has no rollback of its own, on purpose.** It is overwritten by every release *and* by every prod
action: promoting or rolling back prod deploys that version to QA on the way through, because the prod
job requires the qa job. QA follows whatever you do elsewhere.

**A dev reset destroys work in progress.** *Discard dev edits* throws away whatever the editors have
changed in the Genie UI since the last sync — tell them first. The run prints exactly what it discarded.
Afterwards the next sync notices dev no longer matches `main` and opens a pull request to bring `main`
back in line: merge it if the reset is permanent, close it if it was temporary.

Without *discard dev edits*, a dev rollback does nothing: the guard sees newer live edits and keeps them.

> If the `dev` or `qa` GitHub environment restricts deployment branches, allow the tag patterns too, or
> the job is blocked before it starts.

## Rejecting a change

If a reviewer does not want a change that is already in dev, there are two ways back:

- ask the editor to undo it in the Genie UI — the sync pull request closes itself once dev matches `main`
- or run **3 · Release** with target `dev` and *discard dev edits*, which resets dev to `main`

## Set up another Genie space

One repository per space. See [configuration.md](configuration.md).

1. Copy this repository. Do **not** copy `src/*.geniespace.json` — bootstrap writes it.
2. Edit `config/project.yml`: `bundle.name`, title, description, `warehouse_name`, `dev_catalog`, the
   per-target catalogs, and the `space_permissions` groups.
3. Set up Databricks and GitHub for it — see [access-and-identity.md](access-and-identity.md).
4. `databricks bundle validate -t dev`, then `-t qa` and `-t prod`.
5. **Actions → 1 · Bootstrap** with the id of the dev space to adopt, then merge the pull request.

## When the bundle loses track of a space

After intentionally changing `deployment_root`, `bundle.name`, or the deploying service principal, the
bundle has no record of the spaces and would create duplicates. `deploy_guard.py` stops the deploy and
prints the fix. Run it once per environment, as the identity that deploys that environment:

```bash
databricks bundle deployment bind genie_space <space-id> -t dev  --auto-approve
databricks bundle deployment bind genie_space <space-id> -t qa   --auto-approve
databricks bundle deployment bind genie_space <space-id> -t prod --auto-approve
```

`<space-id>` is the last part of the space's URL (`.../genie/rooms/<id>`); the guard's error message
prints the right one. Confirm with `databricks bundle plan -t <env>` — it should say `update`, never
`create`.

## Troubleshooting

| Message | Cause | Fix |
|---|---|---|
| `Databricks settings missing for 'dev'` | the GitHub environment has no `DATABRICKS_HOST` / `DATABRICKS_CLIENT_ID` | Settings → Environments → add both; the name must be exactly `dev` |
| `net/url: invalid control character in URL` | a variable was saved with a trailing newline | re-enter it. `check_settings.sh` trims and warns, but fix the value |
| `github-oidc auth: …`, or `invalid_client` / `401` | no federation policy for this repository and environment, or a wrong client id | add a policy with subject `repo:<owner>/<repo>:environment:<env>`, or set `DATABRICKS_CLIENT_SECRET` |
| `genie space with ID … not found` | wrong space id, or the principal cannot see it | copy the id from the URL; give the principal `CAN MANAGE` |
| `403 PERMISSION_DENIED` … `Failed to fetch tables for the agent` | no catalog grants **in that environment** | [access-and-identity.md](access-and-identity.md#1-catalog-grants) |
| Smoke test `COMPLETED, 0 row(s)` while the UI answers fine | a row filter excludes every row for the service principal | [access-and-identity.md](access-and-identity.md#2-membership-in-every-row-filter-group) |
| `check_access.py` reports `[EMPTY]` | same — readable but no rows | as above |
| `the plan would CREATE a space, but '…' already exists` | the bundle lost its record | bind it, above |
| `the space was edited in the UI` (prod) | someone edited prod directly | re-make it in dev, or rerun with *overwrite prod edits* |
| `data sources must use the dev catalog …` | `dev_catalog` does not match the exported JSON | set it in `config/project.yml` |
| `already exists on main: the space is already bootstrapped` | bootstrap is one-time, and this repo is already done | you want dev-sync for changes, or `bundle deployment bind` for re-linking |
| Benchmark gate fails | the change made answers worse, **or** the data changed underneath | read the per-question table in the run summary |
| The `prod` job says *skipped* | by design: prod only runs from *Run workflow* with target `prod` | run it that way |

## A failure mode nothing here catches

The pipeline versions the *space*, not the *data*. Genie's accuracy depends on the tables, the metric
views and the Unity Catalog comments it reads — and those live in a different repository. A metric view
change or a dropped column comment can degrade prod with no commit in this repository and no failing
check, because the benchmarks only run when something here changes.

Until a scheduled benchmark run against prod exists, this is the gap to watch.
