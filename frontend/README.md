# Procura AI frontend

Vite 5, React 18, TypeScript (strict), Tailwind 3 with CSS-variable tokens, react-router 6, TanStack Query 5, Recharts, Vitest + Testing Library.

```bash
npm install
npm run dev        # http://localhost:5173, expects the API at http://localhost:8000 (override with VITE_API_URL)
npm run typecheck
npm test
npm run build
```

## Pages

| Page | What it does |
|---|---|
| Overview | Review queue (highest AI risk first, then oldest) and headline counts |
| Requests / Request detail | List, create, and the main screen: intake, quotes, documents, history, **AI assessment** and the separate **human decision** panel |
| Documents | Upload (policies need an admin), extraction with field provenance |
| Vendors | Profiles, gaps, conflicts, admin merge |
| Policies | Policy clauses and a "search the policies" box that shows what the pipeline would retrieve |
| Analytics | Live metrics with their definitions |
| Audit log | Filterable log and hash-chain verification |
| Settings | Persona, AI provider status, approved-supplier list (admin) |

## Honesty rules in the UI

- Mock AI output is labelled as mock wherever it appears; the sidebar shows whether a live model is configured.
- The AI assessment is never styled as a decision. Approving, rejecting and requesting information are only available in the human decision panel, which shows what blocks an approval (same author, insufficient authority, missing reasoning, unreviewed confirmed violations).
- `src/lib/policy.ts` mirrors PRC-001 2.1-2.4 for display only. The backend enforces every rule.

## Limits

No Playwright suite and no screenshots yet (planned for milestones 13-14). The persona picker sends demo headers; it is not authentication.
