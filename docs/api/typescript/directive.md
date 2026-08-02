# directive

Source: `sdk/typescript/src/directive.ts`

## API Reference

### createDirective

Directive — goal/task directive management.
Wraps the corresponding SpacetimeDB reducers for each domain.
/
import type { ClientLike } from "./types";
// ---------------------------------------------------------------------------
// Directive — task directives with status and progress tracking
// ---------------------------------------------------------------------------
/** Create a new directive (goal/task).

---
