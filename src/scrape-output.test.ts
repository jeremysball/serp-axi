import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { SerpAxiError } from "./errors.ts";
import {
  DEFAULT_LIMIT,
  FULL_LIMIT,
  limitFor,
  resolveIncludeMarkup,
  shapeScrapeRecord,
  type ShapeOptions,
} from "./scrape-output.ts";

const EVERY_STRING = { kind: "every-string", except: new Set(["url"]) } as const;
const TEXT_FIELD = { kind: "field", key: "text" } as const;
const RERUN = "serp-axi scrape 'https://example.com/a'";

const HTML_DOCUMENT = '<!doctype html><html lang="en"><head><title>T</title></head><body><p>hi</p></body></html>';

function shape(record: Record<string, unknown>, overrides: Partial<ShapeOptions> = {}) {
  return shapeScrapeRecord(record, {
    full: false,
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
  const over = shape({ url: "https://example.com/a", markdown: "m".repeat(FULL_LIMIT + 5) }, { full: true });

  assert.equal((under.markdown as string).length, 2000);
  assert.equal(Object.hasOwn(under, "help"), false);
  assert.equal((over.markdown as string).length, FULL_LIMIT);
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
  assert.equal(limitFor(false), DEFAULT_LIMIT);
  assert.equal(limitFor(true), FULL_LIMIT);
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
