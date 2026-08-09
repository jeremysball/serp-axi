### Task 1: Repo scaffold

**Files:**
- Create: `package.json`
- Create: `tsconfig.json`
- Create: `.mise.toml`
- Create: `.gitignore`

**Interfaces:**
- Produces: the `npm run build`, `npm run typecheck`, `npm test`, and `npm run check` scripts every later task relies on.

- [ ] **Step 1: Write `package.json`**

```json
{
  "name": "serper-axi",
  "version": "0.1.0",
  "private": true,
  "description": "AXI-compliant CLI for Serper (Google Search API) search and page-scrape queries",
  "type": "module",
  "bin": {
    "serper-axi": "dist/bin/serper-axi.js"
  },
  "engines": {
    "node": ">=26"
  },
  "scripts": {
    "build": "tsc",
    "typecheck": "tsc --noEmit",
    "test": "node --test \"src/**/*.test.ts\"",
    "check": "npm run typecheck && npm test"
  },
  "dependencies": {
    "@toon-format/toon": "2.3.1"
  },
  "devDependencies": {
    "typescript": "7.0.2",
    "@types/node": "26.2.0"
  }
}
```

- [ ] **Step 2: Write `tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2023",
    "module": "NodeNext",
    "moduleResolution": "NodeNext",
    "lib": ["ES2023"],
    "outDir": "dist",
    "rootDir": "src",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "types": ["node"]
  },
  "include": ["src/**/*.ts"],
  "exclude": ["dist", "node_modules"]
}
```

- [ ] **Step 3: Write `.mise.toml`**

```toml
[tools]
node = "26.5.1"
```

- [ ] **Step 4: Verify `.gitignore` already covers the package's build artifacts**

`.gitignore` was created at repo root before this plan's worktree existed (it needed to ignore `.worktrees/` before any worktree
was created). Read it and confirm it already contains `node_modules/` and `dist/` alongside `.worktrees/`:

```
.worktrees/
node_modules/
dist/
```

If either package line is missing, add it — but never remove the `.worktrees/` line: this file is shared with `main` through the
eventual merge, and dropping that line would stop `main` from ignoring future worktrees.

- [ ] **Step 5: Install dependencies and verify exact pinned versions landed**

Run: `npm install`

Then verify:

```bash
npm ls @toon-format/toon typescript @types/node
```

Expected: `@toon-format/toon@2.3.1`, `typescript@7.0.2`, `@types/node@26.2.0`, no errors, no "invalid" markers.

- [ ] **Step 6: Commit**

```bash
git add package.json package-lock.json tsconfig.json .mise.toml .gitignore
git commit -m "chore: scaffold serper-axi package"
```

---

