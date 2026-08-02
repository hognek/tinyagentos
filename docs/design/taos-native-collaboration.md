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

## The wake daemon, concretely

One small persistent service per agent, on the box that agent runs on:

1. Holds a connection to taOS (SSE where available, a tight poll otherwise) and
   watches for events addressed to its agent: a new note, a mention, a decision
   answered, a message.
2. Filters hard. Only real signals wake the agent. Auto-acks, its own posts and
   routine chatter are dropped. `a2a_filter.py` already does this job and should
   be reused rather than rewritten.
3. On a real signal, invokes the harness headlessly with the payload and a
   pinned session id, so the agent picks up with its context rather than cold.
4. Records that it woke, what for, and what came back. Emits a heartbeat, so a
   dead daemon is visibly dead rather than silently quiet.

**This is what makes Jay's paused-session scenario work.** A session that ends
mid-question posts the question to Decisions, and the daemon, not the session,
watches for the answer. When Jay answers, the daemon wakes the agent with the
answer and the agent resumes. The session ending stops being data loss.

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

**Slice 3, the wake daemon.** One agent first, most likely me, with the wake
budget and heartbeat from day one. Realtime replies to messages and decisions.

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
