import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { SerpAxiError } from "./errors.ts";
import {
  DEFAULT_FULL_MAX_CHARS,
  DEFAULT_MAX_CHARS,
  FULL_MAX_CHARS_ENV,
  MAX_CHARS_ENV,
  limitFor,
  requestCharLimits,
  resolveCharLimits,
  resolveIncludeMarkup,
  shapeScrapeRecord,
  type CharLimitRequest,
  type CharLimitSources,
  type CharLimits,
  type ShapeOptions,
} from "./scrape-output.ts";

const EVERY_STRING = { kind: "every-string", except: new Set(["url"]) } as const;
const TEXT_FIELD = { kind: "field", key: "text" } as const;
const RERUN = "serp-axi scrape 'https://example.com/a'";
const DEFAULT_LIMITS: CharLimits = { maxChars: DEFAULT_MAX_CHARS, fullMaxChars: DEFAULT_FULL_MAX_CHARS };

const HTML_DOCUMENT = '<!doctype html><html lang="en"><head><title>T</title></head><body><p>hi</p></body></html>';

function shape(record: Record<string, unknown>, overrides: Partial<ShapeOptions> = {}) {
  return shapeScrapeRecord(record, {
    full: false,
    limits: DEFAULT_LIMITS,
    capFlags: "",
    includeMarkup: false,
    rerun: RERUN,
    scope: EVERY_STRING,
    ...overrides,
  });
}

test("shapeScrapeRecord omits a page_html field and names it in markupOmitted", () => {
  const out = shape({ url: "https://example.com/a", markdown: "# Hi", page_html: HTML_DOCUMENT });

  assert.deepEqual(out.markupOmitted, ["page_html"]);
  assert.equal(out.markdown, "# Hi");
  assert.equal(out.url, "https://example.com/a");
  assert.equal(Object.hasOwn(out, "page_html"), false);
});

test("shapeScrapeRecord omits any field holding a whole HTML document, whatever it is called", () => {
  const out = shape({
    url: "https://example.com/a",
    markdown: "# Hi",
    body: `\n  <!DOCTYPE html>${HTML_DOCUMENT.slice("<!doctype html>".length)}`,
    snapshot: '<html lang="en"><body>x</body></html>',
  });

  assert.deepEqual(out.markupOmitted, ["body", "snapshot"]);
  assert.equal(out.markdown, "# Hi");
  assert.equal(Object.hasOwn(out, "body"), false);
  assert.equal(Object.hasOwn(out, "snapshot"), false);
});

test("shapeScrapeRecord treats a field named *html as markup even when it is only a fragment", () => {
  const out = shape({ url: "https://example.com/a", markdown: "# Hi", description_html: "<p>a <b>fragment</b></p>" });

  assert.deepEqual(out.markupOmitted, ["description_html"]);
  assert.equal(Object.hasOwn(out, "description_html"), false);
});

test("shapeScrapeRecord leaves prose that merely mentions a tag untouched", () => {
  const prose = "Use the <div> element, not <b>bold</b> tags.";
  const out = shape({ url: "https://example.com/a", markdown: prose, page_html: HTML_DOCUMENT, note: "<p>fragment</p>" });

  // The count comes first: it proves the omission code ran on this record.
  assert.deepEqual(out.markupOmitted, ["page_html"]);
  assert.equal(out.markdown, prose);
  assert.equal(out.note, "<p>fragment</p>");
});

test("shapeScrapeRecord never omits the declared content field, even when it holds an HTML document", () => {
  const out = shape(
    { url: "https://example.com/a", text: HTML_DOCUMENT, page_html: HTML_DOCUMENT },
    { scope: TEXT_FIELD },
  );

  // A sibling markup field is still omitted, so the keep below is a decision and not a no-op.
  assert.deepEqual(out.markupOmitted, ["page_html"]);
  assert.equal(out.text, HTML_DOCUMENT);
});

test("shapeScrapeRecord keeps html2text: the rule is a name ending in html, not containing it", () => {
  const out = shape({ url: "https://example.com/a", html2text: "EXAMPLE DOMAIN", page_html: HTML_DOCUMENT });

  assert.deepEqual(out.markupOmitted, ["page_html"]);
  assert.equal(out.html2text, "EXAMPLE DOMAIN");
});

test("shapeScrapeRecord with includeMarkup differs from the default only by the omitted fields", () => {
  const record = { url: "https://example.com/a", markdown: "# Hi", page_html: HTML_DOCUMENT };

  const stripped = shape(record);
  const kept = shape(record, { includeMarkup: true });

  assert.deepEqual(stripped.markupOmitted, ["page_html"]);
  assert.deepEqual(kept, record);
});

test("shapeScrapeRecord strips before truncating, so the limit is spent on content", () => {
  const huge = shape({ url: "https://example.com/a", markdown: "short", page_html: `${HTML_DOCUMENT}${"x".repeat(5000)}` });
  const long = shape({ url: "https://example.com/a", markdown: "m".repeat(2000) });

  // The control: a long content field does trigger truncation.
  assert.equal(long.markdownTruncatedFrom, 2000);
  assert.deepEqual(huge.markupOmitted, ["page_html"]);
  assert.equal(huge.markdown, "short");
  assert.equal(Object.hasOwn(huge, "markdownTruncatedFrom"), false);
  assert.equal(Object.hasOwn(huge, "page_htmlTruncatedFrom"), false);
  assert.doesNotMatch(huge.help as string, /--full/);
});

test("shapeScrapeRecord drops an upstream truncation marker that belonged to an omitted field", () => {
  const out = shape({
    url: "https://example.com/a",
    markdown: "# Hi",
    page_html: HTML_DOCUMENT,
    page_htmlTruncatedFrom: 9999,
    markdownTruncatedFrom: 4321,
  });

  assert.deepEqual(out.markupOmitted, ["page_html"]);
  assert.equal(out.markdownTruncatedFrom, 4321);
  assert.equal(Object.hasOwn(out, "page_htmlTruncatedFrom"), false);
});

test("shapeScrapeRecord truncates only the named field in field scope and uses the bare marker", () => {
  const out = shape(
    { url: "https://example.com/a", title: "T".repeat(3000), text: "t".repeat(3000) },
    { scope: TEXT_FIELD },
  );

  assert.equal((out.text as string).length, 1200);
  assert.equal(out.truncatedFrom, 3000);
  assert.equal((out.title as string).length, 3000);
  assert.equal(Object.hasOwn(out, "titleTruncatedFrom"), false);
});

test("shapeScrapeRecord truncates every string except the exempt ones in every-string scope", () => {
  const url = `https://example.com/${"u".repeat(2000)}`;
  const out = shape({ url, markdown: "m".repeat(2000), views: 7 });

  assert.equal(out.url, url);
  assert.equal((out.markdown as string).length, 1200);
  assert.equal(out.markdownTruncatedFrom, 2000);
  assert.equal(out.views, 7);
});

test("shapeScrapeRecord --full raises the limit and reports the cap instead of a rerun hint", () => {
  const under = shape({ url: "https://example.com/a", markdown: "m".repeat(2000) }, { full: true });
  const over = shape({ url: "https://example.com/a", markdown: "m".repeat(DEFAULT_FULL_MAX_CHARS + 5) }, { full: true });

  assert.equal((under.markdown as string).length, 2000);
  assert.equal(Object.hasOwn(under, "help"), false);
  assert.equal((over.markdown as string).length, DEFAULT_FULL_MAX_CHARS);
  assert.match(over.help as string, /capped at 50000 characters even with --full/);
});

test("shapeScrapeRecord help gives a runnable rerun command with the total", () => {
  const out = shape({ url: "https://example.com/a", markdown: "m".repeat(2000) });

  assert.equal(out.help, `Run \`${RERUN} --full\` to see up to 50000 characters (2000 total)`);
});

test("shapeScrapeRecord help leaves out the total when several fields were cut", () => {
  const one = shape({ url: "https://example.com/a", markdown: "m".repeat(2000) });
  const two = shape({ url: "https://example.com/a", markdown: "m".repeat(2000), html2text: "h".repeat(3000) });

  assert.match(one.help as string, /\(2000 total\)/);
  assert.equal(two.markdownTruncatedFrom, 2000);
  assert.equal(two.html2textTruncatedFrom, 3000);
  assert.doesNotMatch(two.help as string, /total/);
});

test("shapeScrapeRecord help offers --include-markup when fields were omitted", () => {
  const out = shape({ url: "https://example.com/a", markdown: "# Hi", page_html: HTML_DOCUMENT });

  assert.equal(out.help, `Run \`${RERUN} --include-markup\` to keep the omitted markup`);
});

test("shapeScrapeRecord help covers both truncation and omission when both happened", () => {
  const out = shape({ url: "https://example.com/a", markdown: "m".repeat(2000), page_html: HTML_DOCUMENT });

  assert.match(out.help as string, /--full/);
  assert.match(out.help as string, /--include-markup/);
});

test("shapeScrapeRecord leaves --include-markup to the caller's rerun string", () => {
  const record = { url: "https://example.com/a", markdown: "m".repeat(2000), page_html: HTML_DOCUMENT };

  // A provider the flag does nothing for passes a rerun without it, and gets no flag back.
  const bare = shape(record, { includeMarkup: true });
  // A provider it matters for names it in its own rerun string.
  const named = shape(record, { includeMarkup: true, rerun: `${RERUN} --include-markup` });

  assert.equal(bare.help, `Run \`${RERUN} --full\` to see up to 50000 characters (2000 total)`);
  assert.equal(named.help, `Run \`${RERUN} --include-markup --full\` to see up to 50000 characters (2000 total)`);
  assert.equal(Object.hasOwn(bare, "markupOmitted"), false);
});

test("shapeScrapeRecord keeps every markup field when nothing but markup is left to show", () => {
  const onlyDocument = shape({ url: "https://example.com/a", content: HTML_DOCUMENT });
  const onlyMarkup = shape({ url: "https://example.com/a", content: HTML_DOCUMENT, page_html: HTML_DOCUMENT });

  assert.equal(onlyDocument.content, HTML_DOCUMENT);
  assert.equal(Object.hasOwn(onlyDocument, "markupOmitted"), false);
  assert.equal(onlyMarkup.page_html, HTML_DOCUMENT);
  assert.equal(onlyMarkup.content, HTML_DOCUMENT);
  assert.equal(Object.hasOwn(onlyMarkup, "markupOmitted"), false);
});

test("shapeScrapeRecord still omits markup once any other text field is there to show", () => {
  const out = shape({ url: "https://example.com/a", error: "timeout", content: HTML_DOCUMENT });

  assert.deepEqual(out.markupOmitted, ["content"]);
  assert.equal(out.error, "timeout");
});

test("shapeScrapeRecord recognises a whole HTML document behind a comment or an XML prolog", () => {
  const saved = `<!-- saved from url=(0020)https://example.com/ -->\n${HTML_DOCUMENT}`;
  const rendered = `<?xml version="1.0" encoding="UTF-8"?>\n<!-- generated -->\n<!DOCTYPE html>${HTML_DOCUMENT.slice("<!doctype html>".length)}`;
  const out = shape({ url: "https://example.com/a", markdown: "# Hi", saved, rendered });

  assert.deepEqual(out.markupOmitted, ["saved", "rendered"]);
});

test("shapeScrapeRecord does not take a comment followed by prose for a document", () => {
  const prose = "<!-- editor's note -->\nThe <html> element is the root of a document.";
  const unclosed = "<!-- never closed <html><body>";
  const out = shape({ url: "https://example.com/a", markdown: "# Hi", prose, unclosed });

  assert.equal(Object.hasOwn(out, "markupOmitted"), false);
  assert.equal(out.prose, prose);
  assert.equal(out.unclosed, unclosed);
});

test("shapeScrapeRecord classifies a field of many comments in linear time", () => {
  // Nested lazy quantifiers backtrack exponentially on this shape; a scan does not.
  const comments = "<!-- c -->".repeat(20000);
  const started = performance.now();
  const out = shape({ url: "https://example.com/a", markdown: "# Hi", comments: `${comments}tail` });

  assert.equal(out.comments, `${comments}tail`.slice(0, 1200));
  assert.ok(performance.now() - started < 1000, "classifying 20000 comments took over a second");
});

test("limitFor is the one place the character limit is chosen", () => {
  assert.equal(limitFor(false, DEFAULT_LIMITS), DEFAULT_MAX_CHARS);
  assert.equal(limitFor(true, DEFAULT_LIMITS), DEFAULT_FULL_MAX_CHARS);
  assert.equal(limitFor(false, { maxChars: 7, fullMaxChars: 9 }), 7);
  assert.equal(limitFor(true, { maxChars: 7, fullMaxChars: 9 }), 9);
});

test("shapeScrapeRecord strips the real Bright Data fixture records", () => {
  const lines = readFileSync(new URL("./fixtures/brightdata-scrape.ndjson", import.meta.url), "utf8")
    .split("\n")
    .filter((line) => line.trim().length > 0);
  const record = JSON.parse(lines[0]) as Record<string, unknown>;

  const out = shape(record);

  assert.equal(typeof record.page_html, "string");
  assert.deepEqual(out.markupOmitted, ["page_html"]);
  assert.equal(out.markdown, record.markdown);
  assert.equal(out.html2text, record.html2text);
  assert.equal(out.page_title, "Example Domain");
});

test("resolveIncludeMarkup defaults to off", () => {
  // The control: a source that is set does switch it on.
  assert.equal(resolveIncludeMarkup({ env: "1" }), true);
  assert.equal(resolveIncludeMarkup({}), false);
  assert.equal(resolveIncludeMarkup({ config: {} }), false);
});

test("resolveIncludeMarkup lets the flag beat env and config", () => {
  assert.equal(resolveIncludeMarkup({ flag: true, env: "0", config: { includeMarkup: false } }), true);
});

test("resolveIncludeMarkup reads env true/1 and false/0 in either case", () => {
  assert.deepEqual(
    ["1", "true", "TRUE", "0", "false", "False"].map((env) => resolveIncludeMarkup({ env })),
    [true, true, true, false, false, false],
  );
});

test("resolveIncludeMarkup lets env beat config in both directions", () => {
  assert.equal(resolveIncludeMarkup({ env: "0", config: { includeMarkup: true } }), false);
  assert.equal(resolveIncludeMarkup({ env: "1", config: { includeMarkup: false } }), true);
});

test("resolveIncludeMarkup falls through an empty env to config", () => {
  assert.equal(resolveIncludeMarkup({ env: "", config: { includeMarkup: true } }), true);
});

test("resolveIncludeMarkup reads the config key", () => {
  assert.equal(resolveIncludeMarkup({ config: { includeMarkup: true } }), true);
  assert.equal(resolveIncludeMarkup({ config: { includeMarkup: false } }), false);
});

test("resolveIncludeMarkup treats a null config value as unset, like the ladder config does", () => {
  assert.equal(resolveIncludeMarkup({ config: { includeMarkup: null } }), false);
  assert.equal(resolveIncludeMarkup({ env: "1", config: { includeMarkup: null } }), true);
});

test("resolveIncludeMarkup rejects an unrecognised env value by name", () => {
  assert.throws(
    () => resolveIncludeMarkup({ env: "yes" }),
    (error: unknown) => {
      assert.ok(error instanceof SerpAxiError);
      assert.equal(error.kind, "usage");
      assert.match(error.message, /SERP_AXI_INCLUDE_MARKUP/);
      assert.match(error.message, /"yes"/);
      return true;
    },
  );
});

test("resolveIncludeMarkup rejects a non-boolean config value by name", () => {
  assert.throws(
    () => resolveIncludeMarkup({ config: { includeMarkup: "yes" } }),
    (error: unknown) => {
      assert.ok(error instanceof SerpAxiError);
      assert.equal(error.kind, "usage");
      assert.match(error.message, /includeMarkup/);
      assert.match(error.message, /JSON boolean/);
      return true;
    },
  );
});

// --- the two character caps ------------------------------------------------

function sources(overrides: Partial<CharLimitSources> = {}): CharLimitSources {
  return { full: false, ...overrides };
}

function usageError(pattern: RegExp) {
  return (error: unknown) => {
    assert.ok(error instanceof SerpAxiError);
    assert.equal(error.kind, "usage");
    assert.match(error.message, pattern);
    return true;
  };
}

test("shapeScrapeRecord's hint offers --full with the real --full cap, not a fixed 50000", () => {
  const record = { url: "https://example.com/a", markdown: "m".repeat(2000) };

  const out = shape(record, { limits: { maxChars: 1200, fullMaxChars: 8000 } });

  assert.equal(out.help, `Run \`${RERUN} --full\` to see up to 8000 characters (2000 total)`);
});

test("shapeScrapeRecord never offers a --full rerun that would show no more than this run did", () => {
  const record = { url: "https://example.com/a", markdown: "m".repeat(2000) };

  // Positive trigger: a --full cap above the default cap still earns the rerun hint.
  const above = shape(record, { limits: { maxChars: 500, fullMaxChars: 501 } });
  assert.match(above.help as string, /--full/);

  // At and below the default cap the rerun would return the same text or less.
  for (const fullMaxChars of [500, 400]) {
    const out = shape(record, { limits: { maxChars: 500, fullMaxChars } });
    assert.equal(out.help, "content is capped at 500 characters (2000 total)", `fullMaxChars ${fullMaxChars}`);
    assert.doesNotMatch(out.help as string, /--full/);
  }
});

test("shapeScrapeRecord under --full reports the --full cap it hit, whatever its value", () => {
  const record = { url: "https://example.com/a", markdown: "m".repeat(2000) };

  const out = shape(record, { full: true, limits: { maxChars: 100, fullMaxChars: 1500 } });

  assert.equal((out.markdown as string).length, 1500);
  assert.match(out.help as string, /capped at 1500 characters even with --full/);
});

test("shapeScrapeRecord on a --full run does not depend on the normal cap", () => {
  // resolveCharLimits leaves the default in `maxChars` on a --full run because
  // nothing reads it; this is the check that nothing does.
  const record = { url: "https://example.com/a", markdown: "m".repeat(2000), page_html: HTML_DOCUMENT };
  const outputs = [1, 100, 1200, 99999].map((maxChars) =>
    shape(record, { full: true, capFlags: " --full", limits: { maxChars, fullMaxChars: 1500 } }),
  );

  assert.equal((outputs[0].markdown as string).length, 1500);
  for (const out of outputs) assert.deepEqual(out, outputs[0]);
});

test("shapeScrapeRecord's --include-markup hint repeats the cap flags the run was given", () => {
  const record = { url: "https://example.com/a", markdown: "m".repeat(2000), page_html: HTML_DOCUMENT };

  // Positive trigger: with no cap flags the hint is the bare rerun, as before.
  assert.match(shape(record).help as string, /Run `serp-axi scrape 'https:\/\/example.com\/a' --include-markup` to keep/);

  const capped = shape(record, { capFlags: " --max-chars 500", limits: { maxChars: 500, fullMaxChars: 50000 } });
  assert.match(capped.help as string, / `serp-axi scrape 'https:\/\/example.com\/a' --max-chars 500 --include-markup` to keep/);

  const full = shape(record, {
    full: true,
    capFlags: " --full --full-max-chars 7000",
    limits: { maxChars: 1200, fullMaxChars: 7000 },
  });
  assert.match(
    full.help as string,
    / `serp-axi scrape 'https:\/\/example.com\/a' --full --full-max-chars 7000 --include-markup` to keep/,
  );
});

test("shapeScrapeRecord's --full hint drops the --max-chars flag, which --full refuses", () => {
  const record = { url: "https://example.com/a", markdown: "m".repeat(2000) };

  const out = shape(record, { capFlags: " --max-chars 500", limits: { maxChars: 500, fullMaxChars: 50000 } });

  assert.equal(out.help, `Run \`${RERUN} --full\` to see up to 50000 characters (2000 total)`);
  assert.doesNotMatch(out.help as string, /--max-chars/);
});

test("requestCharLimits leaves a cap unset when neither flag nor env speaks for it", () => {
  assert.deepEqual(requestCharLimits(sources()), {
    full: false,
    maxChars: undefined,
    fullMaxChars: undefined,
    capFlags: "",
  });
});

test("requestCharLimits lets the flag beat the env, for each cap on its own", () => {
  assert.deepEqual(requestCharLimits(sources({ envMaxChars: "300", envFullMaxChars: "9000" })), {
    full: false,
    maxChars: 300,
    fullMaxChars: 9000,
    capFlags: "",
  });
  assert.deepEqual(requestCharLimits(sources({ flagMaxChars: "400", envMaxChars: "300" })).maxChars, 400);
  assert.deepEqual(
    requestCharLimits(sources({ full: true, flagFullMaxChars: "7000", envFullMaxChars: "9000" })).fullMaxChars,
    7000,
  );
});

test("requestCharLimits checks only the source that wins", () => {
  // Positive trigger: the same bad env value is an error when nothing beats it.
  assert.throws(() => requestCharLimits(sources({ envMaxChars: "abc" })), usageError(/SERP_AXI_MAX_CHARS/));

  assert.equal(requestCharLimits(sources({ flagMaxChars: "5", envMaxChars: "abc" })).maxChars, 5);
});

test("requestCharLimits refuses --max-chars with --full and says how to fix it", () => {
  assert.throws(
    () => requestCharLimits(sources({ full: true, flagMaxChars: "100" })),
    (error: unknown) => {
      assert.ok(error instanceof SerpAxiError);
      assert.equal(error.kind, "usage");
      assert.match(error.message, /--max-chars cannot be combined with --full/);
      assert.match(error.help, /--full-max-chars/);
      return true;
    },
  );
  // Positive trigger: each flag is fine in the run it applies to.
  assert.equal(requestCharLimits(sources({ flagMaxChars: "100" })).maxChars, 100);
  assert.equal(requestCharLimits(sources({ full: true, flagFullMaxChars: "100" })).fullMaxChars, 100);
});

test("requestCharLimits refuses --full-max-chars without --full", () => {
  assert.throws(
    () => requestCharLimits(sources({ flagFullMaxChars: "100" })),
    usageError(/--full-max-chars only applies with --full/),
  );
});

test("requestCharLimits does not call an env cap for the other mode a conflict", () => {
  // The env vars hold a standing preference for both kinds of run.
  const plain = requestCharLimits(sources({ envFullMaxChars: "9000" }));
  assert.equal(plain.fullMaxChars, 9000);

  // Positive trigger: the same env value is read, and wins, on a run that uses it.
  assert.equal(requestCharLimits(sources({ envMaxChars: "300" })).maxChars, 300);
  // A --full run does not conflict with it either; it just never reads it.
  assert.doesNotThrow(() => requestCharLimits(sources({ full: true, envMaxChars: "300" })));
});

test("requestCharLimits never reads the normal cap on a --full run, so a bad value there cannot fail it", () => {
  // Positive trigger: the same bad env value fails a run that uses the normal cap.
  assert.throws(() => requestCharLimits(sources({ envMaxChars: "bad" })), usageError(/SERP_AXI_MAX_CHARS/));

  // The --full rerun a hint suggests after `--max-chars 500` got past the bad value.
  const rerun = requestCharLimits(sources({ full: true, envMaxChars: "bad" }));
  assert.equal(rerun.maxChars, undefined);
  assert.equal(rerun.full, true);

  // The cap the run does use is still checked.
  assert.throws(() => requestCharLimits(sources({ full: true, envFullMaxChars: "bad" })), usageError(/SERP_AXI_FULL_MAX_CHARS/));
});

test("requestCharLimits still checks the --full cap on a run without --full, which names it in a hint", () => {
  assert.throws(() => requestCharLimits(sources({ envFullMaxChars: "bad" })), usageError(/SERP_AXI_FULL_MAX_CHARS/));
  // Positive trigger: a flag that wins over the bad env value clears it.
  assert.equal(requestCharLimits(sources({ full: true, flagFullMaxChars: "5", envFullMaxChars: "bad" })).fullMaxChars, 5);
});

test("requestCharLimits hands back the cap flags as typed, for a rerun command", () => {
  assert.equal(requestCharLimits(sources()).capFlags, "");
  assert.equal(requestCharLimits(sources({ flagMaxChars: "500" })).capFlags, " --max-chars 500");
  assert.equal(requestCharLimits(sources({ full: true })).capFlags, " --full");
  assert.equal(
    requestCharLimits(sources({ full: true, flagFullMaxChars: "7000" })).capFlags,
    " --full --full-max-chars 7000",
  );
  // Env values are standing settings the rerun picks up on its own, so they are not repeated.
  assert.equal(requestCharLimits(sources({ envMaxChars: "300", envFullMaxChars: "9000" })).capFlags, "");
  assert.equal(requestCharLimits(sources({ full: true, envFullMaxChars: "9000" })).capFlags, " --full");
});

test("requestCharLimits rejects anything but a whole number of at least 1, naming the flag", () => {
  const bad = ["", "abc", "0", "00", "-5", "1.5", "1e3", " 7", "0x10", "99999999999999999999"];
  for (const value of bad) {
    assert.throws(() => requestCharLimits(sources({ flagMaxChars: value })), usageError(/--max-chars must be/), `flag ${JSON.stringify(value)}`);
    assert.throws(
      () => requestCharLimits(sources({ full: true, flagFullMaxChars: value })),
      usageError(/--full-max-chars must be/),
      `flag ${JSON.stringify(value)}`,
    );
  }
  // Positive trigger: the edge of the range is accepted, so the rejections above are about the value.
  assert.equal(requestCharLimits(sources({ flagMaxChars: "1" })).maxChars, 1);
  assert.equal(requestCharLimits(sources({ flagMaxChars: String(Number.MAX_SAFE_INTEGER) })).maxChars, Number.MAX_SAFE_INTEGER);
});

test("requestCharLimits names the env var, with an example, when the env value is bad", () => {
  assert.throws(
    () => requestCharLimits(sources({ envMaxChars: "lots" })),
    (error: unknown) => {
      assert.ok(error instanceof SerpAxiError);
      assert.match(error.message, new RegExp(`^${MAX_CHARS_ENV} must be a whole number of characters, got string "lots"`));
      assert.match(error.help, new RegExp(`${MAX_CHARS_ENV}=5000`));
      return true;
    },
  );
  assert.throws(() => requestCharLimits(sources({ envFullMaxChars: "0" })), usageError(new RegExp(`^${FULL_MAX_CHARS_ENV} must be`)));
});

function request(overrides: Partial<CharLimitRequest> = {}): CharLimitRequest {
  return { full: false, capFlags: "", ...overrides };
}

test("resolveCharLimits falls back to the built-in defaults", () => {
  assert.deepEqual(resolveCharLimits(request(), {}), { maxChars: 1200, fullMaxChars: 50000 });
  assert.deepEqual(resolveCharLimits(request(), {}), DEFAULT_LIMITS);
});

test("resolveCharLimits lets a request beat the config, and the config beat the default, for each cap", () => {
  assert.deepEqual(resolveCharLimits(request(), { maxChars: 300, fullMaxChars: 9000 }), { maxChars: 300, fullMaxChars: 9000 });
  assert.deepEqual(resolveCharLimits(request({ maxChars: 50 }), { maxChars: 300, fullMaxChars: 9000 }), {
    maxChars: 50,
    fullMaxChars: 9000,
  });
  assert.deepEqual(resolveCharLimits(request({ fullMaxChars: 70 }), { maxChars: 300, fullMaxChars: 9000 }), {
    maxChars: 300,
    fullMaxChars: 70,
  });
});

test("resolveCharLimits treats a null config value as unset, like the other config keys", () => {
  assert.deepEqual(resolveCharLimits(request(), { maxChars: null, fullMaxChars: null }), DEFAULT_LIMITS);
});

test("resolveCharLimits ignores a bad config value for a cap the request already set", () => {
  // Positive trigger: the same bad value is an error when nothing beats it.
  assert.throws(() => resolveCharLimits(request(), { maxChars: "lots" }), usageError(/maxChars/));

  assert.equal(resolveCharLimits(request({ maxChars: 5 }), { maxChars: "lots" }).maxChars, 5);
});

test("resolveCharLimits requires a JSON integer from the config and names the key", () => {
  const bad: unknown[] = ["300", "abc", 1.5, 0, -1, true, [], {}, Number.MAX_SAFE_INTEGER + 2];
  for (const value of bad) {
    assert.throws(() => resolveCharLimits(request(), { maxChars: value }), usageError(/^maxChars must be a JSON integer|^maxChars must be a whole number/), `maxChars ${JSON.stringify(value)}`);
    assert.throws(() => resolveCharLimits(request(), { fullMaxChars: value }), usageError(/^fullMaxChars must be/), `fullMaxChars ${JSON.stringify(value)}`);
  }
  assert.equal(resolveCharLimits(request(), { maxChars: 1 }).maxChars, 1);
});

test("resolveCharLimits does not read the normal cap's config key on a --full run", () => {
  // Positive trigger: the same bad config value fails a run that uses the normal cap.
  assert.throws(() => resolveCharLimits(request(), { maxChars: "lots" }), usageError(/^maxChars must be/));

  const limits = resolveCharLimits(request({ full: true }), { maxChars: "lots", fullMaxChars: 9000 });
  assert.equal(limits.fullMaxChars, 9000);
  // The default stands in for a cap nothing reads; a configured 300 is not carried along.
  assert.equal(resolveCharLimits(request({ full: true }), { maxChars: 300 }).maxChars, DEFAULT_MAX_CHARS);
  // The cap the run does use is still checked.
  assert.throws(() => resolveCharLimits(request({ full: true }), { fullMaxChars: "lots" }), usageError(/^fullMaxChars must be/));
});

test("the built-in defaults are the numbers the docs name", () => {
  assert.equal(DEFAULT_MAX_CHARS, 1200);
  assert.equal(DEFAULT_FULL_MAX_CHARS, 50000);
});
