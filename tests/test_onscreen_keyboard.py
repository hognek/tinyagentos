"""The on-screen keyboard on the server-rendered auth pages.

taOS targets touchscreens with no keyboard, under `chromium --kiosk` on a bare
X session where no IME can be summoned. These assert the two things that make
the keyboard trustworthy: it is really there on both pages, and adding it did
not cost the no-JavaScript guarantee those pages are written for.
"""
from __future__ import annotations

import re

import pytest

from tinyagentos.routes.auth import (
    _LOCK_SCREEN_SCRIPT as LOCK_SCRIPT,
    _login_page,
    _pin_panel_html,
    _setup_page,
)
from tinyagentos.routes.onscreen_keyboard import (
    OSK_SCRIPT,
    OSK_SCRIPT_PATH,
    OSK_STYLE,
    osk_assets,
)


@pytest.fixture()
def login_console():
    """Login page as the device's own screen sees it (PIN offered)."""
    return _login_page("", multi_user=False, next_url="", pin_available=True)


@pytest.fixture()
def login_remote():
    """Login page as a LAN browser sees it (no PIN)."""
    return _login_page("", multi_user=False, next_url="", pin_available=False)


class TestKeyboardIsPresentWhereItIsNeeded:
    def test_login_page_ships_the_keyboard(self, login_remote):
        assert f'src="{OSK_SCRIPT_PATH}"' in login_remote

    def test_setup_page_ships_the_keyboard(self):
        """Onboarding is the FIRST thing a new touchscreen device does; without
        a keyboard here the device cannot be set up at all."""
        page = _setup_page("")
        assert f'src="{OSK_SCRIPT_PATH}"' in page

    def test_keyboard_is_offered_even_without_a_pin(self, login_remote):
        """The keyboard is an accessibility affordance, not part of PIN sign-in;
        a password user on a touchscreen needs it just as much."""
        assert 'id="pin-panel"' not in login_remote
        assert f'src="{OSK_SCRIPT_PATH}"' in login_remote

    def test_assets_ship_style_and_script_together(self):
        out = osk_assets()
        assert "<style>" in out
        assert OSK_STYLE.strip()[:20] in out
        assert f'src="{OSK_SCRIPT_PATH}"' in out

    def test_script_is_never_inlined(self):
        """taOS sends `script-src 'self'`, which silently refuses inline
        <script> blocks. An inlined keyboard produces correct-looking HTML that
        the browser drops at execution time -- the page renders, the keyboard
        never appears, and any test asserting on the markup still passes. This
        is the assertion that would have caught it."""
        out = osk_assets()
        assert OSK_SCRIPT.strip()[:40] not in out, "keyboard script must not be inlined"
        assert "defer" in out


class TestNoJavaScriptGuaranteeIsIntact:
    """The auth pages are deliberately server-rendered and work with JS off.

    The keyboard is added at runtime by script, so with JS disabled the page
    must still be a plain, submittable HTML form.
    """

    def test_password_form_still_posts_without_script(self, login_console):
        assert 'method="POST"' in login_console
        assert 'action="/auth/login"' in login_console
        assert 'name="password"' in login_console

    def test_setup_form_still_posts_without_script(self):
        page = _setup_page("")
        assert 'method="POST"' in page
        assert 'action="/auth/setup"' in page
        for field in ("username", "full_name", "email", "password"):
            assert f'name="{field}"' in page

    def test_no_key_markup_is_server_rendered(self, login_console):
        """Keys are built by script. If they were in the HTML they would appear
        for no-JS users as dead buttons that type nothing."""
        assert 'class="osk-key"' not in login_console

    def test_password_panel_is_only_hidden_when_a_pin_is_offered(self, login_remote):
        """With no PIN there is nothing to switch to, so the form must not start
        hidden — that would leave a no-JS user with a blank page."""
        assert re.search(r'id="pw-panel"[^>]*\shidden', login_remote) is None


class TestKeysCannotSubmitTheForm:
    def test_every_key_is_type_button(self):
        """A bare <button> in a form defaults to submit. A keyboard whose keys
        each submit the login form would be worse than no keyboard at all."""
        assert 'b.type = "button"' in OSK_SCRIPT
        # The toggle lives inside the page too and must not submit either.
        assert 'toggle.type = "button"' in OSK_SCRIPT

    def test_pin_controls_are_type_button(self, login_console):
        for el_id in ("pin-submit", "use-password"):
            match = re.search(rf'<button[^>]*id="{el_id}"', login_console)
            assert match, f"{el_id} not found"
            assert 'type="button"' in match.group(0)


class TestFocusIsNotStolenFromTheField:
    def test_pointerdown_is_cancelled(self):
        """Without preventDefault on pointerdown the first tap blurs the input
        and the second types into nothing."""
        assert 'panel.addEventListener("pointerdown"' in OSK_SCRIPT
        assert "ev.preventDefault()" in OSK_SCRIPT

    def test_nothing_closes_the_panel_on_blur(self):
        """The keyboard must not close because focus moved.

        Measured in Chromium at 1024x600: tapping a button focuses it on
        pointerdown, which blurred the field; the old focusout handler then hid
        the panel, un-reserving ~276px, which reflowed the card out from under
        the finger — so mouseup landed elsewhere and no `click` was ever fired.
        "Sign in with PIN" produced pointerdown and no click: PIN sign-in was
        dead to touch. Visibility now follows the toggle only.
        """
        assert 'addEventListener("focusout"' not in OSK_SCRIPT
        # hide() may only be reached from the explicit on/off path.
        assert OSK_SCRIPT.count("hide();") == 1
        assert "function setEnabled" in OSK_SCRIPT

    def test_reserved_space_is_measured_not_guessed(self):
        """A fixed vh guess is wrong for at least one of {numeric, letters} x
        {600px panel, desktop window}, and being wrong low puts the card's
        buttons under the keys."""
        assert "panel.offsetHeight" in OSK_SCRIPT
        assert 'document.body.style.paddingBottom = h ? h + "px" : ""' in OSK_SCRIPT

    def test_a_card_too_tall_for_the_space_left_stays_reachable(self):
        """The auth pages centre their card in a flex body; centring a card
        taller than the remaining space puts its actions behind the keys with
        nothing to scroll."""
        rule = re.search(r"body\.osk-open\s*\{([^}]*)\}", OSK_STYLE)
        assert rule, "no body.osk-open rule"
        assert "flex-start" in rule.group(1)
        assert "overflow-y: auto" in rule.group(1)


class TestAccessibility:
    def test_toggle_exposes_pressed_state(self):
        assert 'toggle.setAttribute("aria-pressed"' in OSK_SCRIPT

    def test_panel_is_a_labelled_group(self):
        assert 'panel.setAttribute("role", "group")' in OSK_SCRIPT
        assert 'aria-label", "On-screen keyboard"' in OSK_SCRIPT

    def test_every_key_carries_an_accessible_name(self):
        assert 'b.setAttribute("aria-label"' in OSK_SCRIPT

    def test_state_changes_are_announced(self):
        assert 'live.setAttribute("aria-live", "polite")' in OSK_SCRIPT

    def test_keyboard_activation_path_exists(self):
        """Tab+Enter never fires pointerdown, so a click path must exist too or
        the keyboard is unusable by switch/AT users."""
        assert 'panel.addEventListener("click"' in OSK_SCRIPT

    def test_touch_targets_meet_the_minimum(self):
        """44px is the floor for a finger target; keys must not go below it."""
        sizes = [int(n) for n in re.findall(r"min-height:\s*(\d+)px", OSK_STYLE)]
        assert sizes, "no key height declared"
        assert min(sizes) >= 44

    def test_no_key_preview_popup(self):
        """Phone keyboards magnify the pressed glyph. On a wall-mounted panel
        that renders the password to the whole room."""
        assert "osk-preview" not in OSK_STYLE
        assert "preview" not in OSK_SCRIPT.lower()


class TestNumericLayoutForPin:
    def test_numeric_layout_selected_by_inputmode(self):
        assert 'mode === "numeric"' in OSK_SCRIPT

    def test_pin_field_suppresses_the_shared_keyboard_on_the_lock_screen(self, login_console):
        """The console page is the lock screen, which draws its OWN keypad.

        inputmode="none" is what keeps the shared on-screen keyboard (and the
        compositor's Wayland keyboard) from opening a SECOND keypad over the
        first -- and the OSK's open state re-anchors the page to the top of the
        viewport, which is what pushed the passcode off a tall phone screen.
        """
        match = re.search(r'<input[^>]*id="pin-input"[^>]*>', login_console)
        assert match
        assert 'inputmode="none"' in match.group(0)

    def test_pin_field_still_requests_the_numeric_pad_without_a_keypad(self):
        """Off the lock screen the shared numeric OSK is still the way in.

        _pin_panel_html is what the non-keypad caller renders, so this asserts
        the branch a future non-lock-screen page would get -- without it the
        keypad=False path is untested and could rot to inputmode="none" too,
        leaving that page with no keyboard at all.
        """
        panel = _pin_panel_html("/desktop", keypad=False)
        match = re.search(r'<input[^>]*id="pin-input"[^>]*>', panel)
        assert match
        assert 'inputmode="numeric"' in match.group(0)
        assert 'data-osk-submit="pin-submit"' in match.group(0)

    def test_pin_field_is_masked(self, login_console):
        match = re.search(r'<input[^>]*id="pin-input"[^>]*>', login_console)
        assert 'type="password"' in match.group(0)

    def test_pin_field_is_not_autofilled_or_saved(self, login_console):
        match = re.search(r'<input[^>]*id="pin-input"[^>]*>', login_console)
        assert 'autocomplete="off"' in match.group(0)

    def test_shared_keyboards_enter_routing_is_still_wired(self):
        """data-osk-submit routes Enter to the PIN handler; without it Enter
        would fall through to the password form and post an empty password.

        The lock screen does not use the shared keyboard, but the mechanism must
        stay intact for the keypad=False rendering that does.
        """
        panel = _pin_panel_html("/desktop", keypad=False)
        match = re.search(r'<input[^>]*id="pin-input"[^>]*>', panel)
        assert 'data-osk-submit="pin-submit"' in match.group(0)
        assert "data-osk-submit" in OSK_SCRIPT

    def test_lock_screen_keypad_can_actually_submit(self, login_console):
        """A keypad with no reachable submit is a phone nobody can unlock.

        There is no auto-submit -- the PIN's length is server-side, so the page
        cannot know when the user has finished typing. #pin-submit is therefore
        the ONLY way in, and a CSS rule that hides it strands the user on the
        lock screen with no way to authenticate.
        """
        assert 'id="pin-submit"' in login_console
        assert not re.search(
            r"\.lockscreen\s+#pin-submit\s*\{[^}]*display:\s*none", login_console
        )

    def test_keypad_is_reachable_without_a_gesture(self, login_console):
        """The keypad is no longer always on screen, so the way to it must be a
        real, focusable BUTTON.

        The swipe is a shortcut. If the only route to the passcode were a drag,
        anyone who cannot make that drag -- or any device where the touch layer
        is misbehaving -- would be locked out of their own phone with the
        keypad rendered but hidden.
        """
        match = re.search(r'<button[^>]*id="ls-unlock-btn"[^>]*>', login_console)
        assert match, "no unlock button"
        assert 'type="button"' in match.group(0)
        assert "ls-unlock-btn" in LOCK_SCRIPT
        assert 'unlockBtn.addEventListener("click", openPasscode)' in LOCK_SCRIPT

    def test_resting_screen_hides_the_passcode_but_not_by_hiding_submit(self, login_console):
        """The passcode is hidden as a SHEET -- the whole shell slides away --
        rather than by hiding its controls one by one.

        This is the rule the submit-visibility test protects, stated for the new
        resting state: whatever hides the passcode must be reversible by the
        unlock control, and #pin-submit must never be the thing being hidden.
        """
        assert 'setAttribute("data-sheet", "none")' in LOCK_SCRIPT
        assert re.search(
            r'\.lockscreen:not\(\[data-sheet="passcode"\]\)\s+\.ls-foot\s*\{[^}]*transform',
            login_console,
        ), "the passcode shell is not hidden by the sheet transform"
        assert not re.search(
            r"\.lockscreen[^{]*#pin-submit\s*\{[^}]*display:\s*none", login_console
        )

    def test_islands_are_buttons_not_a_list(self, login_console):
        """An island opens a sheet, so it must be operable by keyboard too."""
        assert 'el.setAttribute("role", "button")' in LOCK_SCRIPT
        assert 'el.setAttribute("tabindex", "0")' in LOCK_SCRIPT
        # A role="list" whose children are buttons is an invalid a11y tree.
        assert 'id="ls-activity" role="group"' in login_console

    def test_lock_chrome_does_not_select_text_like_a_browser(self, login_console):
        """Press-and-hold is bound to the islands. Without this, chromium starts
        a text selection on that exact gesture and raises the copy callout."""
        assert re.search(
            r"body\.lockscreen-on\s*\{[^}]*user-select:\s*none", login_console
        )
        assert re.search(
            r"\.ls-msg,\s*\.ls-compose-input\s*\{[^}]*user-select:\s*text", login_console
        ), "selection should still work inside the conversation"

    def test_lock_screen_renders_its_own_keypad(self, login_console):
        assert 'id="ls-pad"' in login_console
        for digit in "0123456789":
            assert f'data-digit="{digit}"' in login_console
        assert 'data-action="back"' in login_console


class TestPinPanelIsConsoleOnly:
    def test_panel_absent_off_console(self, login_remote):
        assert 'id="pin-panel"' not in login_remote
        assert 'id="use-pin"' not in login_remote

    def test_pin_endpoint_not_named_off_console(self, login_remote):
        """The page must not even mention PIN sign-in to a remote browser."""
        assert "/auth/pin-login" not in login_remote
        assert "/auth/pin-panel.js" not in login_remote

    def test_panel_present_on_console(self, login_console):
        assert 'id="pin-panel"' in login_console
        assert 'src="/auth/pin-panel.js"' in login_console

    def test_password_remains_reachable_from_the_pin_panel(self, login_console):
        """A PIN that fails must never strand the user with no way back."""
        assert 'id="use-password"' in login_console


class TestPinPanelChrome:
    """Rendered-state defects seen on a 1024x600 panel, not markup presence."""

    def test_empty_error_bar_is_not_rendered(self, login_console):
        """`.error` carries a red background and border, and the live region
        has to exist before it has anything to say — so without this the page
        shows a bare red slab having failed at nothing."""
        assert re.search(r"#pin-error:empty\s*\{[^}]*display:\s*none", login_console)

    def test_primary_pin_action_is_a_real_touch_target(self, login_console):
        """#pin-submit is type=button (a submit would post the password form),
        so it misses `button[type="submit"]` styling entirely and renders as a
        ~21px native button — half the 44px floor, on a touchscreen."""
        rule = re.search(r"#pin-submit\s*\{([^}]*)\}", login_console)
        assert rule, "#pin-submit carries no styling of its own"
        found = re.search(r"min-height:\s*(\d+)px", rule.group(1))
        assert found and int(found.group(1)) >= 44

    def test_card_sheds_height_while_the_keyboard_is_open(self, login_console):
        """The keypad takes 291px of a 600px panel. Without this the card's
        buttons are only reachable by scrolling a page that gives no sign it
        scrolls."""
        assert "body.osk-open .card" in login_console


class TestFocusedFieldIsClearOfTheKeys:
    def test_reveal_measures_against_the_panel_not_the_viewport(self):
        """scrollIntoView treats the strip the keyboard sits on as visible —
        the panel is position:fixed OVER the viewport — so a field level with
        the top row is left tucked behind the keys."""
        assert "scrollIntoView(" not in OSK_SCRIPT  # the call, not the comment
        assert "panel.getBoundingClientRect().top" in OSK_SCRIPT
        assert "window.scrollBy" in OSK_SCRIPT


def test_insert_honours_maxlength():
    """Writing .value directly bypasses the browser's own maxlength.

    The setup PIN field is maxlength=12, so without a clamp the numeric pad
    could enter a 13th digit. This asserts the clamp is PRESENT in the served
    script; that it BEHAVES is proven on the device (a script that is served
    but refused by CSP passes any assertion about its text -- see
    test_script_is_never_inlined for why that distinction is load-bearing).
    """
    from tinyagentos.routes.onscreen_keyboard import OSK_SCRIPT

    assert 'getAttribute("maxlength")' in OSK_SCRIPT
    assert "if (room <= 0) return;" in OSK_SCRIPT
