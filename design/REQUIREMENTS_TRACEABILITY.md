# UnoArena - Requirements Traceability Matrix

This matrix maps assignment requirements to concrete document sections.
Status values:
- `covered`: section exists and is materially addressed.
- `partial`: section exists but requires deeper completion.
- `missing`: no section currently addresses the requirement.

---

## 1. Submission and Structure

| Requirement | Location | Status |
|---|---|---|
| Root entrypoint (`README.md` or `index.md`) | `design/README.md` | covered |
| One file per major deliverable or clear separation | `design/` folder | covered |
| Markdown-based submission organization | repository root + `specs/` + `design/` | covered |

---

## 2. Mandatory Deliverables

| Deliverable | Primary location | Status |
|---|---|---|
| Domain glossary / ubiquitous language | `design/GLOSSARY.md` | covered |
| Bounded contexts and context map | `design/CONTEXT_MAP.md` | covered |
| Spectator View boundary treatment | `design/CONTEXT_MAP.md` + `specs/CONSTRAINTS.md` section 4 | covered |
| Aggregates, entities, value objects | `design/DOMAIN_MODEL.md` | covered |
| Commands and domain events catalog | `design/COMMANDS_EVENTS.md` | covered |
| Event flow narratives (3 required) | `design/EVENT_FLOWS.md` | covered |
| Edge cases and failure paths | `design/FAILURE_PATHS.md` | covered |
| Consistency and recovery strategy | `design/CONSISTENCY_RECOVERY.md` | covered |
| Open questions and assumptions | `specs/ASSUMPTIONS.md` + open sections in `design/` docs | partial |

---

## 3. EventStorming Method Coverage

| EventStorming requirement | Location | Status |
|---|---|---|
| Main business flows | `design/EVENT_FLOWS.md` sections 1-3 | covered |
| Exceptional flows | `design/FAILURE_PATHS.md` | covered |
| Cross-context interactions via events | `design/CONTEXT_MAP.md` section 2 + `design/COMMANDS_EVENTS.md` | covered |
| Invariants and policy decisions | `design/DOMAIN_MODEL.md` + `design/CONSISTENCY_RECOVERY.md` | covered |

---

## 4. Bo3 Tournament Rule Traceability

| Bo3 requirement | Location | Status |
|---|---|---|
| Best-of-Three format (up to 3 games) | `specs/TOURNAMENT_RULES.md` section 3 | covered |
| Early end at 2 game wins | `specs/TOURNAMENT_RULES.md` section 3 | covered |
| Game 3 if no 2-win player after Game 2 | `specs/TOURNAMENT_RULES.md` section 3 | covered |
| Tie-break order at advancement ties | `specs/TOURNAMENT_RULES.md` section 4 | covered |
| Bo3 events and flow treatment | `design/COMMANDS_EVENTS.md` + `design/EVENT_FLOWS.md` | partial |

---

## 5. Known Remaining Gaps

1. Final deterministic fallback if Bo3 tie remains unresolved after configured tie-breakers.
2. Final event payload schemas and rejection code catalog.
3. Final separation pass: move validated decisions out of assumptions where applicable.

See [MISSING_REQUIREMENTS_PLAN](/Users/mactrucho/Downloads/UNO-system/design/MISSING_REQUIREMENTS_PLAN.md) for prioritized completion sequence.
