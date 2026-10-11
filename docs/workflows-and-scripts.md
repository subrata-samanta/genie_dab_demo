# Workflows and scripts

Every workflow and every script, what it does, and where it is called from. Read
[architecture.md](architecture.md) first for the shape of the whole thing.

---

# Workflows

## 1 · Bootstrap (`.github/workflows/bootstrap.yml`)

**Run once per repository, by hand.** Puts an existing dev Genie space under version control without
losing it: the space keeps its URL, its id and its saved conversations.

Input: `space_id`, the last part of the space's URL (`.../genie/rooms/<id>`).

1. **Refuses to run twice.** If `src/genie_space.geniespace.json` already exists on `main`, it stops. A
   second run would overwrite the version history of the space content with a fresh export.
2. **Exports the space.** `bundle generate genie-space --existing-id <id> --key genie_space`. This also
   writes a resource YAML, which the step moves aside and restores, so the repository keeps its own
   variable-driven `resources/genie_space.genie_space.yml`.
3. **Adopts it.** `bundle deployment bind genie_space <id> -t dev` tells the bundle this existing space
   is the resource, so later deploys update it instead of creating a new one.
4. **Opens a pull request** with the first version.

## 2 · Sync dev edits (`.github/workflows/dev-sync.yml`)

**Hourly, and on demand.** This is what makes the whole thing work for non-git users.

1. Exports the live dev space over `src/genie_space.geniespace.json`.
2. Compares it with what is on `main`, **ignoring list order** — Databricks does not guarantee the order
   of its exported lists, so a plain `git diff` would report changes that are not changes.
3. If the content is the same, discards the export and does nothing. No commit, no pull request, no noise.
4. If it differs, writes the change list in plain words and opens or updates the pull request on branch
   `genie/dev-sync`.

The branch always holds exactly **one commit**, force-pushed. So the pull request always shows
`main` → *the live dev space*, never a history of intermediate saves. Editors keep editing; the same pull
request keeps updating.

If the editors undo their changes, the next run finds dev matching `main` again and closes the pull
request on its own.

## PR checks (`.github/workflows/pr-checks.yml`)

Runs on every pull request into `main`.

| Job | What it checks |
|---|---|
| **format** | `check_space.py` — the JSON is valid, ids are well formed, catalogs are right, and the file is formatted exactly as `bundle generate` writes it. Also posts the plain-words change list to the run summary |
| **validate** | `databricks bundle validate -t dev` |
| **dev benchmarks** | only for the `genie/dev-sync` pull request: runs the benchmark questions against the dev space |

The third job deserves explanation. The dev space *is* the pull request — it holds exactly the content
being proposed. So the benchmarks can be run against the real thing before merging, which is why
`deploy_guard.py --live-matches` runs first: if an editor changed dev again since the export, the live
space no longer matches the pull request and the benchmark result would be meaningless, so it is skipped.

Make **format** and **validate** required checks in branch protection.

## 3 · Release (`.github/workflows/release.yml`)

| Trigger | What runs |
|---|---|
| push to `main` | check → dev → QA |
| *Run workflow*, target `dev` | check → dev |
| *Run workflow*, target `qa` | check → QA |
| *Run workflow*, target `prod` | check → QA → [approval] approval → prod |

Prod is never reached by a push — its job requires `github.event_name == 'workflow_dispatch'` and
`inputs.target == 'prod'`. And it requires the QA job to have succeeded **in the same run**, so prod
always receives a version that passed the gate against that exact content.

Each environment job runs the same sequence:

```
check_settings.sh        the Databricks settings are present and clean
set_catalog.sh <env>     (QA and prod only) point the JSON at this environment's catalog
check_access.py          this identity can read the data
bundle plan + deploy_guard.py   it is safe to deploy
deploy.sh <env>          deploy
tag_release.sh <env>     record what this environment now runs
smoke test / benchmark gate     does it work?
```

The UI-edit policy differs per environment: dev **keeps** them (they are the editors' work, and the next
sync collects them), QA **overwrites**, prod **refuses** unless you rerun with *overwrite prod edits*.

---

# Scripts

## `scripts/check_settings.sh`

Called first in every job that talks to Databricks.

Trims stray whitespace and newlines from `DATABRICKS_HOST`, `DATABRICKS_CLIENT_ID` and
`DATABRICKS_CLIENT_SECRET`, re-exports the clean values for later steps, and warns which one was dirty.
Then fails with an explicit message if the host or client id is missing, and reports which login method
is in use.

Why: a value pasted into GitHub with a trailing newline reaches the CLI as `https://host\r\n` and fails
with `net/url: invalid control character in URL`, in whatever step first calls the CLI.

> The trimmed value is re-exported through `$GITHUB_ENV`. If the same variable is also declared in the
> job's `env:` block, GitHub may re-apply the original for each step — so **fix the value in GitHub**
> rather than relying on the trim. The warning names the variable.

## `scripts/check_access.py`

```
python scripts/check_access.py --target <dev|qa|prod>
```

Checks that the identity the job runs as can actually use the space's data, before deploying.

- Prints the identity and whether it is a **service principal** or a **user** — a service principal
  authenticates as its application id (a UUID), a person as an email address. Warns if qa or prod is
  being deployed by a person.
- Checks the warehouse id set for that target (`targets.<env>.variables.warehouse_id`) exists in this
  workspace and is usable by this identity. Ids are workspace-scoped, so this catches one copied from
  the wrong environment.
- Reads every data source listed in the space JSON. A failure is an **error** (missing `SELECT`,
  `USE CATALOG`). A table that is readable but returns **no rows** is a **warning**: that is what a row
  filter looks like, and it is the one failure mode that otherwise produces a working pipeline and an
  empty answer.

Exit 1 if any data source cannot be read.

## `scripts/deploy_guard.py`

```
python scripts/deploy_guard.py <plan.json> --on-ui-edits <keep|overwrite|refuse>
python scripts/deploy_guard.py <plan.json> --live-matches
```

Reads `databricks bundle plan -o json` and decides whether deploying is safe. Writes
`deploy=true|false` to `$GITHUB_OUTPUT`; the deploy step is conditional on it.

| Verdict | Exit | When |
|---|---|---|
| `ok` | 0 | no UI edits, or the UI edits are already in git |
| `keep` | 0 | the live space has newer UI edits — do not deploy, they would be lost (dev) |
| `overwrite` | 0 | deploy anyway, and report what was overwritten (QA) |
| `refuse` | 2 | the space was edited in the UI and nobody should have (prod) |
| `destroy` | 3 | the plan would delete, recreate, or **duplicate** the space |

The duplicate check is the subtle one. A plan that says `create` means the bundle has no record of the
space — which is also exactly what a moved `deployment_root`, a renamed bundle or a new service principal
looks like. So before allowing a create, it asks the *workspace* whether a space with that title already
exists. If one does, it stops and prints the `bundle deployment bind` command to adopt it instead.

`--live-matches` is a different question, used by the PR benchmarks: does the live dev space hold exactly
this version? If not, benchmarking it would measure something else.

## `scripts/describe_changes.py`

```
python scripts/describe_changes.py OLD.json NEW.json     # Markdown
python scripts/describe_changes.py --same OLD.json NEW.json   # exit 0 if identical
```

Turns two versions of the space JSON into a change list a reviewer can read: *[+] added benchmark
question*, *[~] changed instruction*, with the exact diff in a collapsed block. Used in the dev-sync pull
request body, the bootstrap pull request, and the PR-checks summary.

`--same` ignores list order, which is why the sync does not open pull requests for re-ordered exports.

## `scripts/space_lib.py`

Shared helpers, not run directly. Knows the shape of the space JSON: which lists carry ids, how to
normalise them for comparison, how to label an item in words, and which catalogs it references. Also
loads `config/*.yml` for the other scripts (`config()`, `setting()`).

`dumps()` reproduces exactly the text `bundle generate` writes — that is what the format check compares
against.

## `scripts/check_space.py`

```
python scripts/check_space.py
```

Static checks, no workspace needed. The **format** check in PR checks and the first step of a release.

- the file is formatted exactly as `bundle generate` writes it
- ids are 32 lowercase hex characters and unique
- the space has at least one data source
- no version 1 field names in a version 2 file
- **every data source uses the dev catalog** — the JSON is exported from dev, and the catalog rewrite for
  QA and prod depends on that being true
- warns if no benchmark has a SQL answer, which would make the QA gate fail

## `scripts/set_catalog.sh`

```
bash scripts/set_catalog.sh <qa|prod>
```

Rewrites `<dev_catalog>.` to `<this target's catalog>.` throughout the space JSON, in the CI checkout
only. **Never commit the result.**

Bundles do not substitute variables inside a file referenced by `file_path`, so this is a textual rewrite.
It verifies afterwards that no reference to the dev catalog survives, and does nothing when the target
already reads the dev catalog.

## `scripts/deploy.sh`

```
bash scripts/deploy.sh <target>
```

Creates the bundle's resource folder (Databricks does not create it when a space is moved into it, which
fails with `Tree node ... does not exist`), then `databricks bundle deploy --auto-approve`.

## `scripts/tag_release.sh`

```
bash scripts/tag_release.sh <dev|qa|prod>
```

Records what an environment is running, as a tag you can roll back to. One version number per version of
the space, reused as it promotes:

```
genie-dev-v9    genie-qa-v9    genie-prod-v7
```

Writes two tags: `genie-<env>-v<n>` never moves and is the rollback point, `genie-<env>-current` moves
every deploy and says what is running now. Prints the ladder to the run summary.

Run **straight after the deploy**, before the smoke test and the benchmark gate, deliberately: the tag
says what the environment *is running*, not what passed. QA is deployed before its gate runs, so a failed
gate still leaves that version in QA and the tag has to say so.

## `scripts/open_pr.sh`

```
bash scripts/open_pr.sh <branch> <title> <body file> <commit message>
```

Commits `src/` on a bot branch and opens or updates its pull request. Force-pushes a single commit, so
the pull request always shows `main` → the current export. Needs `gh` and `GH_TOKEN`.

---

# Tests

## `tests/smoke_test.py`

Can the deployed space answer at all? Asks up to three questions through the Genie Conversation API and
requires each to produce SQL that returns **at least one row**.

Questions come from `SMOKE_QUESTIONS` (one per line), else the space's trusted example SQL, else its
benchmark questions.

It deliberately does not check that the numbers are right — that is the gate's job. It catches a space
that deploys but cannot work: missing tables, missing grants, a broken instruction, a row filter that
hides everything.

If the space has neither example SQL nor benchmarks, there is nothing to ask and the test **fails** with
*there is nothing to ask*, rather than passing on an empty list. A test that asserts nothing must not
report success.

```
export GENIE_SPACE_ID=$(databricks bundle summary -t dev -o json | jq -r '.resources.genie_spaces.genie_space.id')
python tests/smoke_test.py
```

## `tests/benchmark_gate.py`

The quality gate. Starts a Genie benchmark evaluation run, waits for it, and grades the result.

Genie compares its own SQL's result with the benchmark's expected SQL: **GOOD** (same result), **BAD**
(different), **NEEDS_REVIEW** (could not be compared — not counted either way).

Fails when the run does not finish, when nothing could be graded, or when accuracy on the graded
questions is below `ACCURACY_THRESHOLD` (default `0.80`). Writes a per-question table to the run summary.

| Variable | Default | |
|---|---|---|
| `ACCURACY_THRESHOLD` | `0.80` | the level Databricks suggests before user acceptance testing |
| `GATE_TIMEOUT_SECONDS` | `1800` | |
| `GATE_POLL_SECONDS` | `10` | |
