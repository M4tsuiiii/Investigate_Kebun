# SAIKI — Active Rebuild Workspace

## Workspace Structure

```
Workspace/
├── GOOD/    ← Reference Knowledge Base (READ-ONLY)
│   ├── app/           Original monolith + domain/infrastructure layers
│   ├── worker/        Worker system + USSD + reactivation + UI
│   ├── tests/         752+ test cases
│   └── docs/          Blueprint, audit reports, business rules
│
└── SAIKI/   ← Active Rebuild Workspace (WRITE-ONLY)
    ├── app/           Domain + infrastructure layers
    ├── worker/        Worker system + USSD + reactivation + UI
    ├── tests/         Test suite
    ├── docs/          Architecture, rebuild plan, design decisions
    ├── scripts/       Utility scripts
    ├── assets/        Static assets
    ├── configs/       Configuration files
    └── logs/          Runtime logs
```

## Roles

| Workspace | Role | Access |
|-----------|------|--------|
| **GOOD** | Reference Knowledge Base | READ-ONLY. Never modify. |
| **SAIKI** | Active Rebuild | WRITE-ONLY. All new code here. |

## Documentation

| Document | Purpose |
|----------|---------|
| `SAIKI/docs/ARCHITECTURE.md` | Layer design, event flow, thread model |
| `SAIKI/docs/REBUILD_PLAN.md` | Phase-by-phase implementation checklist |
| `SAIKI/docs/DESIGN_DECISIONS.md` | Rationale for architectural choices |
| `SAIKI/docs/BUSINESS_RULES_INDEX.md` | All BR/HR rules with status |
| `SAIKI/docs/MIGRATION_NOTES.md` | Migration tracking from GOOD to SAIKI |
| `SAIKI/docs/FUTURE_IDEAS.md` | Future enhancements (low priority) |
| `GOOD/docs/BLUEPRINT_REBUILD_V2.md` | Original architecture design |
| `GOOD/docs/AUDIT_REPORT.md` | Findings from rebuild audit |
| `GOOD/docs/HUNTER-RE-05--BUSINESS_RULE_EXTRACTION.md` | Complete rule extraction |

## Quick Start

```bash
# 1. Review architecture
cat SAIKI/docs/ARCHITECTURE.md

# 2. Check rebuild plan
cat SAIKI/docs/REBUILD_PLAN.md

# 3. Reference business rules
cat SAIKI/docs/BUSINESS_RULES_INDEX.md

# 4. Run tests
cd SAIKI
python -m unittest discover -s tests -p "test_*.py" -v
```

## Rules

1. **NEVER modify GOOD/** — It is the ground truth reference.
2. **All new code in SAIKI/** — This is the active workspace.
3. **Reference docs, not code** — Read GOOD docs, write SAIKI code.
4. **Test everything** — Run full test suite before committing.
5. **Document decisions** — Add rationale to DESIGN_DECISIONS.md.
