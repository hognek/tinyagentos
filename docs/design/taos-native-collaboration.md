# Moving work and comms into taOS

**Status:** PROPOSED. Needs Jay's decisions on the marked questions before slice 1.
**Date:** 2026-08-02
**Goal, in Jay's words:** put an idea into taOS, have an agent pick it up, ask
clarifying questions in Decisions, then spec, design and card it, without ever
opening Claude Code. Agents reply in realtime to messages and decisions inside
taOS. Claude Code stops being the primary place work happens.

## The honest answer: yes, except for one missing mechanism

Almost every part of this already exists. The blocker is not taOS, it is the
agent side, and it is a single specific gap.

**An LLM agent has no event loop.** It does not run continuously waiting for
messages. It acts only when its harness gives it a turn. Everything that looks
like realtime today, including my own A2A watcher, is a process running *inside
an already-open session*: when the session ends, the watching ends with it. That
is why the current setup depends on a Claude Code window being open. Nothing in
taOS can fix this, because the missing part is on the harness side.

**What changes the picture:** the Claude CLI supports headless invocation
(`claude -p`), a pinned `--session-id`, and `--resume`. So a small daemon can
hold the watch and INVOKE the harness when something arrives, creating the turn
that the agent needs in order to act. That is the whole trick, and it is
buildable now.

## What already exists

| Piece | State |
|---|---|
| Projects with nested typed elements | Built. `type` is free-form, so notes and lists are storable today |
| Project Files API | Built |
| Decisions app: create, answer, notify | Built, and agents can create decisions with a registry token |
| A2A bus and channels | Built, running on the Pi |
| Messages and chat | Built |
| Notifications | Built |
| Signal filtering (drop noise, keep real mentions) | Built, `a2a_filter.py` |

## What is missing

1. **A notes surface in Projects.** The storage exists; there is no organised
   notes-and-lists UI to put an idea into. Pure build, no blockers.
2. **Agent-state badges on entries** (see below). Small model plus UI.
3. **The wake daemon.** The real blocker.
4. **Cost governance.** Every wake spends tokens. Without gating this eats the
   weekly budget, which is already the binding constraint on how much the fleet
   can do.

## Badges: making agent state visible on the entry

Jay's ask, and it is the difference between "I threw an idea in a box" and "I
know what is happening to it". Every note, card, message and decision carries a
visible state:

- **Unseen** the agent has not read it yet
- **Seen** read, not yet acted on
- **Working** an agent is actively on it, with which agent shown
- **Question waiting** the agent asked something and is blocked on Jay, linked
  straight to the decision
- **Done** with what came of it, a card, a PR, a spec
- **Stalled** claimed but nothing has happened for N hours

Two properties matter more than the list itself. The state must be written by
the same mechanism that does the work, never by an agent remembering to update
it, or it will drift and become a lie. And **stalled must be computed, not
reported**: an agent that dies cannot mark itself stalled, and a dead agent
looks exactly like a working one otherwise. That is the same trap as a dead
watcher looking like a quiet one.

## Delivery: inject into the open session, do not spawn a new one

**Corrected 2026-08-02 by Jay, and it is the better design.** The earlier draft
proposed a daemon that spawns a headless session per event. That is the
expensive way to build this, and taOS should not be spawning a session per task.

**The mechanism already exists and is already in use.** `herdr pane run <pane>
"<message>"` injects a turn into an ALREADY-OPEN Claude session. That is exactly
how the context-watch and usage-watch nudges reach the agents today: the cron
measures, then injects a message into the agent's pane, and the agent picks it
up on its next turn. There is no cold start, no context reload, and no new
session: the session is already warm, so the marginal cost is one turn.

Cost comparison for the same event, measured earlier in this doc:

| Delivery | Cost per event |
|---|---|
| Spawn a fresh headless session | $0.164 (full context load first) |
| Resume a headless session | $0.031 |
| **Inject into an already-open session** | **incremental turn only, no reload** |

**So the realtime design is a router, not a daemon fleet:**

1. A watcher on taOS events (note created, decision answered, message, mention)
   with the same hard filtering we already use, so only real signals get through.
2. A mapping from taOS agent identity to live pane id.
3. Delivery via `herdr pane run` into that agent's open pane.
4. Batching: a short settle window so a burst becomes one injection.

**What this needs that we do not have yet:**

- **An agent-to-pane registry.** Today the pane list is discoverable
  (`herdr pane list` reports agent, cwd, status and pane id) but nothing maps
  "@taOSmd-dev" to "w1:p2". That mapping has to be explicit and maintained, not
  guessed from the working directory.
- **Liveness surfaced in taOS.** If an agent's pane is gone, an idea dropped in
  taOS will sit unread. taOS must show which agents are actually connected, so
  the badge says "unseen, agent offline" rather than a silent nothing. A dead
  agent must not look like a quiet one.
- **A queue for offline agents**, so work is delivered when they come back
  rather than lost.

**Where spawning still belongs:** only for the case where no session is open at
all. Jay's call is that this becomes a taOS Teams capability later, not part of
this design.

## Measured, not assumed: headless viability and cost

Tested on this Max subscription on 2026-08-02, no API key present, so these are
subscription numbers.

**Headless works.** `claude -p` returns clean JSON, `is_error: false`, and a
`session_id`. No API key required and no restriction encountered.

**Cost per wake, measured on a trivial prompt:**

| Mode | Cost | Cache creation | Cache read |
|---|---|---|---|
| Cold start (new session) | $0.164 | 7,347 | 15,251 |
| `--resume` an existing session | $0.031 | 388 | 22,598 |

The cold-start floor is the system prompt, CLAUDE.md and the memory index being
loaded *before any work happens*. **Resume is 5.3x cheaper per wake**, and that
ratio, not the daily count, is what decides whether this is affordable. At 50
wakes a day it is roughly $8 a day cold versus $1.55 resumed.

**Design consequence:** never spawn per event. Injecting into an open session is
cheaper than both rows above, and resume is the fallback for a session that has
been closed, not the primary path.

## Session identity and context lifecycle

Sessions are plain files: `~/.claude/projects/<path-slug>/<session-id>.jsonl`.
The session id is the filename, so tracking is a matter of recording one uuid
per agent and confirming the file still exists before resuming.

The catch with resume is that context grows monotonically. This session's
transcript is already 4.9MB. Left alone, a long-lived resumed session gets
slower, more expensive per wake, and eventually hits the context ceiling.

**We already solved this by hand, and the daemon should automate the existing
pattern rather than invent one.** `context_watch.sh` measures a session's token
usage and nudges at banded thresholds; `checkpoint_and_clear.sh` and the
`RESUME-*.md` handoff docs capture durable state so a fresh session can pick up
without re-deriving. The policy that falls out:

- **Preserve** by default: resume the pinned session, cheapest per wake.
- **Summarise** at a token band: write the handoff doc, start a fresh session,
  record the new id. The cost of one cold start is repaid within a few wakes.
- **Clear** deliberately when the work changes shape, so an agent is not
  carrying a finished project's context into a new one.

The durable memory is the handoff doc and taOS itself, never the transcript.
That is what makes clearing safe, and it is already how the agents work.

## Risk: this depends on a harness feature

Headless invocation working on a subscription is an external dependency we do
not control, and it has been discussed as something that might be restricted.
The mitigation is in the ordering: slices 1 and 2 deliver the notes surface and
the badges with timed pickup, which need none of this. Only the realtime upgrade
depends on it, and if that route closed, the fallback is a scheduled pickup on a
few-minute cadence, which is worse but not broken.

## Cost, stated plainly

Every wake is a paid turn. A chatty channel could wake an agent hundreds of
times a day and exhaust the weekly budget in hours. This is the single biggest
risk to the whole design and it needs deciding up front, not discovering later:

- Hard daily wake budget per agent, refusing to wake past it and telling Jay it
  has stopped rather than going quiet.
- Batching: a short settle window so five messages in a minute produce one wake.
- Tiering: free-model agents take the cheap work, expensive agents wake only for
  judgement.

## Phases

**Slice 1, notes and pickup.** A notes and lists surface in Projects. An agent
picks up new notes, asks clarifying questions as decisions, and turns the answer
into a spec and cards. Wake is still timed rather than realtime. This alone
delivers "I put an idea in and never open Claude Code", just with latency.

**Slice 2, badges.** Agent state on every entry, computed where it can be.

**Slice 3, the event router.** Agent-to-pane registry, liveness in taOS, and
delivery by injection into open sessions. Realtime replies to messages and
decisions, with no session spawning.

**Slice 4, the rest of the fleet.** The sibling agents get daemons, and Claude
Code becomes a debugging tool rather than the venue.

Slices 1 and 2 are useful on their own even if 3 is delayed, which is the point
of the ordering: nothing here is all-or-nothing.

## Decisions needed before slice 1

1. **Where do notes live?** A first-class Notes element type inside a Project,
   or a dedicated Notes app that references projects? Cheaper inside Projects,
   more discoverable as its own app.
2. **Which agent owns idea intake?** Me, or the in-OS taOS agent that is already
   the user-facing one? This decides who Jay is talking to when he drops an idea.
3. **The wake budget number.** How many paid wakes per day is acceptable before
   the daemon stops and says so.

## What this does not change

Claude Code stays the place for debugging the fleet itself and for work that
needs a terminal. The goal is that Jay does not need it for the ordinary loop of
having an idea and getting it built.
