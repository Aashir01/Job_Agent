/**
 * The extension's non-negotiables from the spec, enforced rather than asserted
 * in a comment:
 *
 *   §10  "The extension never clicks a site's Submit button. It fills; the
 *         user submits."
 *   §1   nothing outbound happens without the user, so the worker may not
 *         navigate or open tabs on its own.
 *   §6   LinkedIn and Indeed are discovery only — harvested passively from
 *         what is already on screen, never fetched.
 */
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";

const SRC = new URL("../src/", import.meta.url).pathname;
const files = readdirSync(SRC).filter((f) => f.endsWith(".js"));

/** Strip comments and string literals so prose and selectors can't trip a rule. */
function code(source) {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/(^|[^:])\/\/.*$/gm, "$1 ")
    .replace(/`(?:[^`\\]|\\.)*`/g, "``")
    .replace(/"(?:[^"\\]|\\.)*"/g, '""')
    .replace(/'(?:[^'\\]|\\.)*'/g, "''");
}

const sources = Object.fromEntries(
  files.map((f) => [f, code(readFileSync(join(SRC, f), "utf8"))]),
);

test("no script ever submits a page form", () => {
  for (const [name, source] of Object.entries(sources)) {
    assert.doesNotMatch(source, /\.requestSubmit\s*\(/, `${name} calls requestSubmit()`);
    assert.doesNotMatch(source, /\bform\s*\.\s*submit\s*\(/, `${name} calls form.submit()`);
    // .click() on anything at all: the user does the clicking.
    assert.doesNotMatch(source, /\.click\s*\(\s*\)/, `${name} programmatically clicks an element`);
  }
});

test("the fill script never targets a submit control", () => {
  const fill = sources["fill.js"];
  assert.doesNotMatch(fill, /type\s*=\s*.?submit/i, "fill.js selects submit inputs");
  assert.doesNotMatch(fill, /\bbutton\[/i, "fill.js selects page buttons");
});

test("autosubmit is forced false before the payload leaves the worker", () => {
  assert.match(
    sources["background.js"],
    /payload\.autosubmit\s*=\s*false/,
    "background.js must neutralise autosubmit regardless of what the API sent",
  );
});

test("the worker never navigates or opens tabs on its own", () => {
  const background = sources["background.js"];
  for (const forbidden of [/chrome\.tabs\.create/, /chrome\.tabs\.update/, /location\s*=/]) {
    assert.doesNotMatch(background, forbidden, "the service worker must not drive the browser");
  }
});

test("the harvest script only reads the page it is already on", () => {
  const harvest = sources["harvest.js"];
  assert.doesNotMatch(harvest, /\bfetch\s*\(/, "harvest.js must not fetch anything");
  assert.doesNotMatch(harvest, /XMLHttpRequest/, "harvest.js must not use XHR");
  assert.doesNotMatch(harvest, /chrome\.tabs/, "harvest.js must not touch other tabs");
});

test("the manifest stays MV3 and asks for no host beyond the named boards", () => {
  const manifest = JSON.parse(readFileSync(new URL("../manifest.json", import.meta.url), "utf8"));
  assert.equal(manifest.manifest_version, 3);
  assert.ok(!manifest.permissions.includes("tabs"), "'tabs' would read every open page");
  assert.ok(!manifest.permissions.includes("<all_urls>"));
  for (const host of manifest.host_permissions) {
    assert.match(host, /^https:\/\//, `${host} must be https`);
    assert.doesNotMatch(host, /^https:\/\/\*\/\*$/, "no blanket host permission");
  }
});

test("the popup escapes anything it renders from the API", () => {
  const popup = readFileSync(join(SRC, "popup.js"), "utf8");
  assert.match(popup, /function escapeHtml/, "popup.js must escape interpolated values");
  const interpolations = popup.match(/\$\{[^}]+\}/g) ?? [];
  for (const expr of interpolations) {
    assert.match(expr, /escapeHtml\(/, `unescaped interpolation in popup.js: ${expr}`);
  }
});
