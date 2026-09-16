"""The lock screen's touch gestures, EXECUTED rather than grepped for.

tsk-6bjsvg: a long upward drag to read to the end of the notification feed was
being read as swipe-up-to-unlock, throwing the reader into the PIN keypad. The
unlock gesture is bound to `document.body`, so the feed had no say in it.

These tests run the real gesture source out of `_LOCK_SCREEN_SCRIPT` under node
against a small DOM stand-in. That is more machinery than asserting on the
script text, and it is here for one reason: a string assertion for the fix
passes whether or not the fix WORKS. It cannot tell a touchstart latch from a
touchend one, and the touchend version is the plausible wrong answer -- the
finger leaves the feed during exactly the drag we mean to exclude.

Because a stub DOM can pass everything by doing nothing, `test_harness_observes_
the_defect` re-runs the failing scenario against the gesture source with the fix
STRIPPED BACK OUT and requires it to unlock. If the stub ever goes inert, that
control fails first and says so.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess

import pytest

from tinyagentos.routes.auth import _LOCK_SCREEN_SCRIPT as LOCK_SCRIPT


def _balanced(src: str, start: int, opener: str, closer: str) -> str:
    """Return src[start:] through the balanced close of the first `opener`.

    Quote-aware, because a brace inside a string literal would otherwise end the
    span early and hand the caller a slice that happens to parse.
    """
    i = src.index(opener, start)
    depth, quote = 0, ""
    while i < len(src):
        ch = src[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return src[start : i + 1]
        i += 1
    raise AssertionError(f"unbalanced {opener!r} from offset {start}")


def _function(name: str) -> str:
    """The source of `function <name>(...) { ... }`, braces balanced."""
    head = f"function {name}("
    assert head in LOCK_SCRIPT, f"{head!r} is gone from the lock screen script"
    return _balanced(LOCK_SCRIPT, LOCK_SCRIPT.index(head), "{", "}")


def _unlock_wiring() -> str:
    """The source of the `swipe(document.body, openPasscode, ...)` call."""
    head = "swipe(document.body, openPasscode,"
    assert head in LOCK_SCRIPT, "the unlock swipe is no longer bound to the body"
    start = LOCK_SCRIPT.index(head)
    return _balanced(LOCK_SCRIPT, start, "(", ")") + ";"


#: A DOM only as real as these gestures need, plus the scenario driver.
#:
#: Touch events are fabricated and handed straight to the listeners the source
#: registered. That is the point of the exercise: the assertions are about what
#: the registered handlers DO, not about what the script says.
_HARNESS = r"""
function makeEl(opts) {
  opts = opts || {};
  return {
    _sel: opts.sel || [],
    _parent: opts.parent || null,
    _attrs: opts.attrs || {},
    _h: {},
    scrollHeight: opts.scrollHeight || 0,
    clientHeight: opts.clientHeight || 0,
    scrollTop: 0,
    addEventListener: function (t, fn) { (this._h[t] = this._h[t] || []).push(fn); },
    setAttribute: function (k, v) { this._attrs[k] = v; },
    getAttribute: function (k) {
      return Object.prototype.hasOwnProperty.call(this._attrs, k) ? this._attrs[k] : null;
    },
    closest: function (sel) {
      var n = this;
      while (n) { if (n._sel.indexOf(sel) !== -1) return n; n = n._parent; }
      return null;
    },
    fire: function (t, ev) { (this._h[t] || []).slice().forEach(function (fn) { fn(ev); }); }
  };
}

var SCN = JSON.parse(process.env.LS_SCENARIO);

var body   = makeEl({ sel: ["body"] });
var screenEl = makeEl({ attrs: { "data-sheet": SCN.sheet } });
var feedEl = makeEl({
  sel: [".ls-feed"], parent: body,
  scrollHeight: SCN.feedScrollHeight, clientHeight: SCN.feedClientHeight
});
// A notification card inside the feed -- what the finger actually lands on.
var card = makeEl({ sel: [".ls-note"], parent: feedEl });
var document = { body: body };

var unlocked = 0;
function openPasscode() { unlocked += 1; }

__GESTURE_SOURCE__

var targets = { body: body, card: card, feed: feedEl };
var startT = targets[SCN.startOn], endT = targets[SCN.endOn];

body.fire("touchstart", { target: startT, touches: [{ clientX: SCN.x0, clientY: SCN.y0 }] });
// One intermediate move, so `moved` latches the way a real drag sets it.
body.fire("touchmove", {
  target: startT,
  touches: [{ clientX: (SCN.x0 + SCN.x1) / 2, clientY: (SCN.y0 + SCN.y1) / 2 }]
});
body.fire("touchend", { target: endT, changedTouches: [{ clientX: SCN.x1, clientY: SCN.y1 }] });

process.stdout.write(JSON.stringify({ unlocked: unlocked }));
"""


def _gesture_source(*, with_fix: bool = True) -> str:
    """The real source of the gesture machinery, optionally de-fixed.

    `with_fix=False` rebuilds the wiring as it stood before tsk-6bjsvg -- the
    unlock swipe bound to the body with no origin veto -- so a test can prove
    the harness is able to observe the bug at all.
    """
    wiring = _unlock_wiring()
    if not with_fix:
        # Drop the 5th argument (the veto) and nothing else.
        guard_end = wiring.rindex("}, function (ev) {")
        wiring = wiring[: guard_end + 1] + ");"
        assert "closest" not in wiring, "de-fixed wiring still carries the veto"
    return "\n".join([_function("feedOverflows"), _function("swipe"), wiring])


def _drive(scenario: dict, *, with_fix: bool = True) -> int:
    """Run one gesture and return how many times unlock was triggered."""
    node = shutil.which("node")
    if node is None:  # pragma: no cover - depends on the runner image
        pytest.skip("node is required to execute the lock screen gesture source")
    script = _HARNESS.replace("__GESTURE_SOURCE__", _gesture_source(with_fix=with_fix))
    done = subprocess.run(
        [node, "-e", script],
        env={**os.environ, "LS_SCENARIO": json.dumps(scenario)},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert done.returncode == 0, f"node failed:\n{done.stderr}"
    return json.loads(done.stdout)["unlocked"]


def _scenario(**over) -> dict:
    """A 200px upward drag on the resting screen, over an overflowing feed."""
    base = {
        "sheet": "none",
        "feedScrollHeight": 900,
        "feedClientHeight": 300,
        "startOn": "card",
        "endOn": "card",
        "x0": 160,
        "y0": 620,
        "x1": 160,
        "y1": 420,
    }
    base.update(over)
    return base


class TestUnlockSwipeOrigin:
    """tsk-6bjsvg: reading the feed must not unlock the phone."""

    def test_drag_from_the_feed_does_not_open_the_keypad(self):
        """THE RED CASE. A long upward drag begun in a scrollable feed.

        This is Jay's bug verbatim: one long drag to reach the end of the
        notifications, which is where it bites, because that is where short
        flicks give way to a single sustained pull.
        """
        assert _drive(_scenario()) == 0

    def test_drag_that_leaves_the_feed_is_judged_by_where_it_began(self):
        """The subtle one: the finger ENDS outside the feed.

        A 200px drag is most of this screen, so the finger routinely leaves the
        feed before lifting. An implementation that asks `touchend.target`
        instead of latching at touchstart passes the test above and still ships
        the bug -- so the two scenarios differ only in where the touch ended.
        """
        assert _drive(_scenario(endOn="body")) == 0

    def test_drag_anywhere_else_still_unlocks(self):
        """The positive case, without which a veto could pass by never unlocking."""
        assert _drive(_scenario(startOn="body", endOn="body")) == 1

    def test_a_feed_with_nothing_to_scroll_still_unlocks(self):
        """A feed that cannot move is not being read.

        On a device with one agent and no notifications the feed still covers
        the middle of the glass. Vetoing there would trade Jay's bug for a dead
        unlock gesture over most of the screen, on the first screen a new user
        sees. The cut-edge fade already measures overflow for the same reason.
        """
        assert _drive(_scenario(feedScrollHeight=300)) == 1

    def test_the_veto_does_not_reach_past_the_resting_screen(self):
        """With a sheet open the unlock swipe was already disarmed; keep it so."""
        assert _drive(_scenario(sheet="chat", startOn="body", endOn="body")) == 0

    def test_harness_observes_the_defect(self):
        """THE CONTROL. Strip the fix and the red scenario must unlock.

        Without this, every assertion above could be passing because the DOM
        stub quietly does nothing -- "no unlock" and "no gesture ran at all"
        read identically. This is the one assertion that fails if the harness
        stops measuring.
        """
        assert _drive(_scenario(), with_fix=False) == 1


class TestGestureLatching:
    """Properties of `swipe()` itself that the scenarios above rely on."""

    def test_the_veto_is_latched_at_touchstart(self):
        """Asserted on structure because it is a claim about WHEN, not what.

        `test_drag_that_leaves_the_feed_...` is the behavioural proof; this
        names the mechanism so a future reader does not "simplify" the latch
        into a touchend lookup and find only a scenario failing for a reason
        the code does not explain.
        """
        latch = "vetoed = !!(veto && veto(ev))"
        assert latch in LOCK_SCRIPT, "the veto is no longer latched from the event"
        touchstart = LOCK_SCRIPT.index('surface.addEventListener("touchstart"')
        touchend = LOCK_SCRIPT.index('surface.addEventListener("touchend"', touchstart)
        assert touchstart < LOCK_SCRIPT.index(latch) < touchend

    def test_overflow_is_measured_in_exactly_one_place(self):
        """The fade and the veto must not drift apart about "can this scroll"."""
        assert LOCK_SCRIPT.count("feedEl.scrollHeight - feedEl.clientHeight") == 1
        assert LOCK_SCRIPT.count("feedOverflows()") >= 2
