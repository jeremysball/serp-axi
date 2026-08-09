### Task 2: `SerperAxiError` and exit-code mapping

**Files:**
- Create: `src/errors.ts`
- Test: `src/errors.test.ts`

**Interfaces:**
- Produces: `SerperAxiError` (class, extends `Error`, fields `message: string`, `kind: "usage" | "runtime"`, `help: string`) and
  `exitCodeForError(error: unknown): number` (returns `2` for a `SerperAxiError` with `kind: "usage"`, `1` for `kind: "runtime"` or any
  other thrown value).

- [ ] **Step 1: Write the failing tests**

```typescript
// src/errors.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { SerperAxiError, exitCodeForError } from "./errors.js";

test("SerperAxiError carries message, kind, and help", () => {
  const error = new SerperAxiError("bad input", "usage", "fix it like this");
  assert.equal(error.message, "bad input");
  assert.equal(error.kind, "usage");
  assert.equal(error.help, "fix it like this");
  assert.equal(error.name, "SerperAxiError");
});

test("exitCodeForError returns 2 for a usage error", () => {
  assert.equal(exitCodeForError(new SerperAxiError("m", "usage", "h")), 2);
});

test("exitCodeForError returns 1 for a runtime error", () => {
  assert.equal(exitCodeForError(new SerperAxiError("m", "runtime", "h")), 1);
});

test("exitCodeForError returns 1 for a non-SerperAxiError", () => {
  assert.equal(exitCodeForError(new Error("boom")), 1);
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `node --test src/errors.test.ts`
Expected: FAIL — `Cannot find module './errors.js'` (file doesn't exist yet).

- [ ] **Step 3: Write the implementation**

```typescript
// src/errors.ts
export type SerperAxiErrorKind = "usage" | "runtime";

export class SerperAxiError extends Error {
  readonly kind: SerperAxiErrorKind;
  readonly help: string;

  constructor(message: string, kind: SerperAxiErrorKind, help: string) {
    super(message);
    this.name = "SerperAxiError";
    this.kind = kind;
    this.help = help;
  }
}

export function exitCodeForError(error: unknown): number {
  if (error instanceof SerperAxiError) {
    return error.kind === "usage" ? 2 : 1;
  }
  return 1;
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `node --test src/errors.test.ts`
Expected: PASS, 4/4 tests.

- [ ] **Step 5: Commit**

```bash
git add src/errors.ts src/errors.test.ts
git commit -m "feat: add SerperAxiError and exit-code mapping"
```

---

