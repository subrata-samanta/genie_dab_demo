# Documentation

How this repository takes a Databricks Genie space from an analyst's edit in the UI, through review and
automated testing, to production — and how to operate it.

The top-level [README](../README.md) is the short version: what to do, by role. These documents are the
long version: how it works and why.

## Start here

| | |
|---|---|
| **[architecture.md](architecture.md)** | The problem this solves, the flow end to end, the three environments, and why each guard exists. **Read this first.** |
| **[workflows-and-scripts.md](workflows-and-scripts.md)** | Every workflow and every script: what it does, what it reads, what it returns |
| **[new-space-checklist.md](new-space-checklist.md)** | Using this repository for another Genie space: the one file to edit, field by field, and everything to set up outside the repository |
| **[configuration.md](configuration.md)** | Every setting and which file it lives in. What to change when you clone this for another space |
| **[access-and-identity.md](access-and-identity.md)** | The permission model, the four gates, and how to verify them before deploying |
| **[operations.md](operations.md)** | Promoting, rolling back, resetting dev, versions, troubleshooting |

## If you are…

**Explaining this to someone** — [architecture.md](architecture.md) has the flow diagram and the
reasoning behind each control. Its *Why each guard exists* section is the part that usually needs saying
out loud, because each guard looks like overhead until you know what it prevents.

**Picking up an incident** — [operations.md](operations.md#troubleshooting), then
[access-and-identity.md](access-and-identity.md#symptoms-and-their-causes). Between them they cover every failure
this pipeline has actually produced.

**Setting up a new space** — [new-space-checklist.md](new-space-checklist.md). It is the only document
you need: one file to edit, then the Databricks and GitHub setup, which is the part that takes the time.

**Changing a script** — [workflows-and-scripts.md](workflows-and-scripts.md). Each entry says why the
script exists, which matters more than what it does: most of them are guards against a specific failure,
and the comment at the top of each file records the one it prevents.

## The three things worth knowing up front

1. **Databricks keeps no version history of a Genie space.** Git is the only record. The bundle will
   happily overwrite a live space with whatever `main` says.

2. **Genie answers every question as the identity that asks it.** In CI that is the service principal.
   Your own access proves nothing — the most expensive failure in this project's history was a row filter
   that returned zero rows for the service principal while answering perfectly in the UI.

3. **The editors never touch git.** They edit the dev space; an hourly workflow turns their work into a
   reviewable pull request. Anything that makes editors use git breaks the premise.
