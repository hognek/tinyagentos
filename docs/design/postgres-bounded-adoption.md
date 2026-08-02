# Bounded Postgres adoption, and an 8GB hardware floor

**Status:** PROPOSED, not adopted. Needs Jay's decision before any code lands.
**Date:** 2026-08-02
**Supersedes nothing. Blocks nothing currently in flight.**

## The question this answers

Should taOS move from SQLite to PostgreSQL project wide, so we maintain one
storage engine instead of several options?

Short answer: no, not project wide, and the premise is worth correcting. We
maintain exactly one storage engine today. A project wide migration would not
remove an option, it would add a second engine that we carry for as long as the
crossing takes, on top of moving live user data. What is worth doing is adopting
Postgres deliberately for the one tier that genuinely needs it, behind an
interface that already exists.

## What the migration surface actually measures

Counted on `origin/dev` and the production Pi, 2026-08-02:

| Measure | Count |
|---|---|
| Python files touching `sqlite3` / `aiosqlite` | 86 |
| Live `.db` files in `data/` on the Pi | 75 |
| Live data volume | 1.5 GB |
| Stores with a disciplined `MIGRATIONS` chain | 7 |

The last row is the important one. Most stores create their schema ad hoc with
`CREATE TABLE IF NOT EXISTS` plus a guarded `_post_init`. A project wide move
would mean writing migration discipline for roughly 68 stores that do not have
it, and then exercising every one of them over a populated pre change database,
because that is our standing rule for upgrades.

## Hardware floor: 8GB minimum

Adopted as part of this proposal.

Raising the floor from 4GB to 8GB retires the "core only" low RAM tier, shrinks
the support matrix, and matches what the hardware market actually sells. It is
also a precondition for anything in this document: Postgres is not a reasonable
ask on a 4GB board that is also running inference.

This needs to be an announced, documented floor with a release note, not a
silent drift. Existing 4GB installs must keep working on their current version
and must be told plainly that they are on a frozen branch.

## What Postgres genuinely buys, and where

Real advantages, all of which apply to large nodes and none of which apply to an
SBC running a single user:

- **Roles and row level security**, which map directly onto the multi user and
  account/subdomain model. This is the strongest single argument.
- **One engine for vectors, full text and graph**: pgvector, tsvector, and
  pgGraph (Apache 2.0, PG 14 to 18, actively maintained) over the same rows.
- **Cross store queries** without attaching a dozen database files.
- **Concurrent writers** without SQLite's single writer contention.

## What Postgres costs, stated plainly

- **Major version upgrades on an appliance.** SQLite has no such event: the file
  is the database and backup is copying it. Postgres needs `pg_upgrade` or a
  dump and restore at every major bump. If that fails on a user's box, core
  services do not start, and our user is someone who never opens a terminal.
  This is the single largest risk in the proposal.
- **Backup regresses** from "copy the files" to orchestrating `pg_dump` and
  proving the restore.
- **Install weight**: a daemon, a data directory, a tuning profile, and a
  failure mode that did not previously exist.
- **taOSmd's identity.** taOSmd is a separate embeddable product whose published
  benchmark result is explicitly measured on a low end reference stack. Making
  it require Postgres would cost it that claim and its embeddability.

## The line

**Postgres is for the corpus and coordination tier on capable nodes:**

- knowledge/corpus storage: chunks, embeddings, concepts, graph edges
- cluster and multi user state where roles and RLS earn their keep

**SQLite stays the default for everything else**, specifically:

- taOSmd in all its default deployments, including the SBC tier
- per app stores, window state, settings, small operational stores

**No existing store migrates as part of this work.** A store moves only when it
has a demonstrated reason to, with its own migration and its own upgrade test.

Adoption goes behind `taosmd/backend.py`'s `MemoryBackend` interface, which
already exists for third party memory backends. This is a plug in against a
designed seam, not a fork of the storage layer.

## Hard prerequisites, before anything ships depending on Postgres

These are gates, not preferences. Each must be demonstrably true.

1. **taOS manages the Postgres lifecycle itself**: containerized, major version
   pinned, provisioned and started by the OS, never a manual install step. The
   user never types a Postgres command.
2. **A tested major version upgrade path**, exercised against a populated data
   directory of realistic size, with a proven rollback. Demonstrate it failing
   safely as well as succeeding: an upgrade that has only ever been seen working
   is unproven.
3. **Backup and restore parity** with today: an automated dump, a restore that
   is actually performed in a test, and a documented recovery for a user who
   cannot use a terminal.
4. **Degraded operation is defined.** If Postgres is unavailable, the OS boots,
   the desktop loads, and the affected app reports a clear error. Postgres must
   not become a boot dependency for the whole system.
5. **The 8GB floor is announced and in effect.**

## Verification

- Fresh install on an 8GB node provisions Postgres unattended and comes up.
- A populated corpus survives a pinned major version bump, with rollback proven.
- Killing Postgres leaves the OS and unrelated apps working.
- taOSmd's default SQLite path is unchanged and its benchmark is re-run to show
  no regression.
- Existing installs that never opt in see no behaviour change at all.

## What this does not solve

Reducing the number of inference backends (llama.cpp, rkllama, Hailo, qmd) or
container runtimes (LXC, Docker) is out of scope and not desirable: those exist
because the hardware differs, not because we drifted. Storage was the wrong
place to look for option reduction, which is part of why this proposal is
bounded rather than sweeping.

## Open questions for Jay

1. Does the corpus tier justify Postgres on its own, or should it wait until the
   multi user work needs RLS anyway, so one adoption serves both?
2. pgGraph is the thing that makes a single engine attractive rather than merely
   bigger. Do we treat it as a hard part of the case, or as a later option?
3. On an 8GB node that is also running inference, what is the acceptable
   Postgres resident footprint before it competes with model memory?
