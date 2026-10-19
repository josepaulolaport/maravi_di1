# Maravi DI1 Backoffice: documentation

These files are the whole specification. They replaced the earlier `docs/` on 2026-10-18; the old set is not authoritative and is kept outside the repository only as a backup.

| File | What it defines | Language |
|---|---|---|
| [maravi_business_specification.md](maravi_business_specification.md) | What the application does: rules, formulas, screens, closed and open decisions (§14) | pt-BR |
| [schema.md](schema.md) | The database design, its integrity decisions and invariants | en |
| [schema.sql](schema.sql) | The PostgreSQL 16 DDL (applies cleanly; see schema.md Status) | SQL |
| [interfaces.md](interfaces.md) | Module contracts, transaction boundaries, HTTP endpoints, DI composition | en |
| [maravi_implementation_plan.md](maravi_implementation_plan.md) | Architecture, repository layout, agent lanes, waves and gates | en |
| [open-questions.md](open-questions.md) | Questions the docs left open and the user's answers (OQ-1 to OQ-46; none open) | en |
| [desafio_tecnico_di1_1.pdf](desafio_tecnico_di1_1.pdf) | The challenge text (authority 1) | pt-BR |

## Order of authority

1. The challenge text ([desafio_tecnico_di1_1.pdf](desafio_tecnico_di1_1.pdf)) sets the minimum requirements. Every interpretation of it and every deliberate deviation from it is in spec §15.
2. `maravi_business_specification.md`, for behaviour and business rules. Where it disagrees with an older document, the most recent explicit decision wins (spec header).
3. `schema.md` / `schema.sql`, `interfaces.md` and `maravi_implementation_plan.md`, for technical execution. Exact endpoint names and SQL types are not business requirements (spec header).
4. Code comments, chat history and assumptions: never authoritative.

When two of these disagree, or a needed answer is missing, it goes to `open-questions.md`. Nobody fills the gap silently.
