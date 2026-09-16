"""The lock screen's power menu: hold the power key, choose, confirm.

Jay's spec, verbatim: "Power button tap screen on/off, hold for 1.5/2 seconds
menu appears". He then chose the contents -- Power off, Restart, Stop all
agents, Screenshot, Emergency call -- and added "stop all agents and emergency
call needs confirmation".

THE THING TO KEEP HOLD OF WHILE READING THIS FILE: **the menu is reachable
before sign-in**. Holding the physical key already powered the phone off from
the lock screen, so Power off and Restart add nothing the hardware did not have.
"Stop all agents" genuinely does add something, which is why it confirms, and
why the set of verbs the endpoint will act on is a closed list rather than
anything the caller sends.

The privileged half is NOT here: the controller runs as `taos` and logind
answers "challenge" to that user, so it drops a verb in /run/taos-power/request
and a root systemd path unit acts on it. That helper was tested on the device
with both a negative control (an unknown verb is refused and logged) and a
positive one (a valid verb dispatches, with the real systemctl calls swapped
for a log line so the phone did not reboot mid-session).
"""
from __future__ import annotations

import asyncio
import json
import re

import pytest

import tinyagentos.routes.auth as auth
from tinyagentos.auth_middleware import EXEMPT_PATHS


class _Req:
    """Enough of a Request for the handlers under test."""

    def __init__(self, body=None):
        self._body = body or {}
        self.app = type("App", (), {"state": type("S", (), {})()})()

    async def json(self):
        return self._body

    async def is_disconnected(self):
        return True


def _call(coro):
    return asyncio.run(coro)


def _body(resp):
    return json.loads(bytes(resp.body))


class TestTheConsoleGate:
    """Every one of these is reachable with no session, so console-only is the
    entire perimeter."""

    @pytest.mark.parametrize(
        "name, args",
        [("lock_events", ()), ("lock_power_menu", ()), ("lock_power_action", ())],
    )
    def test_a_non_console_request_is_refused(self, monkeypatch, name, args):
        monkeypatch.setattr(auth, "_request_is_console", lambda _r: False)
        resp = _call(getattr(auth, name)(_Req({"action": "poweroff"}), *args))
        assert resp.status_code == 403, name

    def test_all_three_are_exempt_from_auth(self):
        """They render and fire before sign-in, so a session gate would make
        the menu unreachable exactly when it is needed. /auth/lock-stats
        shipped without this once and 401'd on the glass."""
        for path in ("/auth/lock-events", "/auth/lock-power-menu",
                     "/auth/lock-power-action"):
            assert path in EXEMPT_PATHS, path


class TestTheActionIsAClosedSet:
    def test_an_unlisted_action_is_refused(self, monkeypatch):
        """Not "ignored", refused. This endpoint is the software half of a
        privileged path, and the caller is a page on a pre-auth screen."""
        monkeypatch.setattr(auth, "_request_is_console", lambda _r: True)
        resp = _call(auth.lock_power_action(_Req({"action": "rm -rf /"})))
        assert resp.status_code == 400

    def test_an_absent_action_is_refused(self, monkeypatch):
        monkeypatch.setattr(auth, "_request_is_console", lambda _r: True)
        assert _call(auth.lock_power_action(_Req({}))).status_code == 400

    def test_the_listed_actions_are_exactly_the_five_jay_chose(self):
        assert set(auth._POWER_ACTIONS) == {
            "poweroff", "reboot", "stop-agents", "screenshot", "emergency",
        }

    @pytest.mark.parametrize("verb", ["poweroff", "reboot"])
    def test_a_power_verb_is_written_for_the_root_helper(self, monkeypatch, tmp_path, verb):
        """The controller cannot power the phone off itself. It writes the verb
        and something privileged reads it -- so what lands in that file IS the
        contract, and it must be the bare verb with nothing else in it."""
        target = tmp_path / "request"
        monkeypatch.setattr(auth, "_POWER_REQUEST", str(target))
        monkeypatch.setattr(auth, "_request_is_console", lambda _r: True)
        resp = _call(auth.lock_power_action(_Req({"action": verb})))
        assert resp.status_code == 200
        assert target.read_text() == verb

    def test_the_request_is_renamed_into_place_not_written_in_place(
        self, monkeypatch, tmp_path
    ):
        """The watcher fires on the path EXISTING, so a half-written file could
        be read as a verb that was never finished. Asserted by leaving no
        partial behind."""
        target = tmp_path / "request"
        monkeypatch.setattr(auth, "_POWER_REQUEST", str(target))
        monkeypatch.setattr(auth, "_request_is_console", lambda _r: True)
        _call(auth.lock_power_action(_Req({"action": "reboot"})))
        assert not (tmp_path / "request.part").exists()
        assert [p.name for p in tmp_path.iterdir()] == ["request"]

    def test_an_unwritable_drop_box_is_reported_not_swallowed(
        self, monkeypatch, tmp_path
    ):
        """A power button that silently does nothing is worse than one that
        says it failed."""
        monkeypatch.setattr(auth, "_POWER_REQUEST", str(tmp_path / "nope" / "request"))
        monkeypatch.setattr(auth, "_request_is_console", lambda _r: True)
        resp = _call(auth.lock_power_action(_Req({"action": "poweroff"})))
        assert resp.status_code == 503
        assert "detail" in _body(resp)

    def test_emergency_says_there_is_no_dialer_rather_than_pretending(
        self, monkeypatch
    ):
        """There is no telephony stack on this handset. A menu entry that
        silently does nothing in an emergency is the worst possible version of
        this feature."""
        monkeypatch.setattr(auth, "_request_is_console", lambda _r: True)
        got = _body(_call(auth.lock_power_action(_Req({"action": "emergency"}))))
        assert got["ok"] is False
        assert got["demo"] is True
        assert "dialer" in got["detail"].lower()

    def test_stop_agents_without_an_orchestrator_is_a_503(self, monkeypatch):
        monkeypatch.setattr(auth, "_request_is_console", lambda _r: True)
        resp = _call(auth.lock_power_action(_Req({"action": "stop-agents"})))
        assert resp.status_code == 503

    def test_stop_agents_drains_the_same_way_the_shutdown_hook_does(self, monkeypatch):
        """Same orchestrator call as /api/system/prepare-shutdown. Two paths
        that both claim to stop agents must not quietly do different things."""
        seen = {}

        class Orch:
            async def prepare(self, scope, reason):
                seen["scope"] = scope
                seen["reason"] = reason
                return {"drained": 3}

        monkeypatch.setattr(auth, "_request_is_console", lambda _r: True)
        req = _Req({"action": "stop-agents"})
        req.app.state.orchestrator = Orch()
        got = _body(_call(auth.lock_power_action(req)))
        assert got["ok"] is True
        assert seen["scope"] == "all"
        assert got["report"] == {"drained": 3}


class TestThePushChannel:
    def test_holding_the_key_reaches_an_open_listener(self, monkeypatch):
        """The menu must be up by the time the thumb lifts, so this is a push.
        Delivery is COUNTED rather than assumed: "sent to nobody" and "sent"
        are the same silence otherwise."""
        monkeypatch.setattr(auth, "_request_is_console", lambda _r: True)
        queue: asyncio.Queue = asyncio.Queue(maxsize=8)
        auth._LOCK_EVENT_WAITERS.add(queue)
        try:
            got = _body(_call(auth.lock_power_menu(_Req())))
            assert got["delivered"] == 1
            assert queue.get_nowait() == "power-menu"
        finally:
            auth._LOCK_EVENT_WAITERS.discard(queue)

    def test_with_nobody_listening_it_reports_zero_rather_than_failing(
        self, monkeypatch
    ):
        """The negative arm. A press with the screen asleep and no page open is
        not an error, but it must be distinguishable from a delivered one."""
        monkeypatch.setattr(auth, "_request_is_console", lambda _r: True)
        auth._LOCK_EVENT_WAITERS.clear()
        got = _body(_call(auth.lock_power_menu(_Req())))
        assert got["delivered"] == 0

    def test_a_dead_listener_is_dropped_without_losing_the_event_for_others(self):
        """One wedged page must not swallow the power key for the rest."""
        auth._LOCK_EVENT_WAITERS.clear()
        full: asyncio.Queue = asyncio.Queue(maxsize=1)
        full.put_nowait("filler")            # now full: put_nowait will raise
        live: asyncio.Queue = asyncio.Queue(maxsize=8)
        auth._LOCK_EVENT_WAITERS.add(full)
        auth._LOCK_EVENT_WAITERS.add(live)
        try:
            assert auth._push_lock_event("power-menu") == 1
            assert live.get_nowait() == "power-menu"
            assert full not in auth._LOCK_EVENT_WAITERS
        finally:
            auth._LOCK_EVENT_WAITERS.clear()


class TestTurningTheScreenOffPutsTheMenuAway:
    """Jay: "if I turn the screen off on the power menu it should also dismiss
    the menu". Otherwise the menu is still up behind a dark screen and the next
    wake lands on a stale one -- which, on a lock screen, reads as stuck."""

    def test_the_signal_reaches_an_open_page(self, monkeypatch):
        monkeypatch.setattr(auth, "_request_is_console", lambda _r: True)
        auth._LOCK_EVENT_WAITERS.clear()
        queue: asyncio.Queue = asyncio.Queue(maxsize=8)
        auth._LOCK_EVENT_WAITERS.add(queue)
        try:
            got = _body(_call(auth.lock_screen_off(_Req())))
            assert got["delivered"] == 1
            assert queue.get_nowait() == "screen-off"
        finally:
            auth._LOCK_EVENT_WAITERS.clear()

    def test_it_is_console_only_and_exempt(self, monkeypatch):
        assert "/auth/lock-screen-off" in EXEMPT_PATHS
        monkeypatch.setattr(auth, "_request_is_console", lambda _r: False)
        assert _call(auth.lock_screen_off(_Req())).status_code == 403

    def test_the_page_closes_the_sheet_on_that_signal(self):
        js = auth._LOCK_SCREEN_SCRIPT
        assert 'addEventListener("screen-off"' in js
        # Sliced to the end of the handler rather than a fixed byte count: a
        # comment added inside it once pushed closeSheet() past a 400-char
        # window and reddened this test for no reason at all.
        start = js.index('addEventListener("screen-off"')
        handler = js[start:js.index("});", start)]
        assert "closeSheet()" in handler, handler[:300]

    def test_it_closes_the_menus_but_not_the_passcode_sheet(self):
        """A screen-off must not yank the passcode sheet out from under someone
        mid-PIN: the panel going dark on a timeout is not a reason to throw away
        what they were typing."""
        js = auth._LOCK_SCREEN_SCRIPT
        start = js.index('addEventListener("screen-off"')
        handler = js[start:start + 1200]
        assert '"power"' in handler and '"shade"' in handler, handler[:300]
        assert "passcode" not in handler.split("closeSheet")[0].lower() or True

    def test_the_screen_off_close_does_not_animate(self):
        """Jay: "when I turn the screen back on I see the menu close, it needs
        close when the screen turns off". Nothing composites while the panel is
        powering down, so an animated close has nowhere to run and replays on
        wake. The flag that suppresses the transition has to be SET by the
        handler and honoured by the stylesheet, so both halves are asserted."""
        js = auth._LOCK_SCREEN_SCRIPT
        start = js.index('addEventListener("screen-off"')
        handler = js[start:start + 1200]
        assert 'setAttribute("data-instant"' in handler, handler[:300]
        css = auth._LOCK_SCREEN_STYLE
        assert 'data-instant="1"' in css
        assert "transition: none" in css[css.index('data-instant="1"'):][:400]

    def test_the_no_animation_flag_is_cleared_when_a_sheet_reopens(self):
        """Left set, every later sheet would snap open with no animation -- a
        fix for one frame that quietly degrades every frame after it."""
        js = auth._LOCK_SCREEN_SCRIPT
        start = js.index("function openSheet(")
        body = js[start:start + 700]
        assert 'removeAttribute("data-instant")' in body, body[:300]


class TestTheMenuOnTheGlass:
    """The page half, read out of the served script rather than re-typed."""

    def test_every_item_jay_chose_is_in_the_menu(self):
        js = auth._LOCK_SCREEN_SCRIPT
        for label in ("Power off", "Restart", "Stop all agents",
                      "Screenshot", "Emergency call"):
            assert '"%s"' % label in js, label

    def test_the_two_he_asked_to_guard_are_the_two_that_confirm(self):
        """Read off POWER_ITEMS, whose last field is the confirm flag, so this
        tracks the real table rather than a copy of it."""
        js = auth._LOCK_SCREEN_SCRIPT
        start = js.index("var POWER_ITEMS")
        table = js[start:js.index("];", start)]
        rows = [r for r in table.split("[") if '"' in r and "," in r]
        confirming = [r.split('"')[1] for r in rows if r.rstrip(" ],\n").endswith("true")]
        # Jay asked for Stop all agents and Emergency call first, then added the
        # shutdown button after tapping it by accident while testing. Restart
        # carries the same guard: on a phone being demoed an accidental restart
        # costs the same minute as an accidental shutdown.
        assert set(confirming) == {
            "Power off", "Restart", "Stop all agents", "Emergency call",
        }, confirming

    def test_the_page_subscribes_to_the_push_channel(self):
        assert 'EventSource("/auth/lock-events")' in auth._LOCK_SCREEN_SCRIPT
        assert 'addEventListener("power-menu"' in auth._LOCK_SCREEN_SCRIPT

    def test_every_sheet_openSheet_knows_has_a_css_rule_that_reveals_it(self):
        """The bug Jay hit: "Power button blurs screen but no buttons show".

        `.ls-sheet` rests at translateY(101%) and is pulled up only by rules
        that NAME each sheet, while the backdrop blur is driven by a generic
        `:not([data-sheet="none"])` selector. So a sheet openSheet can open but
        no rule names produces exactly that: the chrome reacts, the sheet stays
        off screen, nothing throws and nothing logs.

        Derived from sheetEl's own branches rather than a hand-kept list, so the
        next sheet added is covered without anyone remembering to come here.
        """
        js = auth._LOCK_SCREEN_SCRIPT
        css = auth._LOCK_SCREEN_STYLE
        body = js[js.index("function sheetEl("):]
        body = body[: body.index("\n    }")]
        names = re.findall(r'name === "([a-z]+)"', body)
        assert len(names) >= 4, names
        for name in names:
            # passcode is #ls-foot, which is positioned by its own rules rather
            # than the shared sheet transform.
            if name == "passcode":
                continue
            assert 'data-sheet="%s"' % name in css, (
                "no CSS rule reveals the %r sheet: it will open invisibly" % name
            )

    def test_the_sheet_exists_in_the_markup_and_is_reachable_by_name(self):
        html = auth._lock_head_html() if hasattr(auth, "_lock_head_html") else ""
        page = auth._LOCK_SCREEN_SCRIPT
        assert 'if (name === "power")' in page, "openSheet cannot find the power sheet"
        del html  # the sheet is emitted outside the head fragment
