### Task 8: `update` command

**Files:**
- Create: `src/commands/update.ts`
- Test: `src/commands/update.test.ts`

**Interfaces:**
- Consumes: `CliCommand` from `../cli.js`; `AxiOutput` from `../output.js`.
- Produces: `runUpdate(): AxiOutput`; `updateCommand: CliCommand` (name `"update"`).

- [ ] **Step 1: Write the failing test**

```typescript
// src/commands/update.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { runUpdate } from "./update.js";

test("runUpdate reports a local install with the upgrade path, no registry call", () => {
  const output = runUpdate();
  assert.equal(output.status, "local install; no registry to check");
  assert.equal(output.upgrade, "git pull && npm run build && npm install -g .");
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `node --test src/commands/update.test.ts`
Expected: FAIL — `Cannot find module './update.js'`.

- [ ] **Step 3: Write the implementation**

```typescript
// src/commands/update.ts
import type { CliCommand } from "../cli.js";
import type { AxiOutput } from "../output.js";

const UPDATE_HELP = `serper-axi update

Report the local install's upgrade path. serper-axi is not published to the
npm registry, so there is no version to check remotely.

Examples:
  serper-axi update`;

export function runUpdate(): AxiOutput {
  return {
    status: "local install; no registry to check",
    upgrade: "git pull && npm run build && npm install -g .",
  };
}

export const updateCommand: CliCommand = {
  name: "update",
  help: UPDATE_HELP,
  run: () => runUpdate(),
};
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `node --test src/commands/update.test.ts`
Expected: PASS, 1/1 test.

- [ ] **Step 5: Commit**

```bash
git add src/commands/update.ts src/commands/update.test.ts
git commit -m "feat: add update command"
```

---

