// desktop/src/theme/__tests__/light-scheme-arbitrary-values.test.ts
//
// Regression guard for the light-scheme gap in tokens.css. The compatibility
// layer inverted the *plain-fraction* overlay utilities (bg-white/5, …) but
// NOT the arbitrary-value form (bg-white/[0.04]) used by the shared primitives
// (card, button, tabs) and ~126 app surfaces. This test proves the arbitrary
// values now invert too.
//
// Two traps this test is built to avoid:
//   1. It asserts on COMPUTED colour, never on the class name — the class is
//      present in both schemes, so a class-name assertion could never fail.
//   2. It reads tokens.css via node:fs and asserts the load actually happened —
//      `import tokensCss from "../tokens.css"` returns an empty string under
//      this repo's vitest config.
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const TOKENS_CSS = readFileSync(
  resolve(process.cwd(), "src/theme/tokens.css"),
  "utf8",
);

// A stand-in for Tailwind's emitted utilities. In the real app the arbitrary
// value `bg-white/[0.04]` compiles to a white-overlay rule; here we reproduce
// that base rule (specificity (0,1,0)) so the tokens.css inversion
// (:root[data-scheme="light"] …, specificity (0,3,0)) demonstrably overrides it
// in light scheme and leaves it alone in dark scheme.
const TAILWIND_BASE = `
[class~="bg-white/[0.04]"] { background-color: rgba(255, 255, 255, 0.04); }
[class~="bg-white/[0.02]"] { background-color: rgba(255, 255, 255, 0.02); }
[class~="border-white/[0.06]"] { border-color: rgba(255, 255, 255, 0.06); }
[class~="border-white/[0.18]"] { border-color: rgba(255, 255, 255, 0.18); }
`;

function injectCss(css: string): void {
  const style = document.createElement("style");
  style.textContent = css;
  document.head.appendChild(style);
}

function setScheme(scheme: "light" | "dark" | null): void {
  if (scheme === null) document.documentElement.removeAttribute("data-scheme");
  else document.documentElement.setAttribute("data-scheme", scheme);
}

function bgColor(className: string): string {
  const el = document.createElement("div");
  el.className = className;
  document.body.appendChild(el);
  const color = window.getComputedStyle(el).backgroundColor;
  el.remove();
  return color;
}

function borderColor(className: string): string {
  const el = document.createElement("div");
  el.className = className;
  el.style.borderStyle = "solid";
  el.style.borderWidth = "1px";
  document.body.appendChild(el);
  const color = window.getComputedStyle(el).borderTopColor;
  el.remove();
  return color;
}

beforeEach(() => {
  document.head.innerHTML = "";
  document.body.innerHTML = "";
  setScheme(null);
  injectCss(TOKENS_CSS);
  injectCss(TAILWIND_BASE);
});

afterEach(() => {
  document.head.innerHTML = "";
  document.body.innerHTML = "";
  setScheme(null);
});

describe("light-scheme arbitrary-value overlay inversion", () => {
  it("loads tokens.css from disk (not an empty css import)", () => {
    // Trap #2: a css raw import yields "" under vitest; node:fs must be used.
    expect(TOKENS_CSS.length).toBeGreaterThan(1000);
  });

  it("declares inversion rules for the arbitrary-value form", () => {
    // Every distinct arbitrary-value overlay in the codebase must have a rule.
    const required = [
      "bg-white/[0.01]",
      "bg-white/[0.02]",
      "bg-white/[0.03]",
      "bg-white/[0.04]",
      "bg-white/[0.05]",
      "bg-white/[0.06]",
      "bg-white/[0.07]",
      "bg-white/[0.08]",
      "bg-white/[0.1]",
      "border-white/[0.04]",
      "border-white/[0.06]",
      "border-white/[0.08]",
      "border-white/[0.18]",
      "hover:bg-white/[0.03]",
      "hover:bg-white/[0.04]",
      "hover:bg-white/[0.05]",
      "hover:bg-white/[0.06]",
      "hover:bg-white/[0.08]",
      "hover:bg-white/[0.1]",
      "hover:border-white/[0.06]",
    ];
    for (const token of required) {
      expect(TOKENS_CSS, `missing inversion rule for ${token}`).toContain(
        `[class~="${token}"]`,
      );
    }
  });

  it("inverts the computed background across schemes (bg-white/[0.04])", () => {
    setScheme("dark");
    const dark = bgColor("bg-white/[0.04]");
    setScheme("light");
    const light = bgColor("bg-white/[0.04]");
    // Dark keeps the additive white overlay; light flips to subtractive black.
    expect(dark).toBe("rgba(255, 255, 255, 0.04)");
    expect(light).toBe("rgba(0, 0, 0, 0.04)");
    expect(light).not.toBe(dark);
  });

  it("inverts the computed border across schemes (border-white/[0.06])", () => {
    setScheme("dark");
    const dark = borderColor("border-white/[0.06]");
    setScheme("light");
    const light = borderColor("border-white/[0.06]");
    expect(dark).toBe("rgba(255, 255, 255, 0.06)");
    expect(light).toBe("rgba(0, 0, 0, 0.06)");
    expect(light).not.toBe(dark);
  });

  it("inverts every arbitrary background value 1:1", () => {
    const cases: Array<[string, string]> = [
      ["bg-white/[0.01]", "rgba(0, 0, 0, 0.01)"],
      ["bg-white/[0.02]", "rgba(0, 0, 0, 0.02)"],
      ["bg-white/[0.03]", "rgba(0, 0, 0, 0.03)"],
      ["bg-white/[0.04]", "rgba(0, 0, 0, 0.04)"],
      ["bg-white/[0.05]", "rgba(0, 0, 0, 0.05)"],
      ["bg-white/[0.06]", "rgba(0, 0, 0, 0.06)"],
      ["bg-white/[0.07]", "rgba(0, 0, 0, 0.07)"],
      ["bg-white/[0.08]", "rgba(0, 0, 0, 0.08)"],
      ["bg-white/[0.1]", "rgba(0, 0, 0, 0.1)"],
    ];
    setScheme("light");
    for (const [className, expected] of cases) {
      expect(bgColor(className), className).toBe(expected);
    }
  });

  it("inverts every arbitrary border value 1:1", () => {
    const cases: Array<[string, string]> = [
      ["border-white/[0.04]", "rgba(0, 0, 0, 0.04)"],
      ["border-white/[0.06]", "rgba(0, 0, 0, 0.06)"],
      ["border-white/[0.08]", "rgba(0, 0, 0, 0.08)"],
      ["border-white/[0.18]", "rgba(0, 0, 0, 0.18)"],
    ];
    setScheme("light");
    for (const [className, expected] of cases) {
      expect(borderColor(className), className).toBe(expected);
    }
  });
});
