# BETA AID Console

The web app of BETA AID: customer service (chat simulator, agent desk, supervisor), the data control plane (readiness
atlas, quality and audit, pipelines, knowledge base) and spec-driven delivery.

Imported from the design prototype built in Lovable (repository `LEONOB2014/pixel-perfect-match`, commit `3a89616`).
That repository stays the design sandbox; changes from it are merged here by hand.

## Architecture rules
- All data access goes through `src/services/*`; pages never import mocks or call `fetch` directly. A screen moves from
  mock to real data by changing its service only.
- `src/services/types.ts` mirrors the BETA AID copilot API exactly (`ChatResponse`, `Trace`, `HandoffPacket`); it is
  the contract with `copilot/`.
- Screens still on mock data say so in the UI ("demo data").
- No customer names: personas are scenario labels and ids, as in the copilot.
- Routing is TanStack Router (TanStack Start).

## Run
```bash
cd console
bun install
bun run dev        # http://localhost:3000 (or the port Vite prints)
bun run test       # vitest
bun run build      # production build
```
