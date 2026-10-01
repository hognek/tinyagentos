// @vitest-environment node
/**
 * Build-artefact guard for the SPA shell's pre-paint script (#655, #58).
 *
 * `desktop/index.html` loads the reduce-effects boot script from a
 * root-absolute `/boot.js` — Vite's public-dir convention. That URL is only
 * correct because the build is configured with `base: "/desktop/"`, which
 * rewrites root-absolute references to `/desktop/...`; the shell the server
 * actually hands out is the built `static/desktop/index.html`, not the source
 * file. The Python guard in tests/test_security_headers.py asserts against the
 * *source* shell, so on its own it proves the base rewrite only by hand (jaylfc
 * review on #3226). This test runs a real `vite build` and inspects the emitted
 * shell, so dropping `base` or switching the reference to an absolute URL fails
 * here instead of silently shipping a pre-paint script that 404s.
 *
 * The same build's public-dir copy of `boot.js` is checked too: the rewritten
 * URL must resolve to a file that actually applies the saved preference.
 *
 * Follows the sw-bundle.test.ts pattern (build into a temp dir, inspect the
 * emitted artefact) — the bundler output, not the source, is the contract.
 */
import { describe, it, expect, beforeAll, afterAll } from "vitest";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

const DESKTOP = path.resolve(__dirname, "..", "..");
const VITE_BIN = path.join(DESKTOP, "node_modules", "vite", "bin", "vite.js");

let outDir = "";
let shell = "";

beforeAll(() => {
  outDir = mkdtempSync(path.join(tmpdir(), "taos-shell-build-"));
  // Drop the vitest-injected mode so the child is a normal production build.
  const env = { ...process.env };
  delete env.NODE_ENV;
  delete env.VITEST;
  delete env.VITEST_MODE;
  execFileSync(
    process.execPath,
    [VITE_BIN, "build", "--outDir", outDir, "--emptyOutDir", "--logLevel", "error"],
    { cwd: DESKTOP, env, stdio: ["ignore", "pipe", "pipe"] },
  );
  shell = readFileSync(path.join(outDir, "index.html"), "utf8");
}, 600_000);

afterAll(() => {
  if (outDir) rmSync(outDir, { recursive: true, force: true });
});

/** The `src` of every real <script> start tag (a `data-src` does not count). */
function scriptSrcs(html: string): string[] {
  const srcs: string[] = [];
  for (const [, attrs] of html.matchAll(/<script\b([^>]*)>/gi)) {
    const src = /(?:^|\s)src\s*=\s*("([^"]*)"|'([^']*)')/i.exec(attrs);
    if (src) srcs.push(src[2] ?? src[3] ?? "");
  }
  return srcs;
}

describe("built SPA shell keeps the pre-paint script working", () => {
  it("rewrites the source /boot.js reference to /desktop/boot.js", () => {
    expect(scriptSrcs(shell)).toContain("/desktop/boot.js");
  });

  it("leaves no reference at the un-rewritten root path", () => {
    // If `base: "/desktop/"` is dropped (or the tag is hard-coded absolute),
    // the served shell would request /boot.js, which the desktop route does not
    // serve — the saved reduce-effects preference would never apply pre-paint.
    expect(scriptSrcs(shell)).not.toContain("/boot.js");
  });

  it("ships boot.js at the build root so the rewritten URL resolves", () => {
    const boot = readFileSync(path.join(outDir, "boot.js"), "utf8");
    expect(boot).toContain("taos-reduce-effects");
    expect(boot).toContain('setAttribute("data-perf", "reduced")');
  });

  it("emits the pre-paint script as a blocking tag in <head>", () => {
    const head = shell.slice(0, shell.search(/<\/head>/i));
    expect(head).toMatch(/<script\b[^>]*\bsrc\s*=\s*"\/desktop\/boot\.js"[^>]*>/i);
    expect(head).not.toMatch(/<script\b[^>]*\b(?:defer|async)\b/i);
  });

  it("keeps every emitted script external (CSP script-src 'self')", () => {
    // Inline scripts are blocked by the app's CSP, so the built shell must have
    // a src on every <script>. Comments are stripped first: the shell's own
    // explanation of the change mentions script markup in prose.
    const withoutComments = shell.replace(/<!--[\s\S]*?-->/g, "");
    const tags = withoutComments.match(/<script\b/gi)?.length ?? 0;
    expect(tags).toBeGreaterThan(0);
    expect(scriptSrcs(withoutComments)).toHaveLength(tags);
  });
});
