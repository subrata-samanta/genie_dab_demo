# How it works

## The problem this solves

A Genie space is configuration — data sources, instructions, trusted example SQL, benchmark questions —
that people edit in a web UI. Databricks keeps **no version history** of a space. There is no undo, no
record of who changed an instruction, and no way to test a change before the people relying on it see it.

So the space's content is kept in git instead, in one file, and Databricks is treated as a deployment
target rather than the source of truth. Everything here follows from that one decision.

The constraint that shapes the design: **the people who improve the space are analysts, not engineers.**
They will not use git. So the pipeline reads their work out of the dev space automatically and turns it
into a reviewable pull request.

## The one file that matters

```
src/genie_space.geniespace.json
```

This is the whole space: data sources, instructions, example SQL, SQL functions, sample questions and
benchmarks. Databricks writes it (`databricks bundle generate genie-space`) and reads it
(`databricks bundle deploy`). Nothing edits it by hand — the format checks reject a file that is not byte
identical to what `bundle generate` produces, because a hand-edit would be silently overwritten by the
next export.

Everything else in the repository exists to move that file safely between three environments.

## The flow

```
  EDITORS                     GITHUB                              DATABRICKS
  ───────                     ──────                              ──────────

  edit the dev space  ──────────────────────────────────────────►  dev space
  in the Genie UI                                                     │
                                                                      │ 2 · Sync, hourly
                                                                      │ exports it
                      ┌───────────────────────────────────────────────┘
                      ▼
            pull request "Genie dev changes (n)"
            branch genie/dev-sync, one commit
                      │
                      ├── format    check_space.py
                      ├── validate  bundle validate -t dev
                      └── dev benchmarks ──────────────────────►  dev space (as edited)
                      │
            reviewer merges to main
                      │
                      ▼
            3 · Release (automatic on merge)
                      │
                      ├─► dev   deploy ─► tag genie-dev-v9  ─► smoke test ──►  dev space
                      └─► QA    deploy ─► tag genie-qa-v9   ─► benchmark gate ►  QA space
                      │
            3 · Release (manual, target prod, approval)
                      │
                      └─► QA again ─► approval ─► deploy ─► tag genie-prod-v9 ─► smoke test ─► prod space
```

Note what is **not** automatic: nothing reaches prod without a human running the release workflow and a
second human approving it. Everything up to QA is automatic, because QA is where mistakes are supposed
to be found.

## The three environments

| | What it is | Who writes to it | Quality check |
|---|---|---|---|
| **dev** | the editors' working space, edited live in the UI | editors, continuously | smoke test |
| **QA** | a candidate, deployed from `main` | the pipeline only | benchmark gate (accuracy ≥ 80%) |
| **prod** | what the business uses | the pipeline, after approval | smoke test |

Each is its own **Databricks workspace**, pinned per target in `config/project.yml`
(`targets.<env>.workspace.host`) and supplied to CI as that GitHub environment's `DATABRICKS_HOST`. The
two must agree or the CLI refuses to run — which is what stops one environment's content reaching
another's workspace when credentials are wrong.

The catalog may then keep the **same name** in every workspace, since the workspace already separates
them. Where it does not — including when all three share one workspace — the exported JSON always names
the dev catalog, so `scripts/set_catalog.sh` rewrites it to the target's catalog in the throw-away CI
checkout before deploying. That rewrite is never committed, and it does nothing when the names match.

## Why each guard exists

Every guard in this pipeline was added because of a specific way it can go wrong. They are listed here
with the failure they prevent, because a guard whose purpose is forgotten gets deleted.

**`check_settings.sh` — the settings are usable.** A value pasted into GitHub with a trailing newline
reaches the CLI as `https://host\r\n` and fails with `net/url: invalid control character in URL` in
whatever step first calls the CLI, far from the cause. It trims and warns.

**`check_access.py` — the identity can read the data.** Genie answers every question as the service
principal, not as the person who wrote the question, and it refuses to create a space whose tables the
agent cannot read. Checking here names the missing grant instead of letting it surface as a 403 at deploy
time, or — worse — as an empty answer.

**`deploy_guard.py` — the deployment will not destroy anything.** Three separate dangers:

- *Someone edited the space in the UI.* In dev those edits are the editors' work: the deploy is skipped
  so the next sync can bring them into git. In QA they are overwritten. In prod the release stops.
- *The plan would delete or recreate the space.* Its URL and every saved conversation would be lost.
- *The plan would create a space that already exists.* This is what a moved deployment folder or a new
  service principal looks like, and deploying would leave a duplicate space and orphan the real one.

**The benchmark gate — the answers are still right.** A change that looks sensible in a diff can make
Genie answer worse. The gate runs the space's own benchmark questions and fails below 80% accuracy, the
level Databricks suggests before user acceptance testing.

**The smoke test — the space can answer at all.** Cheaper than the gate and catches the dead-on-arrival
cases: missing tables, missing grants, a row filter that hides every row.

## Where the state lives

Three separate things remember what is deployed, and confusing them causes real damage:

| | Where | What it holds |
|---|---|---|
| The content | `src/genie_space.geniespace.json` on `main` | what the space *should* be |
| The bundle's record | `/Workspace/Applications/<bundle.name>/<target>` | which Databricks space this resource is, and what was last deployed |
| The version history | git tags `genie-<env>-v<n>` | what each environment is running, and what you can go back to |

The middle one is the subtle one. If the bundle loses its record — a changed `deployment_root`, a renamed
bundle, a different service principal — it concludes the space does not exist and creates a second one.
That is why `root_path` deliberately contains no user name, and why `deploy_guard.py` refuses to create a
space whose title already exists.

## Further reading

- [workflows-and-scripts.md](workflows-and-scripts.md) — what every workflow and script does
- [configuration.md](configuration.md) — every setting, and which file it lives in
- [access-and-identity.md](access-and-identity.md) — the permission model
- [operations.md](operations.md) — promoting, rolling back, resetting dev, troubleshooting
