---
name: record-decision
description: Record a user decision in the Maravi DI1 docs — close the open question, add it to the business specification's closed list, and propagate it to every affected doc in one change. Integrator only; use after the user answers an OQ or a spec gap, or changes a decision.
---

# Record a decision (integrator only)

Only the **user** decides. Record a decision only when you have the user's words.

1. **Close the question** in `docs/open-questions.md`. Move it to "Answered" with:
   - the date and time;
   - the user's words, quoted exactly;
   - the decision, in numbered items.
2. **Add it to the closed list** in `docs/maravi_business_specification.md` §14 ("Fechado"), in Portuguese, as one line. Remove it from "Aberto" if it is listed there.
3. **Propagate it, in the same change, to every affected doc:**
   - the spec sections;
   - `schema.md` and `schema.sql`. If the schema changes, apply the DDL to a fresh PostgreSQL 16 and report the result;
   - `interfaces.md`;
   - the implementation plan;
   - `CLAUDE.md` §2, if it states the rule.
4. **Verify:**
   - grep for old wording that is now wrong;
   - check every relative link.
5. **Hand it over:**
   - commit (skill `commit`, type `docs`, scope `docs`); the recorded words must be the user's;
   - open a PR, which the user or the merger session the user authorised merges (CLAUDE.md §4);
   - tell the affected lanes what changed.
