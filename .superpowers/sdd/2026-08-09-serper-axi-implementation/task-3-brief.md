### Task 3: TOON output helpers

**Files:**
- Create: `src/output.ts`
- Test: `src/output.test.ts`

**Interfaces:**
- Consumes: `encode` from `@toon-format/toon`.
- Produces: `AxiOutput = Record<string, unknown>`; `encodeOutput(output: AxiOutput): string` (TOON text, always ending in exactly one
  `\n`); `collapseHomeDirectory(path: string, homeDir: string): string`; `truncate(text: string, limit: number): { text: string;
  truncated: boolean; totalChars: number }`.

- [ ] **Step 1: Write the failing tests**

```typescript
// src/output.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { encodeOutput, collapseHomeDirectory, truncate } from "./output.js";

test("encodeOutput renders TOON with a trailing newline", () => {
  const text = encodeOutput({ count: 2 });
  assert.equal(text, "count: 2\n");
});

test("encodeOutput renders a tabular array", () => {
  const text = encodeOutput({
    results: [
      { position: 1, title: "a" },
      { position: 2, title: "b" },
    ],
  });
  assert.match(text, /results\[2\]\{position,title\}:/);
});

test("collapseHomeDirectory replaces a leading home path with ~", () => {
  assert.equal(collapseHomeDirectory("/home/user/.local/bin/serper-axi", "/home/user"), "~/.local/bin/serper-axi");
});

test("collapseHomeDirectory leaves a non-home path untouched", () => {
  assert.equal(collapseHomeDirectory("/usr/local/bin/serper-axi", "/home/user"), "/usr/local/bin/serper-axi");
});

test("truncate passes short text through unchanged", () => {
  const result = truncate("hello", 10);
  assert.deepEqual(result, { text: "hello", truncated: false, totalChars: 5 });
});

test("truncate cuts long text and reports the total length", () => {
  const result = truncate("hello world", 5);
  assert.equal(result.text, "hello");
  assert.equal(result.truncated, true);
  assert.equal(result.totalChars, 11);
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `node --test src/output.test.ts`
Expected: FAIL — `Cannot find module './output.js'`.

- [ ] **Step 3: Write the implementation**

```typescript
// src/output.ts
import { encode } from "@toon-format/toon";

export type AxiOutput = Record<string, unknown>;

export function encodeOutput(output: AxiOutput): string {
  const text = encode(output);
  return text.endsWith("\n") ? text : `${text}\n`;
}

export function collapseHomeDirectory(path: string, homeDir: string): string {
  if (homeDir.length > 0 && path.startsWith(homeDir)) {
    return `~${path.slice(homeDir.length)}`;
  }
  return path;
}

export interface Truncated {
  text: string;
  truncated: boolean;
  totalChars: number;
}

export function truncate(text: string, limit: number): Truncated {
  const totalChars = text.length;
  if (totalChars <= limit) {
    return { text, truncated: false, totalChars };
  }
  return { text: text.slice(0, limit), truncated: true, totalChars };
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `node --test src/output.test.ts`
Expected: PASS, 6/6 tests.

- [ ] **Step 5: Commit**

```bash
git add src/output.ts src/output.test.ts
git commit -m "feat: add TOON output, home-path collapse, and truncation helpers"
```

---

