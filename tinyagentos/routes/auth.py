from __future__ import annotations

import html
import json
import socket
from pathlib import Path
import logging
import os
import threading
import time
from collections import OrderedDict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from tinyagentos.auth import (
    PIN_MAX_LEN,
    PIN_MIN_LEN,
    AuthStoreCorruptError,
    _PinAttemptLimiter,
    is_console_origin,
    validate_pin,
)
from tinyagentos.middleware.csrf import verify_csrf
from tinyagentos.routes.onscreen_keyboard import OSK_SCRIPT, osk_assets

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Brute-force rate limiter (in-memory, per-IP, fixed window)
# ---------------------------------------------------------------------------

_FAIL_COUNTER_MAX_KEYS = 10_000  # cap total tracked IPs to prevent unbounded growth


class _FailCounter:
    """Count failed attempts per key in a rolling window.

    Bounded to avoid memory leaks:
    - Expired entries (all timestamps outside the window) are dropped on access.
    - Total key count is capped at ``_FAIL_COUNTER_MAX_KEYS``; oldest-accessed
      entries are evicted first (LRU via OrderedDict).

    Thread-safe: all mutating operations are protected by a Lock.
    """

    def __init__(self, max_attempts: int = 5, window_seconds: int = 600):
        self._max = max_attempts
        self._window = window_seconds
        # key → list of failure timestamps; OrderedDict for LRU eviction
        self._log: OrderedDict[str, list[float]] = OrderedDict()
        self._lock = threading.Lock()

    def _prune(self, key: str) -> None:
        """Must be called with self._lock held."""
        cutoff = time.monotonic() - self._window
        if key not in self._log:
            return
        self._log[key] = [t for t in self._log[key] if t > cutoff]
        if not self._log[key]:
            # All timestamps expired — drop the entry entirely
            del self._log[key]
        else:
            # Keep active entry fresh in LRU order
            self._log.move_to_end(key)

    def _ensure_capacity(self) -> None:
        """Must be called with self._lock held."""
        while len(self._log) >= _FAIL_COUNTER_MAX_KEYS:
            self._log.popitem(last=False)  # evict oldest-accessed

    def is_limited(self, key: str) -> bool:
        with self._lock:
            self._prune(key)
            return len(self._log.get(key, [])) >= self._max

    def record_failure(self, key: str) -> None:
        with self._lock:
            self._prune(key)
            if key not in self._log:
                self._ensure_capacity()
                self._log[key] = []
            self._log[key].append(time.monotonic())
            self._log.move_to_end(key)

    def reset(self, key: str) -> None:
        with self._lock:
            self._log.pop(key, None)

    def count(self, key: str) -> int:
        """Current failure count for the key within the window."""
        with self._lock:
            self._prune(key)
            return len(self._log.get(key, []))


_login_limiter = _FailCounter(max_attempts=5, window_seconds=600)
_complete_limiter = _FailCounter(max_attempts=5, window_seconds=600)

# Hard ceiling: at/above this we reject BEFORE verifying the password, which
# bounds BOTH brute-force guesses and the bcrypt cost per window+IP. Kept just
# above the soft limit (5): a user who fat-fingers a few times then types the
# right password still gets in (within the first ~10 attempts), while an attacker
# is throttled to at most this many guesses+hashes per 10-minute window per IP.
# Letting a correct password through inherently requires checking it, so a small
# increase over the soft limit is the necessary cost of not locking out real
# users -- keep this tight, not large.
_LOGIN_HARD_MAX = 10
_LOCKOUT_MSG = "Too many failed attempts. Wait a few minutes, then sign in with your correct password."

# Self-contained HTML pages for the auth flow.
#
# These are deliberately JS-free and CDN-free so they work on any device
# even when the SPA bundle is broken or stale. After successful submit
# the server redirects to /desktop where the SPA takes over.
_AUTH_BASE_STYLE = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body {
  margin: 0;
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: env(safe-area-inset-top, 16px) env(safe-area-inset-right, 16px) env(safe-area-inset-bottom, 16px) env(safe-area-inset-left, 16px);
  background: linear-gradient(160deg, #141415 0%, #1a1a1d 45%, #202024 100%);
  color: rgba(255, 255, 255, 0.85);
  font: 14px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}
.card {
  width: 100%;
  max-width: 380px;
  padding: 28px 24px;
  border: 1px solid rgba(255,255,255,0.10);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.04);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
}
.brand {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  margin-bottom: 22px;
}
/* The on-screen keyboard takes roughly half of a 600px panel, so while it is
   open the card sheds decorative height to keep its actions above the keys.
   The body is scrollable in that state either way, but a sign-in the user has
   to scroll to reach is a sign-in a kiosk user will not find. */
body.osk-open .card { padding: 16px 20px 12px; }
body.osk-open label.field { margin-bottom: 6px; }
body.osk-open .brand { margin-bottom: 8px; gap: 6px; }
body.osk-open .brand h1.wordmark { font-size: 26px; }
body.osk-open .brand p { display: none; }
/* The wordmark IS the brand mark on these pages: the product name set as type,
   carrying the card visually on its own. It replaces an earlier drawn glyph —
   a rounded square with a centre dot and an X through it — which on a sign-in
   screen read as an error badge or a close affordance rather than a logo.
   Plain ASCII in the page's own font stack, so there is no webfont to fetch
   and no code point that can land as TOFU on a device missing a covering font,
   which is what the JS-free, CDN-free auth pages need. */
.brand h1.wordmark {
  margin: 0;
  font-size: 34px;
  font-weight: 600;
  letter-spacing: -0.02em;
  line-height: 1.1;
}
.brand p { margin: 0; font-size: 12px; color: rgba(255,255,255,0.5); text-align: center; }
label.field {
  display: block;
  margin-bottom: 12px;
}
label.field > span {
  display: block;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: rgba(255,255,255,0.4);
  margin-bottom: 4px;
}
input[type="text"], input[type="password"], input[type="email"] {
  width: 100%;
  padding: 10px 14px;
  border-radius: 10px;
  border: 1px solid rgba(255,255,255,0.10);
  background: #171717;
  color: rgba(255,255,255,0.85);
  font: inherit;
  outline: none;
}
input:focus { border-color: rgba(139,146,163,0.5); }
.field .hint {
  display: block;
  font-size: 10px;
  color: rgba(255,255,255,0.3);
  margin-top: 4px;
}
.checkbox {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: rgba(255,255,255,0.55);
  margin-top: 14px;
}
button[type="submit"] {
  width: 100%;
  margin-top: 18px;
  padding: 11px 14px;
  border: 0;
  border-radius: 10px;
  background: #8b92a3;
  color: #fff;
  font: inherit;
  font-weight: 600;
  cursor: pointer;
  transition: filter 120ms;
}
button[type="submit"]:hover { filter: brightness(1.1); }
button[type="submit"]:disabled { opacity: 0.4; cursor: not-allowed; }
.error {
  margin: 0 0 12px;
  padding: 10px 12px;
  border-radius: 8px;
  background: rgba(239, 68, 68, 0.15);
  border: 1px solid rgba(239, 68, 68, 0.3);
  color: #fca5a5;
  font-size: 12px;
  text-align: center;
}
"""


_PIN_PANEL_STYLE = """
.pin-panel { margin-bottom: 14px; }
.pin-panel[hidden], .pw-panel[hidden] { display: none; }
/* The error paragraph is a live region, so it has to exist before it has
   anything to say — but `.error` carries a red background and border, and an
   empty one renders as a bare red slab above the keypad on a page that has not
   failed at anything yet. */
#pin-error:empty { display: none; }
/* The primary action is type=button (a submit would post the password form),
   so it misses `button[type="submit"]` styling entirely and lands as a ~21px
   native button — on a touchscreen, under the 44px this keyboard's own floor
   requires. */
#pin-submit {
  width: 100%; margin-top: 6px; padding: 12px 14px; min-height: 44px;
  border: 0; border-radius: 10px;
  background: #8b92a3; color: #fff;
  font: inherit; font-weight: 600; cursor: pointer;
  transition: filter 120ms;
}
#pin-submit:hover { filter: brightness(1.1); }
#pin-submit:focus-visible { outline: 3px solid #4c9aff; outline-offset: 2px; }
.pin-dots { display: flex; gap: 10px; justify-content: center; margin: 8px 0 14px; }
body.osk-open .pin-dots { margin: 2px 0 8px; }
.pin-dot {
  width: 14px; height: 14px; border-radius: 50%;
  border: 1px solid rgba(255,255,255,0.45); background: transparent;
}
.pin-dot[data-filled="1"] { background: #4c9aff; border-color: #4c9aff; }
.method-switch {
  display: block; width: 100%; margin-top: 12px; padding: 12px;
  min-height: 44px; background: none; border: none; cursor: pointer;
  color: #9ecbff; font: inherit; text-decoration: underline;
}
.method-switch:focus-visible { outline: 3px solid #4c9aff; outline-offset: 2px; }
"""


# Phone lock-screen chrome. Only ever rendered for a console-local request that
# already qualifies for PIN sign-in, so a LAN browser still gets the plain card.
_LOCK_SCREEN_STYLE = """
/* A handset is tall, and a sign-in card floating in the middle of 2400px of
   glass reads as a web page, not as an OS. The lock screen splits the height
   the way iOS and Android do: status up top, passcode down by the thumb. */
/* display:block, NOT a flex row. The base stylesheet makes <body> a centring
   flex container for the sign-in card, and the on-screen keyboard appends its
   panel, toggle and live region to <body> -- under a flex ROW those become
   SIBLING FLEX ITEMS of the lock screen, squeezing it to a fraction of the
   width (its max-width never binds) and spilling a stray control above the
   clock. As a block the lock screen owns the full width and those appended
   elements sit out of flow where they belong. */
body.lockscreen-on {
  display: block; padding: 0; overflow: hidden;
  /* This is an OS screen, not a web page. Without these a press-and-hold on an
     island does what a browser does -- starts a text selection and raises the
     copy/share callout -- which is exactly the gesture the islands bind, so the
     long press fought the selection every time. Selection stays ON inside the
     conversation, where copying a message is a reasonable thing to want. */
  -webkit-user-select: none; user-select: none;
  -webkit-touch-callout: none;
}
.ls-msg, .ls-compose-input { -webkit-user-select: text; user-select: text; }
/* The on-screen keyboard's layout override (padding-bottom + flex-start) is for
   the password form. The lock screen carries its own keypad and never opens it,
   but be explicit so a stray .osk-open cannot re-anchor the screen to the top. */
body.lockscreen-on.osk-open { display: block; padding-bottom: 0 !important; overflow-y: hidden; }
.lockscreen {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100vh;
  height: 100dvh;
  padding: calc(env(safe-area-inset-top, 0px) + 7vh) 10px calc(env(safe-area-inset-bottom, 0px) + 18px);
  gap: 16px;
}
/* Top block: the glanceable half. */
.ls-head {
  display: flex; flex-direction: column; align-items: center; gap: 4px;
  align-self: stretch;
  /* min-height:0 so this block is allowed to shrink instead of pushing the
     keypad off-screen; a flex item's default min-height:auto refuses to. */
  min-height: 0;
}
.ls-time {
  font-size: clamp(56px, 17vw, 88px);
  font-weight: 250;
  line-height: 1;
  letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums;
  color: #fff;
}
.ls-date { font-size: 16px; font-weight: 500; color: rgba(255,255,255,0.62); }
.ls-widgets {
  display: flex; flex-wrap: wrap; justify-content: center; gap: 8px; margin-top: 18px;
}
/* Widgets are CLIENT-SIDE only (clock, battery) plus the device's own name.
   Nothing here reads the account or its data: this surface is shown BEFORE
   authentication, so anything account-derived would be a pre-auth leak. */
.ls-widget {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 7px 12px; border-radius: 999px;
  border: 1px solid rgba(255,255,255,0.10);
  background: rgba(255,255,255,0.05);
  font-size: 13px; color: rgba(255,255,255,0.70);
  backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px);
}
.ls-widget b { font-weight: 600; color: rgba(255,255,255,0.88); }
/* Agent islands. Each running agent is its own floating pill -- a row of
   identical cards would make three agents look like a list of settings; a
   detached island reads as a thing that is alive and can speak up on its own.
   Elevation is declared ONCE, as a shadow: no hairline border under it. */
.ls-islands {
  display: flex; flex-direction: column; align-items: center; gap: 14px;
  width: 100%; align-self: stretch; margin-top: 16px;
}
/* #ls-agents is the box the islands are appended INTO. Without a width of its
   own it is a shrink-to-fit block inside a centre-aligned flex column, so every
   island's width:100% and max-width resolved against its CONTENT box -- the cap
   could never bind and side padding changed nothing. It carries the stack. */
.ls-agents {
  display: flex; flex-direction: column; align-items: center; gap: 14px;
  width: 100%; align-self: stretch;
  /* The agent stack is the only part allowed to overflow, and it scrolls
     without a visible bar: a scrollbar on a lock screen reads as a web page. */
  min-height: 0;
  overflow-y: auto;
  scrollbar-width: none;
  -ms-overflow-style: none;
  overscroll-behavior: contain;
}
.ls-agents::-webkit-scrollbar { width: 0; height: 0; display: none; }
.ls-island {
  display: flex; align-items: center; gap: 10px;
  width: 100%; max-width: 396px;
  padding: 7px 16px 7px 7px;
  border-radius: 999px;
  background: rgba(30, 30, 34, 0.92);
  box-shadow: 0 6px 18px -6px rgba(0, 0, 0, 0.75);
  backdrop-filter: blur(24px) saturate(1.3);
  -webkit-backdrop-filter: blur(24px) saturate(1.3);
  /* Entrance: already-visible default, one authored moment, exponential ease. */
  animation: ls-island-in 520ms cubic-bezier(0.16, 1, 0.3, 1) backwards;
}
.ls-island:nth-child(2) { animation-delay: 70ms; }
.ls-island:nth-child(3) { animation-delay: 140ms; }
@keyframes ls-island-in {
  from { opacity: 0; transform: translateY(6px) scale(0.96); filter: blur(3px); }
  to   { opacity: 1; transform: none; filter: none; }
}
/* The avatar and the harness mark sit as a pair, the mark tucked over the
   avatar's edge the way a platform badge does -- two separate circles side by
   side read as two unrelated buttons. */
.ls-marks { position: relative; flex: none; width: 52px; height: 34px; }
.ls-avatar {
  position: absolute; inset: 0 auto 0 0;
  width: 34px; height: 34px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 13px; font-weight: 600; letter-spacing: 0.01em; color: #fff;
  background: linear-gradient(145deg, var(--ls-a, #4c9aff), var(--ls-b, #2f6fd0));
}
.ls-fw {
  position: absolute; right: 0; bottom: -1px;
  width: 22px; height: 22px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  background: #0f0f12;
  /* The ring is the separation from the avatar behind it, not decoration. */
  box-shadow: 0 0 0 2px rgba(30, 30, 34, 0.92);
  color: rgba(255, 255, 255, 0.86);
}
.ls-fw svg { width: 15px; height: 15px; }
/* A real store logo fills the badge; the drawn marks are inset because they are
   line art and need the breathing room a solid mark does not. */
.ls-fw-img { background: #fff; overflow: hidden; }
.ls-fw-img img { width: 100%; height: 100%; object-fit: cover; display: block; }
/* A photo fills the circle edge to edge; the monogram gradient stays behind it
   as the loading ground rather than a grey box. */
.ls-avatar-img { width: 100%; height: 100%; border-radius: 50%; object-fit: cover; display: block; }
/* The OS's own agent carries the product mark. A mark is not a portrait: no
   circular crop, no gradient ground and no monogram behind it -- those exist to
   make arbitrary photos and initials sit together, and cropping a landscape
   wordmark into a 34px circle would cut the word in half. It gets a wider slot
   and is contained inside it, while the harness badge stays exactly where it is
   on every other island. */
/* Same circle, same size as every other avatar -- a row of pills whose first
   mark is a different shape and size reads as a mis-render, not as emphasis.
   The only differences are the ground (a flat dark disc rather than the
   per-name gradient, which is there to make INITIALS legible) and `contain`,
   because the wordmark is landscape and `cover` would crop it to "aO". */
.ls-island[data-system="1"] .ls-avatar { background: #0f0f12; }
.ls-island[data-system="1"] .ls-avatar-img { object-fit: contain; }
.ls-sprite { position: absolute; width: 0; height: 0; overflow: hidden; }
/* One stroke weight and one cap style across the marks. */
.ls-fw svg, .ls-sprite {
  fill: none; stroke: currentColor; stroke-width: 1.7;
  stroke-linecap: round; stroke-linejoin: round;
}
.ls-body { min-width: 0; flex: 1 1 auto; }
.ls-name {
  font-size: 13.5px; font-weight: 600; color: rgba(255,255,255,0.92);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  letter-spacing: -0.01em;
}
.ls-status {
  font-size: 11.5px; color: rgba(255,255,255,0.52);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
/* Live pip: present only while the agent is actually doing something. */
.ls-pip {
  flex: none; width: 7px; height: 7px; border-radius: 50%;
  background: #3ddc84;
}
.ls-island[data-state="idle"] .ls-pip { background: rgba(255,255,255,0.28); }
/* ATTENTION. The island itself breathes -- a ring that grows out of its own
   silhouette, so it is legible from across a room without reading a word. */
.ls-island[data-attention="1"] {
  animation: ls-island-in 520ms cubic-bezier(0.16, 1, 0.3, 1) backwards,
             ls-attention 2.6s ease-out 520ms infinite;
}
.ls-island[data-attention="1"] .ls-pip { background: #ffb020; }
.ls-island[data-attention="1"] .ls-status { color: rgba(255, 176, 32, 0.92); }
@keyframes ls-attention {
  0%   { box-shadow: 0 6px 18px -6px rgba(0,0,0,0.75), 0 0 0 0 rgba(255,176,32,0.45); }
  70%  { box-shadow: 0 6px 18px -6px rgba(0,0,0,0.75), 0 0 0 10px rgba(255,176,32,0); }
  100% { box-shadow: 0 6px 18px -6px rgba(0,0,0,0.75), 0 0 0 0 rgba(255,176,32,0); }
}
@media (prefers-reduced-motion: reduce) {
  .ls-island, .ls-island[data-attention="1"] { animation: none; }
  .ls-island[data-attention="1"] { outline: 2px solid rgba(255,176,32,0.7); outline-offset: 2px; }
}
/* Scheduled tasks stay quieter than the agents: they are context, not actors. */
.ls-tasks { width: 100%; align-self: stretch; }
.ls-tasks:not(:empty) {
  display: flex; flex-direction: column; align-items: center; gap: 4px;
  margin-top: 6px; width: 100%;
}
.ls-task {
  display: flex; justify-content: space-between; gap: 10px;
  padding: 0 18px; font-size: 11.5px; color: rgba(255,255,255,0.42);
}
.ls-task-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ls-empty { font-size: 13px; color: rgba(255,255,255,0.40); padding: 2px 0; }
/* The spacer, not a margin: it collapses first when the viewport is short, so
   the keypad stays reachable on a small phone instead of being pushed off. */
.ls-spacer { flex: 1 1 auto; min-height: 8px; }
.ls-foot { display: flex; flex-direction: column; align-items: center; gap: 10px; align-self: stretch; flex: none; }
.ls-hint { margin: 0; font-size: 14px; color: rgba(255,255,255,0.55); }
/* Keypad: 3 columns, targets well above the 44px minimum because this is the
   one control on the device that must work with a thumb, in the dark. */
.ls-pad {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
  width: 100%;
  max-width: 300px;
  margin-top: 4px;
}
.ls-key {
  aspect-ratio: 1 / 1;
  max-height: 74px;
  border-radius: 50%;
  border: 1px solid rgba(255,255,255,0.10);
  background: rgba(255,255,255,0.07);
  color: #fff;
  font: 300 30px/1 inherit;
  font-variant-numeric: tabular-nums;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
  transition: background 90ms ease, transform 90ms ease;
}
.ls-key:active { background: rgba(255,255,255,0.20); transform: scale(0.94); }
.ls-key:focus-visible { outline: 3px solid #4c9aff; outline-offset: 2px; }
/* Backspace and the password escape are actions, not digits: no filled pill, so
   the ten digits stay the obvious targets. */
.ls-key[data-action] { background: none; border-color: transparent; font-size: 22px; }
.ls-key[data-action]:active { background: rgba(255,255,255,0.12); }
.ls-key.ls-key-blank { visibility: hidden; pointer-events: none; }
/* The lock screen supplies its own dots/keypad, so the card chrome that the
   plain sign-in page needs is not wanted here. */
.lockscreen .pin-panel:not([hidden]) { display: contents; }
.lockscreen #pin-submit {
  width: 100%; max-width: 300px; margin-top: 4px;
  border-radius: 999px; background: rgba(255,255,255,0.14);
  border: 1px solid rgba(255,255,255,0.12); color: #fff;
}
.lockscreen .pin-panel label.field { display: none; }
.lockscreen .pin-dots { margin: 0; }
.lockscreen .pin-dot { width: 12px; height: 12px; }
.lockscreen .error { margin: 0; min-height: 18px; text-align: center; }
.lockscreen .method-switch { margin-top: 2px; }
.lockscreen .pw-panel { width: 100%; max-width: 320px; }
/* No keyboard and no keyboard BUTTON on the passcode screen: the keypad is the
   only input this screen takes, and a floating keyboard FAB over a lock screen
   reads as a stray browser control. The toggle comes back with the password
   form, which does need typing -- lock-screen.js drops .lockscreen-on when the
   user switches to it. */
body.lockscreen-on .osk-toggle { display: none; }
/* ---------------------------------------------------------------------------
   SHEETS. The lock screen has one resting state and three things that can rise
   over it: the passcode, an agent conversation and a decision. They are all the
   same object -- a bottom sheet -- so they share geometry, scrim and dismissal
   and differ only in content.

   data-sheet on .lockscreen is the single source of truth for which one is up.
   Everything else (the scrim, the blur, the unlock bar, which sheet is
   translated into view) is derived from it, so there is no state to get out of
   sync and no way to have two sheets open at once.
   --------------------------------------------------------------------------- */
.lockscreen { position: relative; }
/* The resting screen: no passcode, no keypad. Same reasoning as a phone --
   the glanceable half is what the screen is FOR, and the way in is one
   affordance at the bottom rather than a permanent keypad.

   The passcode shell is taken OUT OF FLOW to do this. Translating it while it
   still occupied its row would leave a keypad-sized hole above the unlock bar,
   pushing the bar into the middle of the screen; as a fixed sheet it shares the
   geometry of the other two and the resting layout is simply head + unlock. */
.lockscreen .ls-foot {
  position: fixed; left: 0; right: 0; bottom: var(--ls-kb, 0px); z-index: 50;
  width: 100%; max-width: 520px; margin: 0 auto;
  max-height: min(88dvh, 720px);
  padding: 14px 14px calc(env(safe-area-inset-bottom, 0px) + 18px);
  border-radius: 26px 26px 0 0;
  background: rgba(24, 24, 27, 0.86);
  backdrop-filter: blur(34px) saturate(1.4);
  -webkit-backdrop-filter: blur(34px) saturate(1.4);
  box-shadow: 0 -12px 40px -12px rgba(0,0,0,0.8);
}
.lockscreen:not([data-sheet="passcode"]) .ls-foot {
  transform: translateY(101%);
  pointer-events: none;
}
/* The head recedes while a sheet is up: blurred and slightly shrunk, so the
   sheet reads as being IN FRONT rather than as a panel pasted on. */
.lockscreen:not([data-sheet="none"]) .ls-head {
  filter: blur(7px);
  transform: scale(0.965);
  opacity: 0.55;
  pointer-events: none;
}
.ls-head {
  transition: filter 320ms cubic-bezier(0.32, 0.72, 0, 1),
              transform 320ms cubic-bezier(0.32, 0.72, 0, 1),
              opacity 320ms ease;
  will-change: filter, transform;
}
/* The scrim darkens what is behind the sheet AND is the tap-to-dismiss target,
   so a sheet can always be closed by tapping away from it. */
.ls-scrim {
  position: fixed; inset: 0; z-index: 40;
  background: rgba(0, 0, 0, 0.42);
  opacity: 0;
  transition: opacity 320ms ease;
}
.lockscreen:not([data-sheet="none"]) ~ .ls-scrim,
.ls-scrim[data-on="1"] { opacity: 1; }
.ls-scrim[hidden] { display: none; }

/* The way in. A real button, not a swipe-only gesture: a screen whose only
   unlock is a drag is unusable to anyone who cannot make that drag, and a
   kiosk has no other way in. The swipe is the shortcut, the button is the
   guarantee. */
.ls-unlock {
  display: flex; flex-direction: column; align-items: center; gap: 2px;
  align-self: stretch; flex: none;
  padding-bottom: 2px;
  transition: opacity 240ms ease, transform 240ms ease;
}
.lockscreen:not([data-sheet="none"]) .ls-unlock {
  opacity: 0; transform: translateY(12px); pointer-events: none;
}
.ls-unlock-btn {
  display: flex; flex-direction: column; align-items: center; gap: 10px;
  width: 100%; padding: 14px 0 6px;
  background: none; border: 0; color: inherit; font: inherit;
  cursor: pointer; -webkit-tap-highlight-color: transparent;
}
.ls-unlock-btn:focus-visible { outline: 3px solid #4c9aff; outline-offset: 4px; border-radius: 16px; }
.ls-unlock-label {
  font-size: 13.5px; font-weight: 500; letter-spacing: 0.01em;
  color: rgba(255,255,255,0.62);
}
/* The home-indicator bar. It breathes upward once every few seconds -- the
   hint that the gesture goes UP, without a word of instruction. */
.ls-grabber {
  display: block; width: 116px; height: 5px; border-radius: 999px;
  background: rgba(255,255,255,0.42);
}
.ls-unlock-btn .ls-grabber { animation: ls-nudge 3.4s ease-in-out infinite; }
@keyframes ls-nudge {
  0%, 62%, 100% { transform: translateY(0); opacity: 0.55; }
  74%           { transform: translateY(-5px); opacity: 1; }
}

/* Shared sheet geometry. Fixed to the bottom edge so the keyboard, the scrim
   and the sheet all reference the same edge; --ls-kb is the measured height of
   the on-screen keyboard, so a raised keyboard lifts the sheet instead of
   burying its input. */
.ls-sheet {
  position: fixed; left: 0; right: 0; bottom: var(--ls-kb, 0px); z-index: 50;
  display: flex; flex-direction: column;
  max-height: min(76dvh, 640px);
  margin: 0 auto; width: 100%; max-width: 520px;
  padding: 8px 14px calc(env(safe-area-inset-bottom, 0px) + 14px);
  border-radius: 26px 26px 0 0;
  background: rgba(24, 24, 27, 0.86);
  backdrop-filter: blur(34px) saturate(1.4);
  -webkit-backdrop-filter: blur(34px) saturate(1.4);
  box-shadow: 0 -12px 40px -12px rgba(0,0,0,0.8);
  transform: translateY(101%);
  transition: transform 380ms cubic-bezier(0.32, 0.72, 0, 1), bottom 180ms ease;
}
.ls-sheet[hidden] { display: none; }
.lockscreen[data-sheet="chat"] ~ #ls-chat,
.lockscreen[data-sheet="decision"] ~ #ls-decision { transform: translateY(0); }
/* The passcode sheet is the sign-in shell itself, so it gets the same motion
   rather than a second implementation of "a sheet". */
.lockscreen .ls-foot {
  transition: transform 380ms cubic-bezier(0.32, 0.72, 0, 1), bottom 180ms ease;
}
.ls-sheet-head {
  display: grid; grid-template-columns: 1fr auto; align-items: center;
  gap: 10px; padding: 0 2px 10px;
}
.ls-sheet-head .ls-grabber {
  grid-column: 1 / -1; justify-self: center; margin: 2px 0 12px;
}
.ls-sheet-title { display: flex; align-items: center; gap: 10px; min-width: 0; }
.ls-sheet-avatar {
  flex: none; width: 38px; height: 38px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 14px; font-weight: 600; color: #fff; overflow: hidden;
  background: linear-gradient(145deg, var(--ls-a, #4c9aff), var(--ls-b, #2f6fd0));
}
.ls-sheet-avatar img { width: 100%; height: 100%; object-fit: cover; display: block; }
.ls-sheet-avatar[data-system="1"] { background: #0f0f12; }
.ls-sheet-avatar[data-system="1"] img { object-fit: contain; }
.ls-sheet-name {
  font-size: 15px; font-weight: 600; color: rgba(255,255,255,0.94);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.ls-sheet-sub { font-size: 11.5px; color: rgba(255,255,255,0.48); }
.ls-sheet-close {
  flex: none; width: 32px; height: 32px; border-radius: 50%;
  border: 0; background: rgba(255,255,255,0.10); color: rgba(255,255,255,0.75);
  font-size: 15px; line-height: 1; cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}
.ls-sheet-close:active { background: rgba(255,255,255,0.20); }
.ls-sheet-close:focus-visible { outline: 3px solid #4c9aff; outline-offset: 2px; }

/* Conversation. Scrolls on its own so the composer never leaves the thumb. */
.ls-msgs {
  flex: 1 1 auto; min-height: 0; overflow-y: auto;
  display: flex; flex-direction: column; gap: 5px;
  padding: 2px 2px 10px;
  scrollbar-width: none; -ms-overflow-style: none;
  overscroll-behavior: contain;
}
.ls-msgs::-webkit-scrollbar { width: 0; height: 0; display: none; }
.ls-day {
  align-self: center; margin: 12px 0 6px;
  font-size: 11px; font-weight: 600; letter-spacing: 0.04em;
  text-transform: uppercase; color: rgba(255,255,255,0.34);
}
.ls-msg {
  max-width: 82%; padding: 9px 13px; border-radius: 19px;
  font-size: 14.5px; line-height: 1.38;
  overflow-wrap: anywhere;
  animation: ls-msg-in 260ms cubic-bezier(0.16, 1, 0.3, 1) backwards;
}
@keyframes ls-msg-in {
  from { opacity: 0; transform: translateY(6px) scale(0.98); }
  to   { opacity: 1; transform: none; }
}
/* The two voices are told apart by SIDE and GROUND, not by a label: a name on
   every bubble is noise in a conversation with exactly two participants. */
.ls-msg[data-role="agent"] {
  align-self: flex-start; border-bottom-left-radius: 7px;
  background: rgba(255,255,255,0.10); color: rgba(255,255,255,0.92);
}
.ls-msg[data-role="user"] {
  align-self: flex-end; border-bottom-right-radius: 7px;
  background: #0a84ff; color: #fff;
}
/* Consecutive bubbles from the same voice tighten into one group. */
.ls-msg[data-role="agent"] + .ls-msg[data-role="agent"] { border-bottom-left-radius: 19px; margin-top: -2px; }
.ls-msg[data-role="user"] + .ls-msg[data-role="user"] { border-bottom-right-radius: 19px; margin-top: -2px; }
.ls-compose { display: flex; align-items: flex-end; gap: 8px; padding-top: 4px; }
.ls-compose-input {
  flex: 1 1 auto; min-width: 0;
  padding: 11px 15px; border-radius: 22px;
  border: 1px solid rgba(255,255,255,0.12);
  background: rgba(255,255,255,0.07);
  color: #fff; font: inherit; font-size: 15px;
}
.ls-compose-input::placeholder { color: rgba(255,255,255,0.38); }
.ls-compose-input:focus { outline: none; border-color: rgba(255,255,255,0.28); }
.ls-send {
  flex: none; width: 40px; height: 40px; border-radius: 50%;
  border: 0; background: #0a84ff; color: #fff; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  -webkit-tap-highlight-color: transparent;
  transition: opacity 140ms ease, transform 90ms ease;
}
.ls-send:disabled { opacity: 0.35; cursor: default; }
.ls-send:not(:disabled):active { transform: scale(0.92); }
.ls-send:focus-visible { outline: 3px solid #4c9aff; outline-offset: 2px; }
.ls-send svg { width: 19px; height: 19px; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }

/* Decision. Short by design: a question, what it is worth knowing, two ways
   out. Anything longer belongs in the Decisions app behind the passcode. */
.ls-decision-body { padding: 4px 4px 16px; }
.ls-decision-q {
  font-size: 19px; line-height: 1.32; font-weight: 500;
  letter-spacing: -0.01em; color: #fff; margin: 0 0 8px;
}
.ls-decision-meta { font-size: 12.5px; color: rgba(255,255,255,0.46); margin: 0; }
.ls-decision-note {
  margin: 14px 0 0; padding: 10px 12px; border-radius: 12px;
  background: rgba(255,176,32,0.10);
  font-size: 12.5px; line-height: 1.45; color: rgba(255,196,96,0.92);
}
.ls-decision-acts { display: flex; gap: 10px; padding-top: 4px; }
.ls-act {
  flex: 1 1 0; padding: 14px 10px; border-radius: 16px;
  border: 1px solid rgba(255,255,255,0.12);
  font: inherit; font-size: 15px; font-weight: 600; color: #fff;
  background: rgba(255,255,255,0.08); cursor: pointer;
  -webkit-tap-highlight-color: transparent;
  transition: transform 90ms ease, background 140ms ease;
}
.ls-act:active { transform: scale(0.97); }
.ls-act:focus-visible { outline: 3px solid #4c9aff; outline-offset: 2px; }
.ls-act[data-act="approve"] { background: #1f8f4e; border-color: transparent; }
.ls-act[data-act="deny"] { background: rgba(255,255,255,0.09); }
.ls-decision-done {
  padding: 10px 4px 6px; text-align: center;
  font-size: 14px; color: rgba(255,255,255,0.72);
}

/* Force-touch feel: the island sinks under the finger, then pops as it opens.
   Without the sink there is no feedback that a HOLD is doing anything, and the
   gesture reads as an unresponsive tap. */
.ls-island { cursor: pointer; -webkit-tap-highlight-color: transparent; transition: transform 160ms cubic-bezier(0.32, 0.72, 0, 1); }
.ls-island[data-press="1"] { transform: scale(0.955); }
.ls-island[data-press="2"] { transform: scale(1.035); transition-duration: 220ms; }
.ls-island:focus-visible { outline: 3px solid #4c9aff; outline-offset: 3px; }

@media (prefers-reduced-motion: reduce) {
  .ls-sheet, .ls-foot, .ls-head, .ls-unlock, .ls-scrim, .ls-island { transition: none; }
  .ls-msg { animation: none; }
  .ls-unlock-btn .ls-grabber { animation: none; }
  .lockscreen:not([data-sheet="none"]) .ls-head { filter: none; }
}
/* Landscape: the keypad and the clock sit side by side or neither fits. */
@media (orientation: landscape) and (max-height: 560px) {
  .lockscreen { flex-direction: row; align-items: center; gap: 24px; padding-top: 12px; }
  .ls-head { flex: 1 1 0; }
  .ls-spacer { display: none; }
  /* .ls-foot is a fixed bottom sheet, not a flex child, so it needs a height
     cap here rather than a flex ratio: at this height the keypad must scroll
     inside the sheet instead of growing past the top of the screen. */
  .lockscreen .ls-foot { max-height: 92dvh; overflow-y: auto; }
  .ls-sheet { max-height: 88dvh; }
  .ls-time { font-size: clamp(40px, 9vw, 64px); }
  .ls-widgets { margin-top: 10px; }
  .ls-key { max-height: 52px; }
}
"""

# Plain (non-f) string: interpolated into the page as a value, so braces here
# must not be doubled.
_PIN_PANEL_SCRIPT = r"""
(function () {
  "use strict";
  // Deferred to DOMContentLoaded on purpose. This script is inline and runs
  // during parsing, but the on-screen keyboard appends its panel on
  // DOMContentLoaded -- so calling taosOSK.enable() here at parse time would
  // "show" a panel that is not in the document yet and the keypad would never
  // appear. The OSK block is emitted BEFORE this one, so its listener is
  // registered first and has already run by the time we get here.
  function init() {
  var pinPanel = document.getElementById("pin-panel");
  var pwPanel  = document.getElementById("pw-panel");
  if (!pinPanel || !pwPanel) return;

  var input   = document.getElementById("pin-input");
  var dots    = document.getElementById("pin-dots");
  var err     = document.getElementById("pin-error");
  var submit  = document.getElementById("pin-submit");
  var toPw    = document.getElementById("use-password");
  var toPin   = document.getElementById("use-pin");
  var nextUrl = pinPanel.getAttribute("data-next") || "/desktop";
  var user    = pinPanel.getAttribute("data-username") || "";
  var busy    = false;

  function paint() {
    var n = input.value.length;
    var kids = dots.children;
    for (var i = 0; i < kids.length; i++) {
      kids[i].setAttribute("data-filled", i < n ? "1" : "0");
    }
  }

  input.addEventListener("input", function () {
    // Digits only: the keypad cannot produce anything else, but a physical
    // keyboard can, and a stray letter would fail server-side validation with
    // a confusing "incorrect PIN".
    input.value = input.value.replace(/\D/g, "");
    paint();
    err.textContent = "";
  });

  function fail(msg) {
    err.textContent = msg;
    input.value = "";
    paint();
  }

  submit.addEventListener("click", function () {
    if (busy) return;
    var pin = input.value;
    if (pin.length < 4) { fail("Enter your PIN."); return; }
    busy = true;
    fetch("/auth/pin-login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: user || undefined, pin: pin })
    }).then(function (r) {
      return r.json().then(function (body) { return { status: r.status, body: body }; });
    }).then(function (res) {
      busy = false;
      if (res.status === 200 && res.body && res.body.ok) {
        window.location.assign(nextUrl);
        return;
      }
      // 404 means PIN sign-in is not available from here at all; say so plainly
      // rather than leaving the user tapping at a keypad that cannot work.
      if (res.status === 404) {
        fail("PIN sign-in is not available on this device. Use your password.");
        return;
      }
      // Read `detail` as well as `error`: a FastAPI HTTPException raised by a
      // dependency (rather than returned by the handler) serialises as
      // {"detail": ...}, and blaming the PIN for a failure that had nothing to
      // do with it strands a kiosk user with no way to tell what is wrong.
      var reason = res.body && (res.body.error || res.body.detail);
      fail(reason || "Sign-in failed. Try again, or use your password.");
    }).catch(function () {
      busy = false;
      fail("Could not reach taOS. Check the connection and try again.");
    });
  });

  function swap(showPin) {
    pinPanel.hidden = !showPin;
    pwPanel.hidden = showPin;
    err.textContent = "";
    if (showPin) {
      input.value = "";
      paint();
      // The lock screen draws its own keypad (#ls-pad), so the shared keyboard
      // must stay shut: enabling it here opened a full QWERTY over the passcode
      // pad and covered the lower third of the phone. Only the page WITHOUT a
      // keypad needs the shared keyboard to type a PIN at all.
      if (document.getElementById("ls-pad")) {
        if (window.taosOSK) window.taosOSK.disable();
      } else if (window.taosOSK) {
        window.taosOSK.enable();
        window.taosOSK.focusField(input);
      } else {
        input.focus();
      }
    } else {
      var pw = pwPanel.querySelector("input[type=password]");
      if (pw && window.taosOSK) window.taosOSK.focusField(pw);
      else if (pw) pw.focus();
    }
  }

  if (toPw)  toPw.addEventListener("click", function () { swap(false); });
  if (toPin) toPin.addEventListener("click", function () { swap(true); });

  // PROGRESSIVE ENHANCEMENT, and it is load-bearing. The server renders the
  // PASSWORD form visible and the PIN panel hidden; only here, once every
  // element resolved and the handlers are attached, do we swap to the PIN
  // view. Hiding the password form server-side instead would brick the console
  // whenever this file does not run -- a CSP refusal, a cache miss, JS off --
  // leaving a keypad that cannot submit and no other way in. That is the exact
  // lockout PIN sign-in was built to remove, so it must not be reintroduced by
  // the fix. swap(true) also opens the keypad, which is the whole point on a
  // keyboard-less panel: the user should not have to find a toggle first.
  swap(true);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
"""



#: The lock-screen keypad. A plain grid of buttons rather than a re-use of the
#: shared on-screen keyboard: that one is a full text keyboard docked to the
#: bottom of the viewport, and a passcode pad wants ten large round targets
#: under the thumb. Digits carry aria-labels because the visible glyph alone is
#: ambiguous to a screen reader announcing a grid of buttons.
_KEYPAD_HTML = """
      <div class="ls-pad" id="ls-pad" role="group" aria-label="PIN keypad">
        <button type="button" class="ls-key" data-digit="1">1</button>
        <button type="button" class="ls-key" data-digit="2">2</button>
        <button type="button" class="ls-key" data-digit="3">3</button>
        <button type="button" class="ls-key" data-digit="4">4</button>
        <button type="button" class="ls-key" data-digit="5">5</button>
        <button type="button" class="ls-key" data-digit="6">6</button>
        <button type="button" class="ls-key" data-digit="7">7</button>
        <button type="button" class="ls-key" data-digit="8">8</button>
        <button type="button" class="ls-key" data-digit="9">9</button>
        <span class="ls-key ls-key-blank" aria-hidden="true"></span>
        <button type="button" class="ls-key" data-digit="0">0</button>
        <button type="button" class="ls-key" data-action="back" aria-label="Delete">&#9003;</button>
      </div>
"""


def _pin_panel_html(next_url: str, keypad: bool = False) -> str:
    """The PIN entry panel, shown only when the request is console-local.

    Rendered HIDDEN. /auth/pin-panel.js reveals it (and hides the password
    form) once it has wired itself up; see the note on the swap in that script.
    """
    safe_next = html.escape(next_url or "/desktop")
    # The lock screen draws its own keypad, so the shared on-screen keyboard must
    # not also open: two keypads fight for the same input, and the OSK's layout
    # override top-anchors the screen. inputmode="none" also stops the
    # compositor's Wayland keyboard (squeekboard) from appearing over the pad.
    osk_mode = "none" if keypad else "numeric"
    osk_attr = "" if keypad else 'data-osk-submit="pin-submit"'
    keypad_html = _KEYPAD_HTML if keypad else ""

    # No username is sent with a PIN: this panel is only ever rendered for a
    # single-user store, because AuthManager.has_pin(None) refuses to guess
    # which account a PIN belongs to on a multi-user one.
    return f"""
    <div class="pin-panel" id="pin-panel" data-next="{safe_next}" data-username="" hidden>
      <label class="field">
        <span>PIN</span>
        <input type="password" id="pin-input" inputmode="{osk_mode}" autocomplete="off"
               {osk_attr} aria-describedby="pin-error"
               maxlength="12" required>
      </label>
      <div class="pin-dots" id="pin-dots" aria-hidden="true">
        <span class="pin-dot"></span><span class="pin-dot"></span>
        <span class="pin-dot"></span><span class="pin-dot"></span>
      </div>
      <p class="error" id="pin-error" role="alert"></p>
      {keypad_html}
      <button type="button" id="pin-submit">Sign in with PIN</button>
      <button type="button" class="method-switch" id="use-password">
        Use my password instead
      </button>
    </div>
    """




#: Framework marks, drawn as geometry rather than shipped as logo files: the
#: lock screen must render with no network and no asset pipeline, and a glyph or
#: emoji standing in for an icon set is not an icon set. One stroke weight and
#: one cap style across all three so they read as a family at 18px. These are
#: stylised marks for the harness a taOS agent runs on, not the vendors' logos.
_FRAMEWORK_SPRITE = """
      <svg class="ls-sprite" aria-hidden="true" focusable="false" width="0" height="0">
        <defs>
          <symbol id="fw-hermes" viewBox="0 0 24 24">
            <!-- winged helm: a dome with two upswept wings -->
            <path d="M7.5 15.5a4.5 4.5 0 0 1 9 0" />
            <path d="M6 15.5h12" />
            <path d="M16.5 11.5c1.6-1.1 3-1.4 4.5-1.1-1 1.3-2.3 2.2-4 2.6" />
            <path d="M7.5 11.5C5.9 10.4 4.5 10.1 3 10.4c1 1.3 2.3 2.2 4 2.6" />
          </symbol>
          <symbol id="fw-openclaw" viewBox="0 0 24 24">
            <!-- three tapered talons converging on a palm arc -->
            <path d="M8 4.5v7" />
            <path d="M12 3.5v8" />
            <path d="M16 4.5v7" />
            <path d="M6.5 11.5a5.5 5.5 0 0 0 11 0" />
          </symbol>
          <symbol id="fw-deepseek" viewBox="0 0 24 24">
            <!-- breaching whale: body arc, tail fluke, spout -->
            <path d="M3.5 14.5c3.2 2.6 7.2 3.4 11 2.1 2.6-.9 4.4-2.8 5.2-5.4" />
            <path d="M19.7 11.2c.9.5 1.4 1.4 1.3 2.5-1-.3-1.8-.9-2.3-1.7" />
            <path d="M8.2 16.8c-.6 1.2-1.7 2-3.1 2.2.2-1.3.9-2.3 2-2.9" />
            <path d="M12.5 9.2c.6-1.2 1.6-2 3-2.3" />
          </symbol>
          <symbol id="fw-omp" viewBox="0 0 24 24">
            <!-- OMP is "oh-my-pi" and ships no logo of its own, so this is an
                 AUTHORED mark in the same line-art set as the others, not a
                 vendor logo: a pi glyph, its legs standing on a base rule. -->
            <path d="M5.5 7.5h13" />
            <path d="M9 7.5v9" />
            <path d="M15 7.5v7a2 2 0 0 0 2.8 1.8" />
            <path d="M6 16.5h6" />
          </symbol>
        </defs>
      </svg>
"""


def _device_label() -> str:
    """The handset's own name, for the lock-screen chip.

    Falls back to the product name: a lock screen that renders an empty chip
    because the host has no resolvable name looks broken, and the name is
    cosmetic here.
    """
    try:
        name = socket.gethostname().split(".")[0].strip()
    except OSError:
        name = ""
    return name or "taOS"


def _lock_head_html() -> str:
    """Opening half of the lock screen: clock, date and the widget row.

    Emitted as the page's first element and closed by the caller, so the
    passcode shell below it is the SAME markup the plain card path renders --
    the lock screen is chrome around the sign-in, not a second implementation
    of it.

    The clock renders empty and is filled by /auth/lock-screen.js: a
    server-rendered time would be the SERVER's clock and, worse, frozen at page
    load, so a phone left on the lock screen would show a stale time.
    """
    return f"""
  <div class="lockscreen" id="lockscreen">
    <div class="ls-head">
      <div class="ls-time" id="ls-time" role="timer" aria-live="off">&nbsp;</div>
      <div class="ls-date" id="ls-date"></div>
      <div class="ls-widgets" id="ls-widgets">
        <span class="ls-widget"><b>taOS</b>&nbsp;{html.escape(_device_label())}</span>
        <span class="ls-widget" id="ls-battery" hidden></span>
      </div>
      <div class="ls-islands" id="ls-activity" role="group" aria-label="Agent activity" hidden>
        <div class="ls-agents" id="ls-agents"></div>
        <div class="ls-tasks" id="ls-tasks"></div>
      </div>
      {_FRAMEWORK_SPRITE}
    </div>
    <div class="ls-spacer"></div>
    <div class="ls-unlock" id="ls-unlock">
      <button type="button" class="ls-unlock-btn" id="ls-unlock-btn"
              aria-expanded="false" aria-controls="ls-foot">
        <span class="ls-grabber"></span>
        <span class="ls-unlock-label">Swipe up to unlock</span>
      </button>
    </div>"""


def _lock_tail_html() -> str:
    """Closing half: the scrim and the two sheets that rise over the screen.

    Emitted AFTER </div> so the sheets are siblings of .lockscreen, not children
    of it. That matters: the head is blurred while a sheet is open, and a child
    would inherit that filter -- a blurred conversation is not a conversation.
    A filter on an ancestor also establishes a containing block, which would
    pin these fixed sheets to the lock screen's box instead of the viewport.

    Both sheets are rendered empty and hidden. They are console-only chrome, and
    everything inside them is written by /auth/lock-screen.js from data the
    server only serves to the device's own screen.
    """
    return """</div>
  <div class="ls-scrim" id="ls-scrim" hidden></div>
  <section class="ls-sheet" id="ls-chat" role="dialog" aria-modal="true"
           aria-labelledby="ls-chat-name" hidden>
    <header class="ls-sheet-head">
      <span class="ls-grabber"></span>
      <div class="ls-sheet-title">
        <div class="ls-sheet-avatar" id="ls-chat-avatar" aria-hidden="true"></div>
        <div>
          <div class="ls-sheet-name" id="ls-chat-name"></div>
          <div class="ls-sheet-sub" id="ls-chat-sub"></div>
        </div>
      </div>
      <button type="button" class="ls-sheet-close" id="ls-chat-close" aria-label="Close conversation">&#10005;</button>
    </header>
    <div class="ls-msgs" id="ls-msgs" role="log" aria-live="polite" tabindex="0"></div>
    <div class="ls-compose">
      <input type="text" class="ls-compose-input" id="ls-compose-input"
             placeholder="Message" autocomplete="off" autocapitalize="sentences"
             aria-label="Message" data-osk-submit="ls-send" maxlength="500">
      <button type="button" class="ls-send" id="ls-send" aria-label="Send message" disabled>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12h15M13 6l6 6-6 6"/></svg>
      </button>
    </div>
  </section>
  <section class="ls-sheet" id="ls-decision" role="dialog" aria-modal="true"
           aria-labelledby="ls-decision-q" hidden>
    <header class="ls-sheet-head">
      <span class="ls-grabber"></span>
      <div class="ls-sheet-title">
        <div class="ls-sheet-avatar" id="ls-decision-avatar" aria-hidden="true"></div>
        <div>
          <div class="ls-sheet-name" id="ls-decision-name"></div>
          <div class="ls-sheet-sub">Needs your decision</div>
        </div>
      </div>
      <button type="button" class="ls-sheet-close" id="ls-decision-close" aria-label="Close">&#10005;</button>
    </header>
    <div class="ls-decision-body">
      <p class="ls-decision-q" id="ls-decision-q"></p>
      <p class="ls-decision-meta" id="ls-decision-meta"></p>
      <p class="ls-decision-note" id="ls-decision-note" hidden></p>
    </div>
    <div class="ls-decision-acts" id="ls-decision-acts">
      <button type="button" class="ls-act" data-act="deny">Deny</button>
      <button type="button" class="ls-act" data-act="approve">Approve</button>
    </div>
    <p class="ls-decision-done" id="ls-decision-done" hidden></p>
  </section>"""


# Plain (non-f) string: braces are JavaScript, not format fields.
_LOCK_SCREEN_SCRIPT = r"""
(function () {
  "use strict";
  // Lock-screen chrome only: the clock, the battery chip and the keypad. PIN
  // submission, the dots and the error line stay in /auth/pin-panel.js -- this
  // script types into the same #pin-input and lets that one do the rest, so
  // there is exactly one implementation of "what happens when a PIN is entered".
  function init() {
    var timeEl = document.getElementById("ls-time");
    var dateEl = document.getElementById("ls-date");

    function tick() {
      var now = new Date();
      // Locale-driven: a 24h phone shows 24h. hour12 is left to the locale
      // rather than forced, because forcing it is wrong in half the world.
      if (timeEl) {
        timeEl.textContent = now.toLocaleTimeString([], {
          hour: "numeric", minute: "2-digit"
        });
      }
      if (dateEl) {
        dateEl.textContent = now.toLocaleDateString([], {
          weekday: "long", day: "numeric", month: "long"
        });
      }
      // Re-align to the top of the next minute instead of polling every second:
      // the display only changes once a minute and this is a battery-powered
      // device sitting on this screen whenever it is idle.
      var ms = (60 - now.getSeconds()) * 1000 - now.getMilliseconds();
      setTimeout(tick, ms > 0 ? ms : 60000);
    }
    tick();

    // Battery: navigator.getBattery is not universal (and is absent on desktop
    // Firefox), so the chip stays hidden unless the API actually answers.
    var batEl = document.getElementById("ls-battery");
    if (batEl && navigator.getBattery) {
      navigator.getBattery().then(function (bat) {
        function paint() {
          var pct = Math.round(bat.level * 100);
          batEl.textContent = (bat.charging ? "⚡ " : "") + pct + "%";
          batEl.hidden = false;
        }
        paint();
        bat.addEventListener("levelchange", paint);
        bat.addEventListener("chargingchange", paint);
      }).catch(function () { /* no battery info: leave the chip hidden */ });
    }

    // Agent activity. Re-fetched on a timer because a lock screen is a LIVE
    // surface: it is what the phone shows while it sits there, so a card that
    // only reflects page-load time is wrong within a minute.
    var screenEl = document.getElementById("lockscreen");
    var card = document.getElementById("ls-activity");
    var agentsEl = document.getElementById("ls-agents");
    var tasksEl = document.getElementById("ls-tasks");

    // Deterministic hue per agent, so an agent keeps its colour between
    // refreshes and between boots. A random palette would reshuffle the lock
    // screen every 15 seconds.
    function hueFor(name) {
      var h = 0;
      for (var i = 0; i < name.length; i++) { h = (h * 31 + name.charCodeAt(i)) % 360; }
      return h;
    }

    function initials(name) {
      var words = name.trim().split(/\s+/);
      if (!words[0]) return "?";
      if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
      return (words[0][0] + words[words.length - 1][0]).toUpperCase();
    }

    var FRAMEWORKS = { hermes: 1, openclaw: 1, deepseek: 1, omp: 1 };
    var RESTING = ["", "stopped", "idle", "exited", "error"];

    function island(agent) {
      var name = agent.name || "agent";
      var status = agent.status || "idle";
      var busy = RESTING.indexOf(status.trim().toLowerCase()) === -1;

      var el = document.createElement("div");
      el.className = "ls-island";
      el.setAttribute("data-state", busy ? "busy" : "idle");
      if (agent.attention) el.setAttribute("data-attention", "1");
      // An island OPENS something, so it is a button, not a list item: it has
      // to be reachable by tab and operable by Enter, not only by a press.
      el.setAttribute("role", "button");
      el.setAttribute("tabindex", "0");
      el.setAttribute("aria-label", (agent.attention && agent.decision)
        ? name + " needs a decision: " + (agent.decision.question || "")
        : name + ", " + status + ". Open conversation.");
      // The handlers read the whole record off the element rather than
      // re-looking it up by name: names are not unique keys, and a repaint
      // between the press and the open would make an index stale.
      el.__agent = agent;
      if (agent.system) el.setAttribute("data-system", "1");

      var marks = document.createElement("div");
      marks.className = "ls-marks";

      var av = document.createElement("div");
      av.className = "ls-avatar";
      var hue = hueFor(name);
      av.style.setProperty("--ls-a", "hsl(" + hue + " 62% 58%)");
      av.style.setProperty("--ls-b", "hsl(" + ((hue + 28) % 360) + " 58% 38%)");
      // A photo when one is configured; the monogram is the fallback, so a
      // missing file degrades to initials rather than a broken image frame.
      if (agent.avatar) {
        var img = document.createElement("img");
        img.className = "ls-avatar-img";
        img.alt = "";
        img.src = agent.avatar;
        img.addEventListener("error", function () {
          img.remove();
          // The product mark is shipped in /static, so a failure here is a
          // broken install rather than a missing optional portrait. Initials
          // are the fallback for a PERSON; "TA" in a circle is not the OS.
          if (!agent.system) av.textContent = initials(name);
        });
        av.appendChild(img);
      } else {
        av.textContent = initials(name);
      }
      marks.appendChild(av);

      var fw = String(agent.framework || "").toLowerCase();
      if (agent.framework_icon) {
        // The App Store's own artwork, when this framework ships one.
        var badge = document.createElement("div");
        badge.className = "ls-fw ls-fw-img";
        var logo = document.createElement("img");
        logo.alt = "";
        logo.src = agent.framework_icon;
        badge.appendChild(logo);
        marks.appendChild(badge);
      } else if (FRAMEWORKS[fw]) {
        var badge = document.createElement("div");
        badge.className = "ls-fw";
        var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        var use = document.createElementNS("http://www.w3.org/2000/svg", "use");
        // setAttribute, not the xlink-prefixed form: plain href on <use>
        // resolves in every browser this ships to and xlink is deprecated.
        use.setAttribute("href", "#fw-" + fw);
        svg.appendChild(use);
        badge.appendChild(svg);
        marks.appendChild(badge);
      }
      el.appendChild(marks);

      var body = document.createElement("div");
      body.className = "ls-body";
      var n = document.createElement("div");
      n.className = "ls-name";
      n.textContent = name;                 // textContent, never innerHTML
      var s = document.createElement("div");
      s.className = "ls-status";
      s.textContent = status;
      body.appendChild(n); body.appendChild(s);
      el.appendChild(body);

      var pip = document.createElement("span");
      pip.className = "ls-pip";
      el.appendChild(pip);
      return el;
    }

    function paintActivity(data) {
      // A repaint while a sheet is open would destroy the very island the sheet
      // was opened from -- dropping its record, restarting every entrance
      // animation and scrolling the list under the user's finger. The poll
      // keeps running; the next tick after the sheet closes paints.
      var openSheetName = screenEl ? screenEl.getAttribute("data-sheet") : "none";
      if (openSheetName && openSheetName !== "none") return;
      agentsEl.textContent = "";
      tasksEl.textContent = "";
      var agents = data.agents || [];
      var tasks = data.tasks || [];
      if (!agents.length && !tasks.length) { card.hidden = true; return; }

      for (var i = 0; i < agents.length; i++) {
        agentsEl.appendChild(island(agents[i]));
      }
      for (var j = 0; j < tasks.length; j++) {
        var row = document.createElement("div");
        row.className = "ls-task";
        var tn = document.createElement("span");
        tn.className = "ls-task-name";
        tn.textContent = tasks[j].name || "task";
        var tw = document.createElement("span");
        tw.textContent = tasks[j].agent
          ? tasks[j].agent + " \u00b7 " + tasks[j].schedule
          : tasks[j].schedule;
        row.appendChild(tn); row.appendChild(tw);
        tasksEl.appendChild(row);
      }
      if (data.task_total > tasks.length) {
        var more = document.createElement("div");
        more.className = "ls-task";
        more.textContent = "+" + (data.task_total - tasks.length) + " more scheduled";
        tasksEl.appendChild(more);
      }
      card.hidden = false;
    }

    function pollActivity() {
      fetch("/auth/lock-widgets", { credentials: "same-origin" })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) { if (d) paintActivity(d); })
        .catch(function () { /* offline or off-console: leave the card as is */ });
    }
    if (card) {
      pollActivity();
      setInterval(pollActivity, 15000);
    }

    // Switching to the password form leaves the lock screen: that form needs a
    // real keyboard, and the keypad/clock chrome has nothing to do with it.
    // Dropping the class restores the ordinary centred sign-in card, keyboard
    // toggle included, without this script re-implementing either.
    var toPw = document.getElementById("use-password");
    if (toPw) {
      toPw.addEventListener("click", function () {
        document.body.classList.remove("lockscreen-on");
      });
    }

    // -----------------------------------------------------------------------
    // SHEETS. One state variable (data-sheet on .lockscreen) drives the scrim,
    // the head blur, the unlock bar and which sheet is raised. Every open and
    // close goes through openSheet/closeSheet so those can never disagree.
    // -----------------------------------------------------------------------
    var scrim     = document.getElementById("ls-scrim");
    var unlockBar = document.getElementById("ls-unlock");
    var unlockBtn = document.getElementById("ls-unlock-btn");
    var chatSheet = document.getElementById("ls-chat");
    var decSheet  = document.getElementById("ls-decision");
    var lastFocus = null;

    if (screenEl) screenEl.setAttribute("data-sheet", "none");

    function sheetEl(name) {
      if (name === "chat") return chatSheet;
      if (name === "decision") return decSheet;
      if (name === "passcode") return document.getElementById("ls-foot");
      return null;
    }

    function openSheet(name) {
      if (!screenEl) return;
      var current = screenEl.getAttribute("data-sheet");
      if (current === name) return;
      // Remember where the user was so closing returns them there rather than
      // dropping focus to the top of the document.
      if (current === "none") lastFocus = document.activeElement;
      // Only ever one sheet: hide whatever was up before revealing the next.
      if (current && current !== "none") {
        var prev = sheetEl(current);
        if (prev && prev.id !== "ls-foot") prev.hidden = true;
      }
      var el = sheetEl(name);
      if (el) el.hidden = false;
      if (scrim) scrim.hidden = false;
      // The attribute is set on the NEXT frame when the sheet was hidden a
      // moment ago: a transform transition on an element that was display:none
      // in the same frame has no start value and the sheet would appear
      // instantly instead of sliding.
      requestAnimationFrame(function () {
        screenEl.setAttribute("data-sheet", name);
      });
      if (unlockBtn) unlockBtn.setAttribute("aria-expanded", name === "passcode" ? "true" : "false");
    }

    function closeSheet() {
      if (!screenEl) return;
      var current = screenEl.getAttribute("data-sheet");
      if (!current || current === "none") return;
      screenEl.setAttribute("data-sheet", "none");
      if (unlockBtn) unlockBtn.setAttribute("aria-expanded", "false");
      // The composer must not keep the keyboard up over a closed sheet.
      if (window.taosOSK) window.taosOSK.disable();
      setKeyboardOffset(0);
      var el = sheetEl(current);
      // Wait out the slide before hiding, or the sheet vanishes mid-animation.
      // hidden (not display) so it also leaves the accessibility tree.
      window.setTimeout(function () {
        if (screenEl.getAttribute("data-sheet") !== "none") return;
        if (el && el.id !== "ls-foot") el.hidden = true;
        if (scrim) scrim.hidden = true;
      }, 400);
      if (lastFocus && lastFocus.focus) { try { lastFocus.focus(); } catch (e) {} }
      lastFocus = null;
    }

    if (scrim) scrim.addEventListener("click", closeSheet);
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") closeSheet();
    });
    var chatClose = document.getElementById("ls-chat-close");
    if (chatClose) chatClose.addEventListener("click", closeSheet);
    var decClose = document.getElementById("ls-decision-close");
    if (decClose) decClose.addEventListener("click", closeSheet);

    // -----------------------------------------------------------------------
    // KEYBOARD OFFSET. The sheets are anchored to the bottom edge and the
    // on-screen keyboard is a fixed panel on that same edge, so without this
    // the composer sits UNDER the keys. The OSK reserves its space as body
    // padding, which does nothing for a fixed element -- so measure the panel
    // itself rather than duplicating its height as a guess that drifts when the
    // keyboard switches between its letter, symbol and numeric layers.
    // -----------------------------------------------------------------------
    function setKeyboardOffset(px) {
      document.documentElement.style.setProperty("--ls-kb", (px || 0) + "px");
    }

    var oskPanel = document.querySelector(".osk");
    function syncKeyboard() {
      if (!oskPanel) { oskPanel = document.querySelector(".osk"); }
      if (!oskPanel || oskPanel.hidden) { setKeyboardOffset(0); return; }
      setKeyboardOffset(oskPanel.offsetHeight);
    }
    if (window.ResizeObserver) {
      var ro = new ResizeObserver(syncKeyboard);
      if (oskPanel) ro.observe(oskPanel);
      // The panel is appended on DOMContentLoaded, which may not have happened
      // yet when this runs, so pick it up once it exists.
      var mo = new MutationObserver(function () {
        var found = document.querySelector(".osk");
        if (found && found !== oskPanel) { oskPanel = found; ro.observe(found); }
        syncKeyboard();
      });
      mo.observe(document.body, { childList: true, attributes: true, attributeFilter: ["hidden", "class"], subtree: true });
    }

    // -----------------------------------------------------------------------
    // UNLOCK. A button AND a swipe, not a swipe alone: the gesture is the
    // shortcut for someone who knows it, the button is what makes the phone
    // openable by someone who does not (or cannot make the drag at all).
    // -----------------------------------------------------------------------
    function openPasscode() {
      openSheet("passcode");
      var pinInput = document.getElementById("pin-input");
      // Focus the field so a physical keyboard types into it, but do NOT raise
      // the shared on-screen keyboard: this screen draws its own keypad.
      if (pinInput) { try { pinInput.focus({ preventScroll: true }); } catch (e) { pinInput.focus(); } }
    }
    if (unlockBtn) unlockBtn.addEventListener("click", openPasscode);

    // Swipe up from the resting screen, swipe down to dismiss a sheet. Tracked
    // on the whole lock screen rather than a thin edge strip, because an edge
    // strip on a phone competes with the system's own gesture area.
    (function () {
      var y0 = null, x0 = null, moved = false;
      function start(ev) {
        var t = ev.touches ? ev.touches[0] : ev;
        y0 = t.clientY; x0 = t.clientX; moved = false;
      }
      function move(ev) {
        if (y0 === null) return;
        var t = ev.touches ? ev.touches[0] : ev;
        if (Math.abs(t.clientY - y0) > 10 || Math.abs(t.clientX - x0) > 10) moved = true;
      }
      function end(ev) {
        if (y0 === null) return;
        var t = (ev.changedTouches ? ev.changedTouches[0] : ev);
        var dy = t.clientY - y0;
        var dx = t.clientX - x0;
        y0 = null; x0 = null;
        // Vertical intent only: a diagonal drag while scrolling the agent list
        // must not be read as an unlock.
        if (!moved || Math.abs(dy) < 56 || Math.abs(dx) > Math.abs(dy)) return;
        var sheet = screenEl ? screenEl.getAttribute("data-sheet") : "none";
        if (dy < 0 && sheet === "none") openPasscode();
        else if (dy > 0 && sheet !== "none") closeSheet();
      }
      var surface = document.body;
      surface.addEventListener("touchstart", start, { passive: true });
      surface.addEventListener("touchmove", move, { passive: true });
      surface.addEventListener("touchend", end, { passive: true });
    })();

    // -----------------------------------------------------------------------
    // CONVERSATION SHEET.
    // -----------------------------------------------------------------------
    var msgsEl    = document.getElementById("ls-msgs");
    var composer  = document.getElementById("ls-compose-input");
    var sendBtn   = document.getElementById("ls-send");
    var chatName  = document.getElementById("ls-chat-name");
    var chatSub   = document.getElementById("ls-chat-sub");
    var chatAv    = document.getElementById("ls-chat-avatar");
    var chatAgent = null;

    function slugFor(name) {
      // Must match the server's _avatar_slug exactly or the thread 404s.
      var out = "";
      var lower = String(name).trim().toLowerCase();
      for (var i = 0; i < lower.length; i++) {
        var ch = lower[i];
        if (/[a-z0-9]/.test(ch)) out += ch;
        else if (out && out[out.length - 1] !== "-") out += "-";
      }
      return out.replace(/^-+|-+$/g, "");
    }

    function fillAvatar(box, agent) {
      box.textContent = "";
      // Same rule as the island: the product mark is contained, not cropped.
      if (agent.system) box.setAttribute("data-system", "1");
      else box.removeAttribute("data-system");
      var hue = hueFor(agent.name || "agent");
      box.style.setProperty("--ls-a", "hsl(" + hue + " 62% 58%)");
      box.style.setProperty("--ls-b", "hsl(" + ((hue + 28) % 360) + " 58% 38%)");
      if (agent.avatar) {
        var img = document.createElement("img");
        img.alt = ""; img.src = agent.avatar;
        img.addEventListener("error", function () {
          img.remove();
          if (!agent.system) box.textContent = initials(agent.name || "agent");
        });
        box.appendChild(img);
      } else {
        box.textContent = initials(agent.name || "agent");
      }
    }

    function dayLabel(d) {
      var today = new Date(); today.setHours(0, 0, 0, 0);
      var that = new Date(d.getTime()); that.setHours(0, 0, 0, 0);
      var days = Math.round((today - that) / 86400000);
      if (days === 0) return "Today";
      if (days === 1) return "Yesterday";
      if (days < 7) return d.toLocaleDateString([], { weekday: "long" });
      return d.toLocaleDateString([], { day: "numeric", month: "long" });
    }

    function bubble(msg) {
      var b = document.createElement("div");
      b.className = "ls-msg";
      b.setAttribute("data-role", msg.role === "user" ? "user" : "agent");
      b.textContent = msg.text || "";     // textContent, never innerHTML
      return b;
    }

    function renderThread(messages) {
      msgsEl.textContent = "";
      var lastDay = "";
      for (var i = 0; i < messages.length; i++) {
        var m = messages[i];
        var when = new Date((m.at || 0) * 1000);
        var label = dayLabel(when);
        if (label !== lastDay) {
          var sep = document.createElement("div");
          sep.className = "ls-day";
          sep.textContent = label;
          msgsEl.appendChild(sep);
          lastDay = label;
        }
        msgsEl.appendChild(bubble(m));
      }
      // Open at the newest message, the way every messaging app does. Set
      // directly rather than scrollIntoView so it does not also scroll the page
      // behind the sheet.
      //
      // Twice, on the next frame: setting scrollTop in the same frame the
      // bubbles were appended measures a scrollHeight that layout has not
      // finished computing, and the thread opens with its last message clipped
      // behind the composer. The second frame catches the reflow that wrapping
      // the final bubble causes. Measured on the device.
      msgsEl.scrollTop = msgsEl.scrollHeight;
      requestAnimationFrame(function () {
        msgsEl.scrollTop = msgsEl.scrollHeight;
        requestAnimationFrame(function () {
          msgsEl.scrollTop = msgsEl.scrollHeight;
        });
      });
    }

    function openChat(agent) {
      chatAgent = agent;
      chatName.textContent = agent.name || "agent";
      chatSub.textContent = agent.demo ? "Demo conversation" : (agent.status || "");
      fillAvatar(chatAv, agent);
      msgsEl.textContent = "";
      composer.value = "";
      if (sendBtn) sendBtn.disabled = true;
      openSheet("chat");

      fetch("/auth/lock-thread/" + encodeURIComponent(slugFor(agent.name || "")), {
        credentials: "same-origin"
      }).then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) {
          if (!d || !d.messages || !d.messages.length) {
            var empty = document.createElement("div");
            empty.className = "ls-day";
            empty.textContent = "No messages yet";
            msgsEl.appendChild(empty);
            return;
          }
          renderThread(d.messages);
        })
        .catch(function () { /* leave the thread empty rather than erroring */ });
    }

    if (composer) {
      composer.addEventListener("input", function () {
        if (sendBtn) sendBtn.disabled = !composer.value.trim();
      });
      // Typing is the ONE place on this screen that wants the full keyboard.
      // The lock screen keeps the shared OSK disabled for the passcode (it has
      // its own keypad), so it has to be turned back on here and off again on
      // close -- which closeSheet does.
      composer.addEventListener("focus", function () {
        if (window.taosOSK) {
          window.taosOSK.enable();
          window.taosOSK.focusField(composer);
        }
        window.setTimeout(syncKeyboard, 60);
      });
    }

    function send() {
      if (!composer) return;
      var text = composer.value.trim();
      if (!text) return;
      var now = Date.now() / 1000;
      msgsEl.appendChild(bubble({ role: "user", text: text, at: now }));
      composer.value = "";
      if (sendBtn) sendBtn.disabled = true;
      msgsEl.scrollTop = msgsEl.scrollHeight;
      // A reply only comes back in a demo thread. Outside demo mode there is no
      // agent on the other end of this sheet -- the lock screen is pre-auth and
      // deliberately cannot reach the chat store -- so inventing a reply would
      // be telling the user something happened when nothing did.
      if (!chatAgent || !chatAgent.demo) return;
      window.setTimeout(function () {
        if (!screenEl || screenEl.getAttribute("data-sheet") !== "chat") return;
        msgsEl.appendChild(bubble({
          role: "agent",
          text: "Got it — I'll pick that up.",
          at: Date.now() / 1000
        }));
        msgsEl.scrollTop = msgsEl.scrollHeight;
      }, 900);
    }
    if (sendBtn) sendBtn.addEventListener("click", send);
    if (composer) {
      composer.addEventListener("keydown", function (ev) {
        if (ev.key === "Enter") { ev.preventDefault(); send(); }
      });
    }

    // -----------------------------------------------------------------------
    // DECISION SHEET. Approve/Deny on a LOCKED screen is deliberately limited:
    // a demo prompt resolves in place, but a real decision carries an id and
    // answering it is an authenticated write. The lock screen does not hold a
    // session, so the honest move is to take the intent, raise the passcode and
    // let the answer happen as the signed-in user -- never to accept a decision
    // from whoever happens to be holding the phone.
    // -----------------------------------------------------------------------
    var decQ     = document.getElementById("ls-decision-q");
    var decMeta  = document.getElementById("ls-decision-meta");
    var decNote  = document.getElementById("ls-decision-note");
    var decName  = document.getElementById("ls-decision-name");
    var decAv    = document.getElementById("ls-decision-avatar");
    var decActs  = document.getElementById("ls-decision-acts");
    var decDone  = document.getElementById("ls-decision-done");

    function openDecision(agent) {
      var d = agent.decision || {};
      decName.textContent = agent.name || "agent";
      fillAvatar(decAv, agent);
      decQ.textContent = d.question || "This agent needs a decision.";
      decMeta.textContent = d.priority && d.priority !== "normal"
        ? d.priority.charAt(0).toUpperCase() + d.priority.slice(1) + " priority"
        : "";
      decNote.hidden = !!d.id;
      decNote.textContent = d.id ? "" : "Demo prompt — nothing is actually approved.";
      decActs.hidden = false;
      decDone.hidden = true;
      decActs.setAttribute("data-decision-id", d.id || "");
      openSheet("decision");
    }

    if (decActs) {
      decActs.addEventListener("click", function (ev) {
        var btn = ev.target.closest(".ls-act");
        if (!btn) return;
        var approved = btn.getAttribute("data-act") === "approve";
        var id = decActs.getAttribute("data-decision-id") || "";
        if (!id) {
          // Demo prompt: resolve in place and say so.
          decActs.hidden = true;
          decDone.hidden = false;
          decDone.textContent = approved ? "Approved (demo)" : "Denied (demo)";
          window.setTimeout(closeSheet, 1100);
          return;
        }
        // Real decision: this needs a session, so send the user to the passcode
        // and let them answer it signed in.
        decActs.hidden = true;
        decDone.hidden = false;
        decDone.textContent = "Unlock to " + (approved ? "approve" : "deny") + " this.";
        window.setTimeout(openPasscode, 700);
      });
    }

    // -----------------------------------------------------------------------
    // ISLAND PRESS. Press-and-hold opens the conversation, the way a long press
    // expands a notification on a phone. A short tap opens too -- the decision
    // when the island is asking for one, the conversation otherwise -- because
    // an island that looks pressable and does nothing on a tap reads as broken.
    // The sink-then-pop is what tells the finger the HOLD is being received.
    // -----------------------------------------------------------------------
    var HOLD_MS = 420;
    (function () {
      var timer = null, held = false, startY = 0, startX = 0, pressed = null;

      function clear() {
        if (timer) { window.clearTimeout(timer); timer = null; }
        if (pressed) { pressed.removeAttribute("data-press"); }
        pressed = null;
      }

      function open(el) {
        var agent = el.__agent;
        if (!agent) return;
        if (agent.attention && agent.decision) openDecision(agent);
        else openChat(agent);
      }

      agentsEl.addEventListener("pointerdown", function (ev) {
        var el = ev.target.closest(".ls-island");
        if (!el) return;
        held = false;
        startY = ev.clientY; startX = ev.clientX;
        pressed = el;
        el.setAttribute("data-press", "1");
        timer = window.setTimeout(function () {
          held = true;
          el.setAttribute("data-press", "2");
          // Haptics where the platform offers them: a long press that only
          // changes pixels does not feel like a press.
          if (navigator.vibrate) { try { navigator.vibrate(12); } catch (e) {} }
          window.setTimeout(function () { el.removeAttribute("data-press"); }, 200);
          openChat(el.__agent || {});
        }, HOLD_MS);
      });

      // A drag is a scroll of the agent list, not a press.
      agentsEl.addEventListener("pointermove", function (ev) {
        if (!pressed) return;
        if (Math.abs(ev.clientY - startY) > 10 || Math.abs(ev.clientX - startX) > 10) clear();
      });

      agentsEl.addEventListener("pointerup", function (ev) {
        var el = pressed;
        clear();
        if (held) { held = false; return; }   // the hold already opened it
        if (!el) return;
        var target = ev.target.closest(".ls-island");
        if (target === el) open(el);
      });

      agentsEl.addEventListener("pointercancel", clear);
      agentsEl.addEventListener("pointerleave", clear);

      // Keyboard parity: an island is a button, so Enter and Space must open it.
      agentsEl.addEventListener("keydown", function (ev) {
        if (ev.key !== "Enter" && ev.key !== " ") return;
        var el = ev.target.closest(".ls-island");
        if (!el) return;
        ev.preventDefault();
        open(el);
      });
    })();

    // Keypad -> the existing PIN input.
    var pad = document.getElementById("ls-pad");
    var input = document.getElementById("pin-input");
    if (!pad || !input) return;

    function emit() {
      // The pin-panel script paints the dots from an "input" event, so the
      // keypad must raise one -- assigning .value alone fires nothing.
      input.dispatchEvent(new Event("input", { bubbles: true }));
    }

    pad.addEventListener("click", function (ev) {
      var key = ev.target.closest(".ls-key");
      if (!key) return;
      var digit = key.getAttribute("data-digit");
      if (digit !== null) {
        var max = parseInt(input.getAttribute("maxlength") || "12", 10);
        if (input.value.length < max) {
          input.value += digit;
          emit();
        }
        return;
      }
      if (key.getAttribute("data-action") === "back") {
        input.value = input.value.slice(0, -1);
        emit();
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
"""


def _login_page(
    error: str = "",
    multi_user: bool = False,
    next_url: str = "",
    pin_available: bool = False,
) -> str:
    err = f'<p class="error" role="alert">{html.escape(error)}</p>' if error else ""
    pwd_placeholder = "Password or invite code" if multi_user else "Password"
    autologin_default = "" if multi_user else "checked"
    username_field = '''
        <label class="field">
          <span>Username or email</span>
          <input type="text" name="username" autocomplete="username" autofocus required>
        </label>
        ''' if multi_user else ""
    next_field = f'<input type="hidden" name="next" value="{html.escape(next_url)}">' if next_url else ""
    # The PIN panel and the "use a PIN instead" switch exist only when this
    # request is console-local AND a PIN is set. Off-console the page is exactly
    # what it has always been, so a LAN browser is never shown a method it would
    # be refused (and never learns that a PIN exists on this box).
    # pin_available is already console-only, so the lock screen never reaches a
    # LAN browser: off-console this page stays exactly the card it has always been.
    lock_screen = pin_available
    pin_panel = _pin_panel_html(next_url, keypad=lock_screen) if pin_available else ""
    pin_switch = (
        '<button type="button" class="method-switch" id="use-pin">Use my PIN instead</button>'
        if pin_available else ""
    )
    pin_script = '<script src="/auth/pin-panel.js" defer></script>' if pin_available else ""
    # The lock screen replaces the card entirely: a passcode screen that still
    # draws a bordered panel in the middle of a 2400px phone reads as a web page.
    # The device's own name is the only server-supplied value on it -- everything
    # else (clock, battery) is read client-side, so nothing account-derived is
    # rendered before the user has authenticated.
    body_class = "lockscreen-on" if lock_screen else ""
    shell_class = "ls-foot" if lock_screen else "card"
    shell_id = ' id="ls-foot"' if lock_screen else ""
    brand = "" if lock_screen else (
        '<div class="brand">\n'
        '      <h1 class="wordmark">taOS</h1>\n'
        '      <p>Sign in to continue</p>\n'
        '    </div>'
    )
    lock_head = _lock_head_html() if lock_screen else ""
    lock_foot = _lock_tail_html() if lock_screen else ""
    lock_script = '<script src="/auth/lock-screen.js" defer></script>' if lock_screen else ""
    lock_style = f"<style>{_LOCK_SCREEN_STYLE}</style>" if lock_screen else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>Sign in — taOS</title>
<style>{_AUTH_BASE_STYLE}</style>
<style>{_PIN_PANEL_STYLE}</style>
{lock_style}
</head>
<body class="{body_class}">
  {lock_head}
  <div class="{shell_class}"{shell_id}>
    {brand}
    {err}
    {pin_panel}
    <form class="pw-panel" id="pw-panel" method="POST" action="/auth/login">
      {username_field}
      {next_field}
      <label class="field">
        <span>Password</span>
        <input type="password" name="password" autocomplete="current-password" placeholder="{pwd_placeholder}" {'' if multi_user else 'autofocus'} required>
      </label>
      <label class="checkbox">
        <input type="checkbox" name="auto_login" value="1" {autologin_default}>
        Stay signed in on this device
      </label>
      <button type="submit">Sign in</button>
      {pin_switch}
    </form>
  </div>
  {lock_foot}
{osk_assets()}
{pin_script}
{lock_script}
</body>
</html>
"""


def _setup_page(error: str = "", pin_offered: bool = False) -> str:
    err = f'<p class="error" role="alert">{html.escape(error)}</p>' if error else ""
    # Offered only when the installer is sitting at the machine's own screen —
    # a PIN is refused anywhere else (see is_console_origin), so offering it to
    # a LAN browser would hand the user a sign-in method that cannot work and
    # would tell that browser a PIN exists on this box. It stays optional: the
    # password is always set, so nobody can lock themselves out by skipping it,
    # and it can be added later from Settings.
    pin_field = f"""
    <label class="field">
      <span>PIN for this screen (optional)</span>
      <input type="password" name="pin" id="setup-pin" inputmode="numeric"
             autocomplete="off" maxlength="{PIN_MAX_LEN}" pattern="[0-9]*">
      <span class="hint">{PIN_MIN_LEN}-{PIN_MAX_LEN} digits, for signing in on
        this device's own screen — handy on a touchscreen with no keyboard.
        Your password still works everywhere.</span>
    </label>
    """ if pin_offered else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>Welcome — taOS</title>
<style>{_AUTH_BASE_STYLE}</style>
</head>
<body>
  <form class="card" method="POST" action="/auth/setup">
    <div class="brand">
      <h1 class="wordmark">taOS</h1>
      <p>Welcome — set up your account to get started.</p>
    </div>
    {err}
    <label class="field">
      <span>Username</span>
      <input type="text" name="username" autocomplete="username" autofocus required>
    </label>
    <label class="field">
      <span>Full name</span>
      <input type="text" name="full_name" autocomplete="name" required>
    </label>
    <label class="field">
      <span>Email</span>
      <input type="email" name="email" autocomplete="email">
      <span class="hint">Optional today, used for cloud services later.</span>
    </label>
    <label class="field">
      <span>Password</span>
      <input type="password" name="password" autocomplete="new-password" minlength="8" required>
      <span class="hint">At least 8 characters.</span>
    </label>
    {pin_field}
    <label class="checkbox">
      <input type="checkbox" name="auto_login" value="1" checked>
      Stay signed in on this device
    </label>
    <button type="submit">Get started</button>
  </form>
{osk_assets()}
</body>
</html>
"""


def _require_admin(request: Request) -> tuple[bool, JSONResponse | None]:
    """Check that the session belongs to an admin. Returns (ok, error_response)."""
    auth_mgr = request.app.state.auth
    token = request.cookies.get("taos_session", "")
    if not token:
        return False, JSONResponse({"error": "forbidden"}, status_code=403)
    user = auth_mgr.session_user(token)
    if not user or not user.get("is_admin"):
        return False, JSONResponse({"error": "forbidden"}, status_code=403)
    return True, None


def _require_self(request: Request, username: str) -> tuple[bool, JSONResponse | None]:
    """Check that the session belongs to *username*. Returns (ok, error_response)."""
    auth_mgr = request.app.state.auth
    token = request.cookies.get("taos_session", "")
    if not token:
        return False, JSONResponse({"error": "forbidden"}, status_code=403)
    user = auth_mgr.session_user(token)
    if not user or user.get("username") != username:
        return False, JSONResponse({"error": "forbidden"}, status_code=403)
    return True, None


async def _json_object(request: Request) -> tuple[dict | None, JSONResponse | None]:
    """Read a JSON request body that must be an object. Returns (body, error_response).

    Parsing alone is not enough: request.json() happily returns null, [], 1 or
    "x" -- all valid JSON, none of them a mapping. A bare body.get() on any of
    those raises AttributeError, so the caller gets a 500 for what is plainly a
    malformed request. /auth/login, /auth/setup and /auth/complete are all
    session-exempt, so that 500 is reachable by anyone who can reach the port.
    """
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        # Deliberately narrow. request.json() READS the body before it parses
        # it, so a blanket `except Exception` also swallows body-read failures
        # (a client disconnecting mid-upload raises ClientDisconnect here) and
        # reports them to the caller as "your JSON was malformed". That is a
        # false accusation, and it hides a transport fault behind a 400 that
        # nobody investigates. A read failure is not the client's syntax error,
        # so let it propagate.
        return None, JSONResponse({"error": "invalid JSON body"}, status_code=400)
    if not isinstance(body, dict):
        return None, JSONResponse({"error": "invalid JSON body"}, status_code=400)
    return body, None


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = "", next: str = ""):
    """Server-rendered login page. Works without JavaScript — the SPA
    takes over once the user is signed in and lands on /desktop."""
    auth_mgr = request.app.state.auth
    # If the install isn't configured yet, send them to setup instead of
    # showing a useless login form.
    if not auth_mgr.is_configured():
        return RedirectResponse("/auth/setup", status_code=303)
    if error == "rate_limit":
        err_text = _LOCKOUT_MSG
    elif error:
        err_text = "Incorrect username or password."
    else:
        err_text = ""
    # Only allow relative paths starting with / to prevent open redirect
    safe_next = next if (next.startswith("/") and not next.startswith("//")) else ""
    # Same rule as /auth/status and /auth/pin-login: offer the keypad only where
    # it would actually be accepted.
    try:
        pin_available = _request_is_console(request) and auth_mgr.has_pin()
    except AuthStoreCorruptError:
        pin_available = False
    return HTMLResponse(_login_page(
        err_text,
        multi_user=auth_mgr.is_multi_user(),
        next_url=safe_next,
        pin_available=pin_available,
    ))


@router.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request, error: str = ""):
    """Server-rendered first-run setup page. Same robustness rationale as
    /auth/login. Once a user exists this page redirects to login."""
    auth_mgr = request.app.state.auth
    if auth_mgr.is_configured():
        return RedirectResponse("/auth/login", status_code=303)
    err_text = ""
    if error:
        err_text = {
            "username": "Username is required.",
            "password": "Password must be at least 8 characters.",
            "pin": f"A PIN must be {PIN_MIN_LEN}-{PIN_MAX_LEN} digits, or left blank.",
        }.get(error, "Setup failed. Please try again.")
    return HTMLResponse(_setup_page(err_text, pin_offered=_request_is_console(request)))


@router.post("/login")
async def login(request: Request):
    """Sign in. Accepts JSON or form-encoded.

    JSON body: ``{username?, password, auto_login?}``. Returns the user
    profile and sets a session cookie.

    For pending users (invite code supplied), returns
    ``needs_onboarding: true`` and creates a session so the
    OnboardingScreen can complete the profile.

    Form body: legacy password-only login (kept for backward compat).
    """
    auth_mgr = request.app.state.auth
    client_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "")

    content_type = request.headers.get("content-type", "")

    # Only the HARD ceiling rejects before we verify the password. Below it we
    # always check, so a correct password succeeds even after earlier typos --
    # the soft lockout (applied on failure below) gates further WRONG attempts,
    # not the legitimate user. This is the footgun that funneled a locked-out
    # user into creating a duplicate account.
    if _login_limiter.count(client_ip) >= _LOGIN_HARD_MAX:
        if "application/json" in content_type:
            return JSONResponse({"error": _LOCKOUT_MSG}, status_code=429)
        return RedirectResponse("/auth/login?error=rate_limit", status_code=303)
    if "application/json" in content_type:
        body, body_err = await _json_object(request)
        if body_err:
            return body_err
        username = (body.get("username") or "").strip() or None
        password = body.get("password") or ""

        ok, user_record = auth_mgr.check_password(password, username=username)
        if not ok:
            _login_limiter.record_failure(client_ip)
            if _login_limiter.is_limited(client_ip):
                return JSONResponse({"error": _LOCKOUT_MSG}, status_code=429)
            return JSONResponse({"error": "invalid credentials"}, status_code=401)

        _login_limiter.reset(client_ip)

        # Determine long_lived. In multi-user mode default to False when
        # auto_login is not explicitly set.
        if "auto_login" in body:
            long_lived = bool(body["auto_login"])
        else:
            long_lived = not auth_mgr.is_multi_user()

        # Pending user: invite code accepted as password
        if user_record and user_record.get("pending_invite"):
            token = auth_mgr.create_session(user_id=user_record["id"], long_lived=long_lived, user_agent=user_agent)
            resp = JSONResponse({
                "ok": True,
                "needs_onboarding": True,
                "user": auth_mgr._public_user(user_record),
            })
            if long_lived:
                resp.set_cookie(
                    "taos_session", token, httponly=True, samesite="strict",
                    max_age=auth_mgr.session_ttl_for(True),
                )
            else:
                resp.set_cookie("taos_session", token, httponly=True, samesite="strict")
            return resp

        user_id = user_record["id"] if user_record else ""
        if user_record:
            auth_mgr.update_last_login(user_id)
        token = auth_mgr.create_session(user_id=user_id, long_lived=long_lived, user_agent=user_agent)
        pub = auth_mgr._public_user(user_record) if user_record else auth_mgr.get_user()
        resp = JSONResponse({"ok": True, "user": pub})
        if long_lived:
            resp.set_cookie(
                "taos_session", token, httponly=True, samesite="strict",
                max_age=auth_mgr.session_ttl_for(True),
            )
        else:
            resp.set_cookie("taos_session", token, httponly=True, samesite="strict")
        return resp

    # Form-encoded path — used by the no-JS HTML login page.
    form = await request.form()
    username = (form.get("username") or "").strip() or None
    password = form.get("password", "")
    long_lived = bool(form.get("auto_login"))
    next_url = str(form.get("next", "") or "")
    # Validate next_url to prevent open redirect
    if not (next_url.startswith("/") and not next_url.startswith("//")):
        next_url = ""

    ok, user_record = auth_mgr.check_password(password, username=username)
    if not ok:
        _login_limiter.record_failure(client_ip)
        next_qs = f"&next={next_url}" if next_url else ""
        err = "rate_limit" if _login_limiter.is_limited(client_ip) else "1"
        return RedirectResponse(f"/auth/login?error={err}{next_qs}", status_code=303)

    _login_limiter.reset(client_ip)

    if user_record and user_record.get("pending_invite"):
        # Pending user — create their session, then send to /desktop. The
        # SPA's LoginGate will see needs_onboarding via /auth/status and
        # render the invite-completion screen.
        token = auth_mgr.create_session(user_id=user_record["id"], long_lived=long_lived, user_agent=user_agent)
    else:
        user_id = user_record["id"] if user_record else ""
        if user_record:
            auth_mgr.update_last_login(user_id)
        token = auth_mgr.create_session(user_id=user_id, long_lived=long_lived, user_agent=user_agent)

    destination = next_url or "/desktop"
    response = RedirectResponse(destination, status_code=303)
    if long_lived:
        response.set_cookie(
            "taos_session", token, httponly=True, samesite="strict",
            max_age=auth_mgr.session_ttl_for(True),
        )
    else:
        response.set_cookie("taos_session", token, httponly=True, samesite="strict")
    return response


def _request_is_console(request: Request) -> bool:
    """Whether this request may use PIN sign-in at all.

    Thin wrapper so every PIN route asks the question exactly one way. The rule
    itself lives in ``auth.is_console_origin`` and is unit-tested there without
    needing a request object.
    """
    return is_console_origin(
        request.client.host if request.client else None, request.headers
    )


#: PIN attempts are throttled separately from passwords, keyed by user id.
#: Sharing ``_login_limiter`` would let PIN failures lock a user out of the
#: password path -- and since every console request arrives from the same
#: loopback address, an IP-keyed counter would be one shared bucket for all.
_pin_limiter = _PinAttemptLimiter()


@router.get("/osk.js")
async def osk_script(request: Request):
    """Serve the on-screen keyboard as a same-origin script.

    taOS sends `script-src 'self'`, which refuses inline <script> blocks. The
    keyboard therefore CANNOT be inlined into the auth pages -- doing so renders
    correct-looking HTML whose script the browser silently drops, so the page
    looks right and the keyboard simply never appears.
    """
    return Response(
        content=OSK_SCRIPT,
        media_type="application/javascript",
        headers={"Cache-Control": "public, max-age=300"},
    )


@router.get("/pin-panel.js")
async def pin_panel_script(request: Request):
    """Serve the PIN panel behaviour. Same CSP reasoning as /auth/osk.js."""
    return Response(
        content=_PIN_PANEL_SCRIPT,
        media_type="application/javascript",
        headers={"Cache-Control": "public, max-age=300"},
    )



@router.get("/lock-screen.js")
async def lock_screen_script(request: Request):
    """Serve the lock-screen chrome. Same CSP reasoning as /auth/osk.js."""
    return Response(
        content=_LOCK_SCREEN_SCRIPT,
        media_type="application/javascript",
        headers={"Cache-Control": "public, max-age=300"},
    )





#: Where the App Store keeps framework/brand artwork. The lock screen reuses
#: those files rather than carrying a second copy, so a logo updated for the
#: store is updated here too.
_STORE_ICON_DIRS = ("static/store-icons", "static/store-icons/brands")


def _framework_icon(framework: str) -> str:
    """URL of the App Store icon for a framework, or "" when none is shipped.

    Resolved server-side so the page only ever points at a file that exists: the
    client falls back to its drawn mark immediately instead of after a 404.
    /static/ is already served and already exempt from auth, so this adds no new
    pre-auth surface.
    """
    fw = "".join(c for c in framework.lower() if c.isalnum())
    if not fw:
        return ""
    root = Path(__file__).resolve().parent.parent.parent
    for folder in _STORE_ICON_DIRS:
        for ext in ("svg", "png", "jpg", "webp"):
            rel = f"{folder}/{fw}.{ext}"
            if (root / rel).is_file():
                return "/" + rel
    return ""


def _avatar_url(name: str) -> str:
    """URL for this agent's avatar, or "" when no image is installed.

    Checked server-side so the page never points an <img> at a 404 -- the client
    falls back to a monogram, and it should do that from the start rather than
    after a failed request paints a broken frame.
    """
    slug = _avatar_slug(name)
    if not slug:
        return ""
    if not (Path(LOCK_AVATAR_DIR) / f"{slug}.jpg").is_file():
        return ""
    return f"/auth/lock-avatar/{slug}"


@router.get("/lock-widgets")
async def lock_widgets(request: Request):
    """Agent activity + scheduled tasks for the lock screen. Console-only.

    This is rendered BEFORE sign-in, which is exactly why it is narrow: it
    returns NAMES, STATUSES AND COUNTS and nothing else. The agent config is
    never serialised here -- it carries per-agent LLM keys, and this endpoint is
    reachable without a session. The console gate is the second half of that
    containment: a LAN browser gets 403 and learns nothing, so the exposure is
    the same one a phone lock screen already makes to whoever is holding it.
    """
    if not _request_is_console(request):
        return JSONResponse({"error": "console only"}, status_code=403)

    agents: list[dict] = []
    try:
        configured = request.app.state.config.agents or []
    except AttributeError:
        configured = []
    # Container status is best-effort: on a host with no container runtime the
    # import or the call raises, and a lock screen that 500s because the phone
    # has no LXC is worse than one that simply shows no status.
    status_by_name: dict[str, str] = {}
    try:
        from tinyagentos.containers import list_containers

        for c in await list_containers(prefix="taos-agent-"):
            status_by_name[c.name.removeprefix("taos-agent-")] = c.status
    except Exception:  # noqa: BLE001 - any runtime absence degrades to "no status"
        status_by_name = {}

    for entry in configured:
        name = entry.get("name") if isinstance(entry, dict) else str(entry)
        if not name:
            continue
        framework = ""
        if isinstance(entry, dict):
            framework = str(entry.get("framework") or entry.get("harness") or "")
        agents.append({
            "name": str(name),
            "framework": framework.lower(),
            "framework_icon": _framework_icon(framework),
            "status": status_by_name.get(str(name), ""),
            "avatar": _avatar_url(str(name)),
        })

    # The OS's own agent is pinned to the top and is not one of the configured
    # ones: it is part of the device rather than something the user added. It
    # carries the product mark rather than a monogram, and the OMP harness badge
    # like any other agent -- it runs on OMP (oh-my-pi) over ACP, see
    # tinyagentos/adapters/omp_adapter.py.
    # Its "status" says WHERE it is, not that it is busy -- this endpoint runs
    # pre-auth and has no cheap, truthful way to read the agent's activity.
    agents.insert(0, {
        "name": "taOS Agent",
        "framework": "omp",
        "framework_icon": _framework_icon("omp"),
        "status": "On device",
        "avatar": "/static/taos-logo.png",
        "system": True,
    })

    tasks: list[dict] = []
    try:
        scheduler = request.app.state.scheduler
        for task in await scheduler.list_tasks():
            item = task if isinstance(task, dict) else {}
            tasks.append({
                "name": str(item.get("name", "") or ""),
                "schedule": str(item.get("schedule", "") or ""),
                "agent": str(item.get("agent_name", "") or ""),
            })
    except Exception:  # noqa: BLE001 - no scheduler on this host: show no tasks
        tasks = []

    # Demo override. OFF unless TAOS_LOCK_DEMO_AGENTS is set, and it only ever
    # ADDS named placeholders to this one read-only lock-screen endpoint -- it
    # writes nothing, creates no agents and changes no other surface. It exists
    # so a demo machine can show a populated lock screen without standing up
    # three real container-backed agents first; anything it lists is a
    # placeholder, not a running process.
    demo = os.environ.get("TAOS_LOCK_DEMO_AGENTS", "").strip()
    if demo:
        existing = {a["name"] for a in agents}
        for raw in demo.split(","):
            # "Name", "Name:framework" or "Name:framework:status text"
            parts = [seg.strip() for seg in raw.split(":")]
            label = parts[0] if parts else ""
            if label and label not in existing:
                agents.append({
                    "name": label,
                    "framework": parts[1].lower() if len(parts) > 1 and parts[1] else "",
                    "framework_icon": _framework_icon(parts[1] if len(parts) > 1 else ""),
                    "status": parts[2] if len(parts) > 2 and parts[2] else "running",
                    "avatar": _avatar_url(label),
                    # Marked at creation so nothing downstream has to work out
                    # which of these entries is a placeholder by elimination.
                    "demo": True,
                })

    # Pending decisions. An agent that is blocked waiting on a human is the one
    # thing on this screen that is actually ASKING for something, so it gets the
    # attention ring -- everything else here is status. Best-effort for the same
    # reason as the container statuses: a host with no decision store should
    # show a lock screen, not a 500.
    #
    # Only the question and its options cross the pre-auth boundary, never the
    # decision's context or notes: the question is a one-line prompt the holder
    # of the phone needs in order to know the phone wants them, while the
    # context is free text an agent may have filled with anything.
    pending: list[dict] = []
    try:
        store = request.app.state.decision_store
        pending = await store.list(status="pending", limit=20)
    except Exception:  # noqa: BLE001 - no decision store on this host: no ring
        pending = []

    # The store returns newest-first. If an agent has asked twice, the question
    # to surface is the one that has been WAITING longest, so walk oldest-first
    # and keep the first hit per agent.
    by_agent: dict[str, dict] = {}
    for d in reversed(pending):
        agent_key = str(d.get("from_agent") or "").strip().lower()
        if agent_key and agent_key not in by_agent:
            by_agent[agent_key] = d

    def _attach(agent: dict) -> None:
        d = by_agent.get(agent["name"].strip().lower())
        if not d:
            return
        options = d.get("options") or []
        labels = [
            str(o.get("label") or o.get("value") or "")
            for o in options
            if isinstance(o, dict)
        ]
        agent["attention"] = True
        agent["decision"] = {
            "id": str(d.get("id") or ""),
            "question": str(d.get("question") or ""),
            "priority": str(d.get("priority") or "normal"),
            "options": [lbl for lbl in labels if lbl][:4],
        }

    for agent in agents:
        _attach(agent)

    # Demo decision. Same single flag as the demo agents, and it is attached to
    # an agent that is already a placeholder -- it never marks a REAL agent as
    # waiting on a human, because a fabricated ring on a real agent would be a
    # lie about the state of the machine. It carries no decision id, which is
    # what the client uses to tell a demo prompt from an answerable one.
    if demo and not any(a.get("attention") for a in agents):
        want = os.environ.get("TAOS_LOCK_DEMO_DECISION_AGENT", "").strip().lower()
        target = None
        for a in agents:
            if not a.get("demo") or a.get("system"):
                continue
            if want and a["name"].strip().lower() != want:
                continue
            target = a
            break
        if target is not None:
            target["attention"] = True
            target["decision"] = {
                "id": "",
                "question": os.environ.get(
                    "TAOS_LOCK_DEMO_DECISION",
                    "Approve \u00a31,340 for the second Raspberry Pi order?",
                ),
                "priority": "normal",
                "options": ["Approve", "Deny"],
                "demo": True,
            }

    # Anything with a status that is not an explicit resting word is doing
    # something -- the demo statuses are free text ("Drafting replies"), so an
    # equality test against "running" would report every busy agent as idle.
    resting = {"", "stopped", "idle", "exited", "error"}
    running = sum(
        1 for a in agents
        if not a.get("system") and a["status"].strip().lower() not in resting
    )
    return JSONResponse({
        "agents": agents[:6],
        "agent_total": len(agents),
        "agent_running": running,
        "tasks": tasks[:4],
        "task_total": len(tasks),
        "threads": bool(demo),
    })



#: Where lock-screen agent avatars are read from. One flat directory of
#: "<slug>.jpg" files, slug being the agent name lowercased with non-alphanumerics
#: collapsed to "-". Overridable so a packaged install can point it at its own
#: data dir rather than this default.
LOCK_AVATAR_DIR = os.environ.get("TAOS_LOCK_AVATAR_DIR", "/var/lib/taos/lock-avatars")


def _avatar_slug(name: str) -> str:
    """Slug for an agent name, restricted to characters that cannot traverse.

    Anything outside [a-z0-9-] is dropped rather than escaped: this value is
    used to build a filesystem path, so a conservative whitelist is the control
    that keeps "../" and absolute paths out, not a sanitiser that tries to spot
    bad input.
    """
    out = []
    for ch in name.strip().lower():
        if ch.isalnum() and ch.isascii():
            out.append(ch)
        elif out and out[-1] != "-":
            out.append("-")
    return "".join(out).strip("-")


@router.get("/lock-avatar/{slug}")
async def lock_avatar(slug: str, request: Request):
    """Serve one lock-screen avatar. Console-only, same reasoning as the widgets.

    The slug is re-derived through the same whitelist before it touches the
    filesystem, so a crafted request cannot address a file outside the avatar
    directory even if the router hands us a path-shaped segment.
    """
    if not _request_is_console(request):
        return JSONResponse({"error": "console only"}, status_code=403)

    safe = _avatar_slug(slug)
    if not safe:
        return JSONResponse({"error": "not found"}, status_code=404)

    path = Path(LOCK_AVATAR_DIR) / f"{safe}.jpg"
    try:
        data = path.read_bytes()
    except OSError:
        return JSONResponse({"error": "not found"}, status_code=404)
    return Response(
        content=data,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


#: Demo conversation scripts for the lock-screen chat sheet, keyed by avatar
#: slug. These exist so a DEMO device can show a populated thread; they are not
#: an agent's real conversation and never touch the chat store.
#:
#: The lock screen renders BEFORE sign-in, so serving an agent's real messages
#: here would hand whoever is holding the phone the contents of every
#: conversation on it. That is why this endpoint serves SCRIPTED TEXT ONLY and
#: 404s when demo mode is off: there is no code path from the lock screen to a
#: real transcript, so there is nothing to get the gate wrong about.
#:
#: Each entry is (days_ago, hh, mm, role, text). Fixed offsets rather than
#: stored timestamps so the thread always reads as "the last few weeks",
#: whenever the demo happens to be run.
_DEMO_THREADS: dict[str, tuple[tuple[int, int, int, str, str], ...]] = {
    "taos-agent": (
        (18, 9, 15, "user", "What can you actually do?"),
        (18, 9, 15, "agent", "I run this device. Open and arrange apps, manage your projects and files, remember things for you, and talk to the other agents on here. If you ask me for something one of them is better at, I hand it over."),
        (16, 21, 30, "user", "the phone felt warm earlier"),
        (16, 21, 31, "agent", "CPU sat at 78\u00b0C for about 20 minutes during the model download. It is back to 41\u00b0C now. Nothing was throttled."),
        (13, 8, 45, "agent", "Storage is at 71%. The biggest single item is the model cache at 9.2 GB. I can clear the unused ones whenever you want."),
        (13, 8, 50, "user", "not yet"),
        (10, 19, 5, "user", "can you put the calendar next to the chat"),
        (10, 19, 5, "agent", "Done \u2014 calendar on the left, chat on the right, split even."),
        (7, 11, 20, "agent", "An update is available: beta.52. It is a packaging fix plus the install reliability work. Nothing on this device depends on it, so it can wait for you."),
        (4, 15, 40, "user", "remind me what we changed on the kiosk"),
        (4, 15, 41, "agent", "The compositor moved from cage to sway so the screen can genuinely power off after 30 seconds. Before that it could only dim, which left the panel lit and touch live."),
        (1, 8, 0, "agent", "Backup completed overnight. 4 of 4 sets, nothing skipped."),
        (0, 7, 35, "agent", "Everything is healthy this morning. Battery 82%, no pending updates, five agents running."),
    ),
    "personal-assistant": (
        (19, 8, 12, "user", "Morning. What does today look like?"),
        (19, 8, 12, "agent", "Three things. Dentist at 11:40, the Hargreaves call moved to 15:00, and your sister's flight lands 19:25. I left a gap either side of the call."),
        (19, 8, 13, "user", "Can you push the dentist?"),
        (19, 8, 15, "agent", "Moved to Thursday 09:15 \u2014 they had a cancellation. Confirmed by text."),
        (17, 20, 41, "agent", "Heads up: the car insurance renews on the 3rd at \u00a3612, up from \u00a3489. I pulled four quotes, cheapest comparable is \u00a3501. Want me to lay them out?"),
        (17, 20, 44, "user", "Yes but not tonight"),
        (17, 20, 44, "agent", "Filed it for Saturday morning."),
        (14, 9, 2, "user", "Did I ever reply to Marcus?"),
        (14, 9, 3, "agent", "No. His last message was the 28th asking about the workshop dates. Draft ready if you want it."),
        (14, 9, 5, "user", "Send it"),
        (14, 9, 5, "agent", "Sent."),
        (11, 13, 30, "agent", "Your passport expires in 5 months. Several countries want 6, so if anything is booked after March it needs renewing now. The form takes about 20 minutes."),
        (8, 7, 55, "user", "Remind me to call mum"),
        (8, 7, 55, "agent", "Every Sunday at 18:00, or just this week?"),
        (8, 7, 56, "user", "every sunday"),
        (8, 7, 56, "agent", "Done. First one this Sunday."),
        (5, 16, 20, "agent", "The Hargreaves invoice is 21 days overdue. I have a polite chase drafted and a firmer one. Neither is sent."),
        (2, 10, 11, "user", "How much did we spend on groceries last month?"),
        (2, 10, 11, "agent", "\u00a3418, across 14 shops. That is \u00a367 up on the month before, almost all of it two big Ocado orders on the 8th and the 22nd."),
        (0, 7, 40, "agent", "Good morning. Quiet day \u2014 one call at 14:00 and the parcel is out for delivery."),
    ),
    "social-media-manager": (
        (20, 11, 5, "agent", "The Tuesday build-in-public post did well: 2.4k views, 41 replies. The thread format is clearly beating the single post."),
        (20, 11, 9, "user", "do more of those"),
        (20, 11, 9, "agent", "Switching the Tuesday and Friday slots to threads. I will keep the Monday one short."),
        (18, 15, 44, "agent", "Someone with 80k followers quoted the roadmap post and called it \u201cthe first self-hosted thing I would actually give my parents\u201d. Worth a reply?"),
        (18, 15, 50, "user", "reply but dont be weird about it"),
        (18, 15, 52, "agent", "Replied: thanked them, no pitch, no link."),
        (15, 9, 30, "agent", "Drafted 6 posts for next week. Three are screenshots, two are short clips, one is the release note. All queued, none published."),
        (12, 18, 2, "user", "why did engagement drop friday"),
        (12, 18, 3, "agent", "Posted at 16:40 local, which is 11:40 for most of the audience \u2014 the worst slot in the data. The 09:00 slot averages 3.1x that."),
        (12, 18, 4, "user", "move everything to 9"),
        (12, 18, 4, "agent", "Moved."),
        (9, 12, 15, "agent", "A reply is getting heated on the pricing post. Two people arguing, neither with us. I have not engaged."),
        (9, 12, 20, "user", "leave it"),
        (6, 8, 48, "agent", "The clip of the phone booting into taOS is the best-performing asset this month by a distance. I can cut three more from the same recording."),
        (6, 8, 49, "user", "yes"),
        (3, 14, 0, "agent", "Follower count crossed 5,000 this morning. Up 640 in three weeks, mostly from the two thread posts."),
        (1, 10, 30, "agent", "Next week's queue is full and reviewed. Nothing goes out without your yes on the release post."),
        (0, 9, 10, "agent", "Morning. One post scheduled for 09:00, already out."),
    ),
    "accountant": (
        (21, 10, 0, "agent", "Q3 books are reconciled. Two transactions I could not categorise \u2014 \u00a3240 on the 14th and \u00a389 on the 22nd, both card, no description."),
        (21, 10, 6, "user", "240 was the monitor, 89 was a domain renewal"),
        (21, 10, 6, "agent", "Filed as equipment and software. Both allowable."),
        (16, 9, 20, "agent", "VAT return is due in 11 days. The figure is \u00a34,182.60. I have it prepared but not submitted."),
        (16, 9, 40, "user", "does that account for the refund"),
        (16, 9, 42, "agent", "It does \u2014 the \u00a3610 refund on the 9th is netted off. Without it the figure would be \u00a34,304.60."),
        (13, 17, 12, "agent", "Your accountant's fee invoice arrived, \u00a3750. It is 40% higher than last year with no explanation attached. Want me to ask?"),
        (13, 17, 30, "user", "ask, politely"),
        (13, 17, 31, "agent", "Asked."),
        (10, 11, 45, "agent", "They replied: the increase is the extra payroll run you added in June. Legitimate. I have approved it for payment on the due date."),
        (7, 8, 30, "agent", "Cash position: \u00a318,420 available, \u00a36,900 committed in the next 30 days. Comfortable."),
        (4, 15, 55, "user", "can we afford the second Pi order"),
        (4, 15, 56, "agent", "Yes. \u00a31,340 leaves \u00a310,180 of headroom after the VAT payment. It is a capital purchase, so it also reduces this year's profit."),
        (4, 15, 58, "user", "order it"),
        (4, 15, 58, "agent", "That is a payment, so it needs your explicit approval in the Decisions app. Raised."),
        (1, 9, 15, "agent", "Two invoices went out this morning, \u00a32,100 total. Both 14-day terms."),
        (0, 8, 5, "agent", "Nothing overdue today. VAT is the only live deadline."),
    ),
    "sales-manager": (
        (20, 9, 40, "agent", "Pipeline is 11 live conversations. Four are warm, two have budget confirmed, the rest are early."),
        (18, 14, 10, "agent", "Westbrook asked for a 20% discount on a 12-seat deal. That is below the floor you set. I have not answered."),
        (18, 14, 22, "user", "offer 10 and annual prepay"),
        (18, 14, 23, "agent", "Sent. Framed as a prepay discount rather than a price cut, so it does not reset their anchor."),
        (15, 11, 30, "agent", "Westbrook accepted. 12 seats, annual, signed. That is the biggest deal this quarter."),
        (15, 11, 31, "user", "nice"),
        (12, 16, 45, "agent", "Two deals have gone quiet for 9 days. Both went silent right after the security questionnaire, which suggests the questionnaire is the problem, not the price."),
        (12, 16, 50, "user", "what do they ask that we fail"),
        (12, 16, 52, "agent", "SOC 2 and a documented incident response. We have neither. Every other question we pass."),
        (9, 10, 5, "agent", "Drafted a one-page security summary that answers 80% of the questionnaire honestly and says plainly what we do not have yet. Ready for your review."),
        (5, 13, 20, "agent", "The honest summary unstuck one of the two. They booked a call for Thursday."),
        (2, 9, 55, "agent", "Renewals: three accounts come up in the next 6 weeks, \u00a38,400 combined. All three have used the product in the last 7 days, so none look at risk."),
        (0, 8, 30, "agent", "One call today at 15:00. Brief is in your inbox."),
    ),
    "customer-service": (
        (21, 8, 0, "agent", "Inbox cleared overnight. 14 tickets, 11 resolved, 3 escalated to you."),
        (19, 12, 30, "agent", "Same install error from four different people this week \u2014 the installer dies silently partway through when the SSH session drops. I filed it rather than answering each one."),
        (19, 12, 40, "user", "good catch"),
        (16, 9, 10, "agent", "The fix shipped. I replied to all four with the release and an apology. Two have already confirmed it works."),
        (14, 15, 20, "agent", "A user is unhappy about the beta cadence \u2014 says updates break things too often. It reads as a real complaint, not noise."),
        (14, 15, 35, "user", "what do you suggest"),
        (14, 15, 37, "agent", "Offer them the stable channel and be honest that beta is beta. I would not promise a slower cadence."),
        (14, 15, 38, "user", "do that"),
        (11, 10, 0, "agent", "They moved to stable and thanked us. Ticket closed."),
        (8, 17, 45, "agent", "Median first reply is now 22 minutes, down from 3 hours when I started. 96% resolved without escalation."),
        (5, 11, 12, "agent", "Someone asked for a refund outside the window. That is a money decision, so it is yours \u2014 raised in Decisions, not answered."),
        (2, 9, 30, "agent", "Quiet week. 6 tickets, all resolved, none escalated."),
        (0, 7, 50, "agent", "Two tickets open, both answered and waiting on the user."),
    ),
}

#: Shown when a demo agent has no scripted thread of its own. Deliberately
#: short: a generic filler thread pretending to be weeks of history would be
#: more misleading than an obviously new conversation.
_DEMO_THREAD_FALLBACK: tuple[tuple[int, int, int, str, str], ...] = (
    (2, 9, 30, "agent", "I am set up and running. Nothing to report yet."),
    (0, 8, 15, "agent", "Still nothing that needs you. I will speak up when there is."),
)


def _demo_enabled() -> bool:
    """Whether the lock screen's demo content is switched on.

    One flag governs the placeholder agents, their scripted threads and the
    demo decision, so a machine cannot end up showing invented conversations
    while believing it is in its real state.
    """
    return bool(os.environ.get("TAOS_LOCK_DEMO_AGENTS", "").strip())


def _demo_thread(slug: str) -> list[dict]:
    """Build one scripted thread as absolute timestamps relative to now."""
    script = _DEMO_THREADS.get(slug, _DEMO_THREAD_FALLBACK)
    now = datetime.now()
    out: list[dict] = []
    for days_ago, hh, mm, role, text in script:
        when = (now - timedelta(days=days_ago)).replace(
            hour=hh, minute=mm, second=0, microsecond=0
        )
        out.append({"role": role, "text": text, "at": when.timestamp()})
    return out


@router.get("/lock-thread/{slug}")
async def lock_thread(slug: str, request: Request):
    """Scripted conversation for the lock screen's chat sheet. Console-only.

    DEMO CONTENT ONLY. This never reads the chat store: the lock screen is
    pre-authentication, so a real transcript served here would be readable by
    anyone holding the phone. With demo mode off there is no thread to serve
    and the answer is 404, which is also what an unknown agent gets.
    """
    if not _request_is_console(request):
        return JSONResponse({"error": "console only"}, status_code=403)
    if not _demo_enabled():
        return JSONResponse({"error": "not found"}, status_code=404)

    safe = _avatar_slug(slug)
    if not safe:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({"slug": safe, "messages": _demo_thread(safe), "demo": True})


@router.post("/pin-login")
async def pin_login(request: Request):
    """Sign in with a PIN. Console-only.

    Refused outright unless the request comes from the device's own screen. The
    refusal is deliberately indistinguishable from "no PIN is set": telling a
    remote caller that PIN sign-in exists here, and that it is merely being
    denied to them, is free reconnaissance for a guesser.
    """
    auth_mgr = request.app.state.auth
    if not _request_is_console(request):
        return JSONResponse({"error": "PIN sign-in is not available"}, status_code=404)

    body, body_err = await _json_object(request)
    if body_err is not None:
        return body_err
    username = (body.get("username") or "").strip() or None
    pin = body.get("pin") or ""

    # Resolve the throttle key before verifying, so a wrong username cannot be
    # used to sidestep the delay by cycling keys.
    record = auth_mgr._pin_user(username)
    limiter_key = (record or {}).get("id") or f"unknown:{username or ''}"

    wait = _pin_limiter.retry_after(limiter_key)
    if wait > 0:
        return JSONResponse(
            {
                "error": f"Too many incorrect PINs. Try again in {wait} seconds.",
                "retry_after": wait,
            },
            status_code=429,
            headers={"Retry-After": str(wait)},
        )

    ok, user_record = auth_mgr.check_pin(pin, username=username)
    if not ok or user_record is None:
        _pin_limiter.record_failure(limiter_key)
        return JSONResponse({"error": "incorrect PIN"}, status_code=401)

    _pin_limiter.reset(limiter_key)
    auth_mgr.update_last_login(user_record["id"])
    # A PIN unlocks THIS device, so the session it mints is the long-lived kind
    # the kiosk needs to survive a reboot without a keyboard being found.
    token = auth_mgr.create_session(
        user_id=user_record["id"],
        long_lived=True,
        user_agent=request.headers.get("user-agent", ""),
    )
    resp = JSONResponse({"ok": True, "user": auth_mgr._public_user(user_record)})
    resp.set_cookie(
        "taos_session", token, httponly=True, samesite="strict",
        max_age=auth_mgr.session_ttl_for(True),
    )
    return resp


@router.post("/pin", dependencies=[Depends(verify_csrf)])
async def set_pin(request: Request):
    """Set or replace the signed-in user's PIN.

    Requires the account PASSWORD in the body even though the caller already
    holds a session. A PIN is a credential that unlocks the device, so minting
    one must cost the real credential -- otherwise anyone who walks up to an
    unlocked screen can quietly add a permanent way back in.
    """
    auth_mgr = request.app.state.auth
    token = request.cookies.get("taos_session", "")
    user_id = auth_mgr.validate_session(
        token, user_agent=request.headers.get("user-agent", "")
    ) if token else None
    if not user_id:
        return JSONResponse({"error": "not authenticated"}, status_code=401)

    body, body_err = await _json_object(request)
    if body_err is not None:
        return body_err

    user = auth_mgr.get_user_by_id(user_id)
    if not user:
        return JSONResponse({"error": "not authenticated"}, status_code=401)
    username = user.get("username", "")

    ok, _ = auth_mgr.check_password(body.get("password") or "", username=username)
    if not ok:
        return JSONResponse({"error": "incorrect password"}, status_code=403)

    try:
        validate_pin(body.get("pin") or "")
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    auth_mgr.set_pin(username, body["pin"])
    _pin_limiter.reset(user_id)
    return JSONResponse({"ok": True, "has_pin": True})


@router.delete("/pin", dependencies=[Depends(verify_csrf)])
async def delete_pin(request: Request):
    """Remove the signed-in user's PIN.

    No password required: turning a credential OFF only ever reduces what an
    attacker could reach, and demanding a typed password to disable PIN would
    be unperformable on the keyboard-less device this feature serves.
    """
    auth_mgr = request.app.state.auth
    token = request.cookies.get("taos_session", "")
    user_id = auth_mgr.validate_session(
        token, user_agent=request.headers.get("user-agent", "")
    ) if token else None
    if not user_id:
        return JSONResponse({"error": "not authenticated"}, status_code=401)
    user = auth_mgr.get_user_by_id(user_id)
    if not user:
        return JSONResponse({"error": "not authenticated"}, status_code=401)
    removed = auth_mgr.clear_pin(user.get("username", ""))
    _pin_limiter.reset(user_id)
    return JSONResponse({"ok": True, "removed": removed, "has_pin": False})


@router.post("/logout", dependencies=[Depends(verify_csrf)])
async def logout(request: Request):
    auth_mgr = request.app.state.auth
    token = request.cookies.get("taos_session")
    if token:
        auth_mgr.revoke_session(token)
    response = RedirectResponse("/auth/login", status_code=303)
    response.delete_cookie("taos_session")
    return response


@router.post("/lock", dependencies=[Depends(verify_csrf)])
async def lock(request: Request):
    """Revoke the current session and clear the cookie."""
    auth_mgr = request.app.state.auth
    token = request.cookies.get("taos_session")
    if token:
        auth_mgr.revoke_session(token)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("taos_session")
    return resp


async def _ensure_native_agent_identity(request: Request, user_id: str) -> None:
    """Mint this install's native agent identity, now that it has an owner.

    Called from BOTH setup paths (JSON and form).  They are two routes into the
    same event -- an install acquiring its first user -- and wiring only the one
    you happened to test is how a fresh install ends up with no agent identity
    while every test passes.  The paired tests below cover both.

    Never raises: an install whose agent identity failed to mint is degraded,
    not broken, and failing setup over it would strand the user on the setup
    page with an account that already exists.
    """
    try:
        from tinyagentos.native_agent_identity import ensure_native_agent_identity

        await ensure_native_agent_identity(
            registry=request.app.state.agent_registry,
            grants=request.app.state.agent_grants,
            data_dir=request.app.state.data_dir,
            signing_key_pem=request.app.state.agent_registry_keypair[0],
            user_id=user_id,
        )
    except Exception:
        logger.exception("native agent identity could not be minted at setup")


@router.post("/setup")
async def auth_setup(request: Request):
    """Onboard the first user. Only works when zero users exist.

    Accepts JSON or form-encoded.

    JSON body: ``{username, full_name, email, password}``. Returns the
    new user's public profile and sets a session cookie.

    Form body: legacy single-password setup (kept for backward compat).
    """
    auth_mgr = request.app.state.auth

    content_type = request.headers.get("content-type", "")
    user_agent = request.headers.get("user-agent", "")
    if "application/json" in content_type:
        body, body_err = await _json_object(request)
        if body_err:
            return body_err
        if auth_mgr.is_configured():
            return JSONResponse({"error": "already configured"}, status_code=409)
        username = (body.get("username") or "").strip()
        full_name = (body.get("full_name") or "").strip()
        email = (body.get("email") or "").strip()
        password = body.get("password") or ""
        if not username:
            return JSONResponse({"error": "username is required"}, status_code=400)
        if not password or len(password) < 8:
            return JSONResponse({"error": "password must be at least 8 characters"}, status_code=400)
        # Validated BEFORE the account is created: a bad PIN must not leave a
        # half-onboarded install behind, and /setup only works while zero users
        # exist, so a second attempt would answer 409 rather than retry.
        pin = (body.get("pin") or "").strip()
        if pin:
            if not _request_is_console(request):
                return JSONResponse(
                    {"error": "a PIN can only be set from this device's own screen"},
                    status_code=400,
                )
            try:
                pin = validate_pin(pin)
            except ValueError as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)
        try:
            user = auth_mgr.setup_user(username, full_name, email, password)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        if pin:
            auth_mgr.set_pin(username, pin)
        long_lived = bool(body.get("auto_login", True))
        # Look up the newly created record to get the ID
        record = auth_mgr.find_user(username)
        user_id = record["id"] if record else ""
        auth_mgr.update_last_login(user_id)
        await _ensure_native_agent_identity(request, user_id)
        token = auth_mgr.create_session(user_id=user_id, long_lived=long_lived, user_agent=user_agent)
        resp = JSONResponse({"ok": True, "user": user})
        if long_lived:
            resp.set_cookie(
                "taos_session", token, httponly=True, samesite="strict",
                max_age=auth_mgr.session_ttl_for(True),
            )
        else:
            resp.set_cookie("taos_session", token, httponly=True, samesite="strict")
        return resp

    # Form-encoded path — used by the no-JS HTML setup page.
    if auth_mgr.is_configured():
        return RedirectResponse("/auth/login", status_code=303)
    form = await request.form()
    username = (form.get("username") or "").strip()
    full_name = (form.get("full_name") or "").strip()
    email = (form.get("email") or "").strip()
    password = form.get("password", "")
    long_lived = bool(form.get("auto_login"))

    if not username:
        return RedirectResponse("/auth/setup?error=username", status_code=303)
    if not password or len(password) < 8:
        return RedirectResponse("/auth/setup?error=password", status_code=303)
    # Same order as the JSON path: reject a bad PIN before creating the account.
    # Silently DROPPED off-console rather than refused — the field is not even
    # rendered there, so anything arriving in it was not typed by this user.
    pin = (form.get("pin") or "").strip()
    if pin and not _request_is_console(request):
        pin = ""
    if pin:
        try:
            pin = validate_pin(pin)
        except ValueError:
            return RedirectResponse("/auth/setup?error=pin", status_code=303)
    try:
        auth_mgr.setup_user(username, full_name, email, password)
    except ValueError:
        return RedirectResponse("/auth/setup?error=conflict", status_code=303)
    if pin:
        auth_mgr.set_pin(username, pin)

    record = auth_mgr.find_user(username)
    user_id = record["id"] if record else ""
    auth_mgr.update_last_login(user_id)
    await _ensure_native_agent_identity(request, user_id)
    token = auth_mgr.create_session(user_id=user_id, long_lived=long_lived, user_agent=user_agent)
    response = RedirectResponse("/desktop", status_code=303)
    if long_lived:
        response.set_cookie(
            "taos_session", token, httponly=True, samesite="strict",
            max_age=auth_mgr.session_ttl_for(True),
        )
    else:
        response.set_cookie("taos_session", token, httponly=True, samesite="strict")
    return response


@router.post("/complete")
async def complete_invite(request: Request):
    """Invited user completes their account setup.

    Body: ``{username, invite_code, full_name, email, password, auto_login?}``
    """
    auth_mgr = request.app.state.auth
    client_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "")

    if _complete_limiter.is_limited(client_ip):
        return JSONResponse(
            {"error": "too many attempts, try again later"},
            status_code=429,
        )

    body, body_err = await _json_object(request)
    if body_err:
        return body_err

    username = (body.get("username") or "").strip()
    invite_code = (body.get("invite_code") or "").strip()
    full_name = (body.get("full_name") or "").strip()
    email = (body.get("email") or "").strip()
    password = body.get("password") or ""

    if not username or not invite_code:
        return JSONResponse({"error": "username and invite_code are required"}, status_code=400)
    if not password or len(password) < 8:
        return JSONResponse({"error": "password must be at least 8 characters"}, status_code=400)

    try:
        user = auth_mgr.complete_invite(username, invite_code, full_name, email, password)
    except ValueError as exc:
        _complete_limiter.record_failure(client_ip)
        return JSONResponse({"error": str(exc)}, status_code=400)

    _complete_limiter.reset(client_ip)
    long_lived = bool(body.get("auto_login", False))
    record = auth_mgr.find_user(username)
    user_id = record["id"] if record else ""
    auth_mgr.update_last_login(user_id)
    # Revoke any existing invite-phase sessions and create a fresh one
    auth_mgr.revoke_user_sessions(user_id)
    token = auth_mgr.create_session(user_id=user_id, long_lived=long_lived, user_agent=user_agent)
    resp = JSONResponse({"ok": True, "user": user})
    if long_lived:
        resp.set_cookie(
            "taos_session", token, httponly=True, samesite="strict",
            max_age=auth_mgr.session_ttl_for(True),
        )
    else:
        resp.set_cookie("taos_session", token, httponly=True, samesite="strict")
    return resp


@router.get("/status")
async def auth_status(request: Request):
    """Single endpoint the UI calls to decide what to render.

    Returns ``{configured, authenticated, user, multi_user, needs_onboarding}``.
    """
    auth_mgr = request.app.state.auth
    configured = auth_mgr.is_configured()
    # An unreadable store reports configured (see AuthManager.is_configured),
    # so tell the UI *why* it can neither sign in nor onboard instead of
    # leaving it to guess from a failing login.
    store_error = None
    try:
        auth_mgr._read_users()
    except AuthStoreCorruptError:
        store_error = "unreadable"
    token = request.cookies.get("taos_session", "")
    # Pass the request's User-Agent so the stolen-cookie binding check runs
    # here exactly as it does in the API middleware. Without it a session
    # whose UA hash no longer matches (browser auto-update rotated the UA)
    # reads authenticated here while every /api/* call 401s, and the SPA's
    # LoginGate remount-loops on that contradiction (the beta.46 PWA
    # refresh-loop, 2026-08-10).
    _ua = request.headers.get("user-agent", "")
    user_id = auth_mgr.validate_session(token, user_agent=_ua) if token else None
    authenticated = user_id is not None

    user = None
    needs_onboarding = False
    # get_user()/session_user() read the same store the probe just failed on,
    # so consulting them here would raise and turn this endpoint into a 500 --
    # exactly the answer the store_error field exists to replace.
    if configured and authenticated and store_error is None:
        user = auth_mgr.get_user(token=token)
        # Check if session user is pending
        if token:
            session_user = auth_mgr.session_user(token)
            if session_user and session_user.get("pending"):
                needs_onboarding = True

    # Whether the sign-in UI should offer a PIN keypad at all. This is the AND
    # of "a PIN exists" and "this request is on the console", so a LAN browser
    # is never told that PIN sign-in exists on this box -- it simply is not
    # offered one, which matches /auth/pin-login answering 404 off-console.
    # Reported only to callers who are not yet signed in; there is nothing for
    # a live session to do with it.
    pin_available = False
    if configured and store_error is None and not authenticated:
        try:
            pin_available = _request_is_console(request) and auth_mgr.has_pin()
        except AuthStoreCorruptError:
            pin_available = False

    return JSONResponse({
        "configured": configured,
        "authenticated": authenticated,
        "user": user,
        "multi_user": auth_mgr.is_multi_user(),
        "needs_onboarding": needs_onboarding,
        "store_error": store_error,
        "pin_available": pin_available,
    })


@router.get("/me")
async def auth_me(request: Request):
    """Return the current user's profile. 401 when not signed in."""
    auth_mgr = request.app.state.auth
    token = request.cookies.get("taos_session", "")
    if not token or auth_mgr.validate_session(
        token, user_agent=request.headers.get("user-agent", "")
    ) is None:
        return JSONResponse({"error": "not authenticated"}, status_code=401)
    user = auth_mgr.get_user(token=token)
    if user is None:
        return JSONResponse({"error": "no user configured"}, status_code=404)
    return JSONResponse({"user": user})


# ------------------------------------------------------------------ #
#  User management endpoints                                           #
# ------------------------------------------------------------------ #

@router.get("/users")
async def list_users(request: Request):
    """List all users. Admin only when multi-user."""
    auth_mgr = request.app.state.auth
    if auth_mgr.is_multi_user():
        ok, err = _require_admin(request)
        if not ok:
            return err
    return JSONResponse({"users": auth_mgr.list_users()})


@router.post("/users")
async def add_user(request: Request):
    """Admin: create a pending user invite. Returns {invite_code}."""
    ok, err = _require_admin(request)
    if not ok:
        return err
    body, body_err = await _json_object(request)
    if body_err:
        return body_err
    username = (body.get("username") or "").strip()
    if not username:
        return JSONResponse({"error": "username is required"}, status_code=400)
    auth_mgr = request.app.state.auth
    token = request.cookies.get("taos_session", "")
    caller = auth_mgr.session_user(token)
    caller_username = caller["username"] if caller else ""
    try:
        code = auth_mgr.add_user_invite(username, caller_username)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"ok": True, "username": username, "invite_code": code})


@router.post("/users/{username}/reset")
async def admin_reset_password(username: str, request: Request):
    """Admin: reset a user's password → new invite code."""
    ok, err = _require_admin(request)
    if not ok:
        return err
    auth_mgr = request.app.state.auth
    token = request.cookies.get("taos_session", "")
    caller = auth_mgr.session_user(token)
    caller_username = caller["username"] if caller else ""
    try:
        code = auth_mgr.admin_reset_password(username, caller_username)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"ok": True, "invite_code": code})


@router.delete("/users/{username}")
async def delete_user(username: str, request: Request):
    """Admin: remove a user."""
    ok, err = _require_admin(request)
    if not ok:
        return err
    auth_mgr = request.app.state.auth
    token = request.cookies.get("taos_session", "")
    caller = auth_mgr.session_user(token)
    caller_username = caller["username"] if caller else ""
    try:
        auth_mgr.delete_user(username, caller_username)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"ok": True})


@router.post("/users/{username}/profile")
async def update_profile(username: str, request: Request):
    """Self: update full_name and/or email."""
    ok, err = _require_self(request, username)
    if not ok:
        return err
    body, body_err = await _json_object(request)
    if body_err:
        return body_err
    full_name = body.get("full_name")
    email = body.get("email")
    auth_mgr = request.app.state.auth
    try:
        user = auth_mgr.update_profile(username, full_name, email)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"ok": True, "user": user})


@router.post("/users/{username}/password")
async def change_password(username: str, request: Request):
    """Self: change password (requires current password)."""
    ok, err = _require_self(request, username)
    if not ok:
        return err
    body, body_err = await _json_object(request)
    if body_err:
        return body_err
    current = body.get("current") or ""
    new_pw = body.get("new") or ""
    if not new_pw or len(new_pw) < 8:
        return JSONResponse({"error": "new password must be at least 8 characters"}, status_code=400)
    auth_mgr = request.app.state.auth
    changed = auth_mgr.change_password(username, current, new_pw)
    if not changed:
        return JSONResponse({"error": "current password is incorrect"}, status_code=401)
    return JSONResponse({"ok": True})
