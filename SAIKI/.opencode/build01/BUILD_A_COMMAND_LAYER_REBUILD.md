# BUILD-A: COMMAND LAYER REBUILD — IMPLEMENTATION PLAN

**Date**: 2026-09-10
**Mode**: PLAN → IMPLEMENTATION
**Status**: PENDING APPROVAL

---

## 1. Problem Statement

Current skills have AT/USSD commands hardcoded as strings. This creates:
- Wrong USSD codes (CekNikSkill sends `*185#` instead of `*888*4444*1#`)
- No centralized command management
- No parser reuse across skills
- No way to change commands without modifying skill code

**Goal**: All modem commands come from a centralized registry. Skills never store command strings.

---

## 2. Current State (what's broken)

### 2.1 Hardcoded Commands in Skills

| Skill | Hardcoded Command | Correct Command | Issue |
|-------|-------------------|-----------------|-------|
| CekNomorSkill | `AT+CNUM` + configurable USSD | OK (configurable) | — |
| CekStatusSkill | `AT+CPIN?` | OK | — |
| CekNikSkill | `*185#` | `*888*4444*1#` | **WRONG CODE** |
| CekKkSkill | `*185#` | cache/DB/Telegram | **WRONG** — KK not from USSD |
| InjectReaktivasiSkill | configurable (default `*185#`) | `*888*89*1*{NIK}*{KK}#` | Dynamic — needs template |
| VerifyGraceSkill | `*185#` | `*185#` | OK — but no grace_date parser |
| RestartHardwareSkill | `ATZ` | OK | — |
| ResetHardwareSkill | serial + `AT+CPIN?` | TO BE REMOVED | Only restart kept |

### 2.2 Inline Parsers in Skills

| Skill | Inline Parser | Should Use Registry |
|-------|---------------|---------------------|
| CekNomorSkill | `_parse_cnum()`, `_parse_ussd_number()` | ParserRegistry |
| CekStatusSkill | uses `parse_cpin_response()` from domain | Already external |
| VerifyGraceSkill | `_classify_card_status()`, `_extract_grace_date()` | ParserRegistry |
| RestartHardwareSkill | none (uses `check_modem()`) | — |
| InjectReaktivasiSkill | none | Needs `classify_injection_response()` |

---

## 3. Target Architecture

```
┌─────────────────────────────────────────────────────┐
│                    SKILL LAYER                       │
│  Skill.execute(port, skill_resolver, command_id)    │
│    → reads CommandProfile from CommandRegistry      │
│    → sends command via ATClient / USSDRuntime       │
│    → parses via ParserRegistry                      │
│    → returns SkillResult                            │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────┴──────────────────────────────┐
│                COMMAND REGISTRY                      │
│  get_command("cek_nomor") → CommandProfile          │
│  get_command("cek_nik") → CommandProfile            │
│  ... (8 commands, one per skill)                    │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────┴──────────────────────────────┐
│                COMMAND PROFILE                       │
│  name: "cek_nik"                                    │
│  command_type: "ussd"                               │
│  ussd_code: "*888*4444*1#"                          │
│  parser: "extract_nik"                              │
│  output_fields: ["nik"]                             │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────┴──────────────────────────────┐
│                PARSER REGISTRY                       │
│  get_parser("extract_nik") → Callable               │
│  get_parser("extract_grace_date") → Callable        │
│  get_parser("classify_card_status") → Callable      │
│  get_parser("classify_injection_response") → Callable│
│  ... (17+ parsers from GOOD)                        │
└─────────────────────────────────────────────────────┘
```

---

## 4. New Files to Create

### 4.1 `SAIKI/worker/command_registry.py`

```python
"""CommandRegistry — Central store for all modem commands.

Skills read commands from this registry. No hardcoded strings in skills.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional


@dataclass(frozen=True)
class CommandProfile:
    """Definition of a single modem command.
    
    Attributes:
        name: Unique command name (matches skill name)
        command_type: "at" | "ussd" | "composite" | "hardware"
        at_command: AT command string (for type "at")
        ussd_code: USSD code string (for type "ussd")
        ussd_template: USSD template with {NIK}, {KK} placeholders (for type "composite")
        parser_name: Name of parser function in ParserRegistry
        output_fields: Fields this command produces
        timeout: Default timeout in seconds
        description: Human-readable description
    """
    name: str
    command_type: str  # "at" | "ussd" | "composite" | "hardware"
    at_command: str = ""
    ussd_code: str = ""
    ussd_template: str = ""
    parser_name: str = ""
    output_fields: tuple = ()
    timeout: float = 5.0
    description: str = ""


class CommandRegistry:
    """Central registry for all modem commands.
    
    Singleton pattern — one instance shared across all skills.
    """
    
    def __init__(self) -> None:
        self._commands: Dict[str, CommandProfile] = {}
        self._register_defaults()
    
    def _register_defaults(self) -> None:
        """Register all built-in commands."""
        defaults = [
            CommandProfile(
                name="cek_nomor",
                command_type="composite",
                at_command="AT+CNUM",
                ussd_code="",  # configurable via settings
                parser_name="parse_cnum",
                output_fields=("number", "grace_date", "card_status"),
                timeout=5.0,
                description="Cek nomor HP via AT+CNUM dengan fallback USSD",
            ),
            CommandProfile(
                name="cek_status",
                command_type="at",
                at_command="AT+CPIN?",
                parser_name="parse_cpin_response",
                output_fields=("cpin_state", "sim_ready"),
                timeout=3.0,
                description="Cek status SIM via AT+CPIN?",
            ),
            CommandProfile(
                name="cek_nik",
                command_type="ussd",
                ussd_code="*888*4444*1#",
                parser_name="extract_nik",
                output_fields=("nik",),
                timeout=30.0,
                description="Cek NIK via USSD *888*4444*1#",
            ),
            CommandProfile(
                name="cek_kk",
                command_type="cache",  # not USSD — from cache/DB/Telegram
                parser_name="extract_kk",
                output_fields=("kk", "source"),
                timeout=5.0,
                description="Cek KK dari cache, database, atau Telegram",
            ),
            CommandProfile(
                name="inject_reaktivasi",
                command_type="composite",
                ussd_template="*888*89*1*{NIK}*{KK}#",
                parser_name="classify_injection_response",
                output_fields=("injected", "provisional", "card_status"),
                timeout=30.0,
                description="Inject reaktivasi via USSD dengan NIK dan KK",
            ),
            CommandProfile(
                name="verify_grace",
                command_type="ussd",
                ussd_code="*185#",
                parser_name="verify_grace_response",
                output_fields=("grace_date_after", "card_status", "success", "outcome"),
                timeout=30.0,
                description="Verifikasi grace date via USSD *185#",
            ),
            CommandProfile(
                name="restart_hardware",
                command_type="at",
                at_command="ATZ",
                parser_name="check_modem",
                output_fields=("restart_sent", "modem_online"),
                timeout=5.0,
                description="Restart modem via ATZ — tunggal atau massal",
            ),
        ]
        for cmd in defaults:
            self._commands[cmd.name] = cmd
    
    def get(self, name: str) -> Optional[CommandProfile]:
        """Get command profile by name."""
        return self._commands.get(name)
    
    def register(self, profile: CommandProfile) -> None:
        """Register a new command profile."""
        self._commands[profile.name] = profile
    
    def list_all(self) -> List[str]:
        """List all registered command names."""
        return list(self._commands.keys())
    
    def get_ussd_code(self, name: str, **kwargs) -> str:
        """Get resolved USSD code for a command.
        
        For template commands, kwargs should include NIK, KK, etc.
        """
        profile = self.get(name)
        if not profile:
            return ""
        if profile.ussd_code:
            return profile.ussd_code
        if profile.ussd_template:
            return profile.ussd_template.format(**kwargs)
        return ""
```

### 4.2 `SAIKI/worker/parser_registry.py`

```python
"""ParserRegistry — Central store for all response parsers.

Parsers are pure functions: raw_response → parsed_data dict.
Skills look up parsers by name from this registry.
"""

from __future__ import annotations
import re
from datetime import datetime, date
from typing import Any, Callable, Dict, Optional

from app.domain.enums import CardStatus, CpinState
from app.domain.classifier import parse_cpin_response as _domain_parse_cpin


def _parse_cnum(raw: str) -> Dict[str, Any]:
    """Parse MSISDN from +CNUM response."""
    if not raw:
        return {"number": None}
    match = re.search(r'\+CNUM:\s*"",\s*"(\d+)"', raw)
    return {"number": match.group(1).strip() if match else None}


def _extract_number_from_ussd(raw: str) -> Dict[str, Any]:
    """Extract phone number from USSD response text."""
    if not raw:
        return {"number": None}
    match = re.search(r'(0\d{9,12})', raw)
    if match:
        return {"number": match.group(1)}
    match = re.search(r'(\+62\d{9,12})', raw)
    return {"number": match.group(1) if match else None}


def _extract_grace_date(raw: str) -> Dict[str, Any]:
    """Extract grace date from *185# response.
    
    Pattern: 'Active 24-08-2026'
    """
    if not raw:
        return {"grace_date": None}
    match = re.search(r'Active\s+(\d{2}-\d{2}-\d{4})', raw)
    return {"grace_date": match.group(1) if match else None}


def _classify_card_status_from_grace(raw: str) -> Dict[str, Any]:
    """Classify card status by calculating masa aktif from grace_date.
    
    Rules (from PENUNJANG.md):
    - grace_date - today > 0 → AKTIF
    - -30 ≤ grace_date - today ≤ 0 → TENGGANG
    - grace_date - today < -30 → HANGUS
    """
    grace_result = _extract_grace_date(raw)
    grace_str = grace_result.get("grace_date")
    if not grace_str:
        return {"card_status": CardStatus.UNKNOWN.value}
    
    try:
        grace_date = datetime.strptime(grace_str, "%d-%m-%Y").date()
        today = date.today()
        delta = (grace_date - today).days
        
        if delta > 0:
            status = CardStatus.AKTIF
        elif -30 <= delta <= 0:
            status = CardStatus.TENGGANG
        else:
            status = CardStatus.HANGUS
        
        return {"card_status": status.value, "masa_aktif_days": delta}
    except (ValueError, TypeError):
        return {"card_status": CardStatus.UNKNOWN.value}


def _extract_nik(raw: str) -> Dict[str, Any]:
    """Extract NIK from *888*4444*1# response.
    
    Pattern: 'NIK : 31750554xxxxxxxx'
    """
    if not raw:
        return {"nik": None}
    match = re.search(r'NIK\s*:\s*(\d{16})', raw)
    return {"nik": match.group(1) if match else None}


def _extract_kk(raw: str) -> Dict[str, Any]:
    """Extract KK from response (if available)."""
    if not raw:
        return {"kk": None, "source": "none"}
    match = re.search(r'KK\s*:\s*(\d{16})', raw)
    return {"kk": match.group(1) if match else None, "source": "ussd"}


def _classify_injection_response(raw: str) -> Dict[str, Any]:
    """Classify injection response from *888*89*1*{NIK}*{KK}#.
    
    Rules:
    - HANGUS → "Permintaan kamu sedang di proses" → provisional
    - TENGGANG → "Nomor xxx sedang dalam masa tenggang" → direct success
    - AKTIF → "Layanan Hanya Dapat Dilakukan Hanya Pada Kartu Hanggus" → failed
    """
    if not raw:
        return {"injected": False, "provisional": False, "card_status": "unknown"}
    
    raw_lower = raw.lower()
    
    if "sedang di proses" in raw_lower or "diproses" in raw_lower:
        return {"injected": True, "provisional": True, "card_status": "HANGUS"}
    
    if "masa tenggang" in raw_lower:
        return {"injected": True, "provisional": False, "card_status": "TENGGANG"}
    
    if "kartu hangus" in raw_lower or "hanya pada kartu hangus" in raw_lower:
        return {"injected": False, "provisional": False, "card_status": "AKTIF"}
    
    if "berhasil" in raw_lower or "success" in raw_lower:
        return {"injected": True, "provisional": False, "card_status": "unknown"}
    
    return {"injected": False, "provisional": False, "card_status": "unknown"}


def _verify_grace_response(raw: str) -> Dict[str, Any]:
    """Full verification: extract grace_date + classify card_status."""
    grace_result = _extract_grace_date(raw)
    status_result = _classify_card_status_from_grace(raw)
    return {**grace_result, **status_result}


def _check_modem(raw: str = "") -> Dict[str, Any]:
    """Check modem online status (used after ATZ restart)."""
    return {"modem_online": True}  # If we got here, modem responded


class ParserRegistry:
    """Central registry for all response parsers.
    
    Parsers are pure functions: raw_response → parsed_data dict.
    """
    
    def __init__(self) -> None:
        self._parsers: Dict[str, Callable] = {}
        self._register_defaults()
    
    def _register_defaults(self) -> None:
        """Register all built-in parsers."""
        defaults = {
            "parse_cnum": _parse_cnum,
            "extract_number_from_ussd": _extract_number_from_ussd,
            "extract_grace_date": _extract_grace_date,
            "classify_card_status_from_grace": _classify_card_status_from_grace,
            "extract_nik": _extract_nik,
            "extract_kk": _extract_kk,
            "classify_injection_response": _classify_injection_response,
            "verify_grace_response": _verify_grace_response,
            "check_modem": _check_modem,
            # Domain parser — re-exported for consistency
            "parse_cpin_response": lambda raw: {"cpin_state": _domain_parse_cpin(raw).value},
        }
        for name, func in defaults.items():
            self._parsers[name] = func
    
    def get(self, name: str) -> Optional[Callable]:
        """Get parser function by name."""
        return self._parsers.get(name)
    
    def register(self, name: str, func: Callable) -> None:
        """Register a new parser function."""
        self._parsers[name] = func
    
    def parse(self, name: str, raw: str, **kwargs) -> Dict[str, Any]:
        """Execute a parser by name."""
        parser = self.get(name)
        if not parser:
            return {"error": f"Unknown parser: {name}"}
        try:
            return parser(raw, **kwargs) if kwargs else parser(raw)
        except Exception as e:
            return {"error": f"Parser error: {e}"}
    
    def list_all(self) -> list:
        """List all registered parser names."""
        return list(self._parsers.keys())
```

---

## 5. Files to Modify

### 5.1 Skill Refactoring (8 skills → 7, reset removed)

Each skill gets `command_registry` injected via `__init__`. The `execute()` method reads its `CommandProfile` from the registry instead of using hardcoded strings.

**Pattern for refactored skill**:
```python
class CekNikSkill(Skill):
    def __init__(self, ussd_runtime, command_registry, parser_registry):
        self._ussd_runtime = ussd_runtime
        self._cmd_reg = command_registry
        self._parser_reg = parser_registry
    
    def execute(self, port, **kwargs):
        profile = self._cmd_reg.get("cek_nik")  # reads from registry
        ussd_code = profile.ussd_code  # "*888*4444*1#"
        raw = ussd_runtime.dial(ussd_code, timeout=profile.timeout)
        parsed = self._parser_reg.parse(profile.parser_name, raw)  # "extract_nik"
        return self._success(port, parsed)
```

**Skills to refactor**:

| Skill | Changes |
|-------|---------|
| CekNomorSkill | Read `AT+CNUM` + USSD code from registry. Use `parse_cnum` + `extract_number_from_ussd` + `extract_grace_date` + `classify_card_status_from_grace` from parser registry |
| CekStatusSkill | Read `AT+CPIN?` from registry. Use `parse_cpin_response` from parser registry |
| CekNikSkill | Read `*888*4444*1#` from registry (FIX). Use `extract_nik` from parser registry |
| CekKkSkill | Read from cache (type="cache"). Use `extract_kk` from parser registry |
| InjectReaktivasiSkill | Read `*888*89*1*{NIK}*{KK}#` template from registry. Use `classify_injection_response` from parser registry |
| VerifyGraceSkill | Read `*185#` from registry. Use `verify_grace_response` from parser registry |
| RestartHardwareSkill | Read `ATZ` from registry. Use `check_modem` from parser registry |
| ~~ResetHardwareSkill~~ | DELETED — only restart kept |

### 5.2 System Bootstrap Updates

- Create `CommandRegistry` and `ParserRegistry` instances
- Pass them to skill factories
- Remove `ResetHardwareSkillFactory`

### 5.3 Workflow Registry Updates

- Remove `hardware_reset` workflow
- Keep 8 workflows (was 9)

### 5.4 Controller Updates

- Remove `cmd.reset_modem` route
- Keep 20 routes (was 21)

---

## 6. Test Plan

### 6.1 New Tests

| Test File | Tests |
|-----------|-------|
| `tests/test_command_registry.py` | TestCommandRegistry: get, register, list, get_ussd_code, template resolution |
| `tests/test_parser_registry.py` | TestParserRegistry: get, register, parse, list, error handling |
| `tests/test_parsers.py` | Test all 10 parsers: parse_cnum, extract_number_from_ussd, extract_grace_date, classify_card_status_from_grace, extract_nik, extract_kk, classify_injection_response, verify_grace_response, check_modem, parse_cpin_response |

### 6.2 Updated Tests

All existing skill tests need mock updates to inject `command_registry` and `parser_registry`:

- `test_skill_cek_nomor.py` — add mock registries
- `test_skill_cek_status.py` — add mock registries
- `test_skill_cek_nik.py` — add mock registries
- `test_skill_cek_kk.py` — add mock registries
- `test_skill_inject_reaktivasi.py` — add mock registries
- `test_skill_verify_grace.py` — add mock registries
- `test_skill_restart_hardware.py` — add mock registries
- `test_workflow_registry.py` — update count from 9→8
- `test_workflow_definitions.py` — no changes needed

---

## 7. Implementation Order

### Phase 1: Create Registries (no breaking changes)

1. Create `SAIKI/worker/command_registry.py` — `CommandProfile` + `CommandRegistry`
2. Create `SAIKI/worker/parser_registry.py` — `ParserRegistry` + all 10 parsers
3. Create `tests/test_command_registry.py` — unit tests
4. Create `tests/test_parser_registry.py` — unit tests
5. Create `tests/test_parsers.py` — parser unit tests
6. Run all tests: `python -m unittest discover`

### Phase 2: Refactor Skills

7. Refactor `CekNomorSkill` — inject registries, read from registry
8. Refactor `CekStatusSkill` — inject registries, read from registry
9. Refactor `CekNikSkill` — inject registries, read from registry (FIX: `*888*4444*1#`)
10. Refactor `CekKkSkill` — inject registries, read from registry (cache type)
11. Refactor `InjectReaktivasiSkill` — inject registries, read from registry (template)
12. Refactor `VerifyGraceSkill` — inject registries, read from registry
13. Refactor `RestartHardwareSkill` — inject registries, read from registry
14. Delete `reset_hardware.py` — only restart kept
15. Run all tests: `python -m unittest discover`

### Phase 3: Wire Registries

16. Update `system_bootstrap.py` — create registries, pass to factories
17. Update `workflow/registry.py` — remove `hardware_reset`
18. Update `worker/ui/controller.py` — remove `cmd.reset_modem` route
19. Update existing skill tests — add mock registries
20. Run all tests: `python -m unittest discover`

### Phase 4: Verify & Report

21. Full test pass: `python -m unittest discover`
22. Create `BUILD_A_REPORT.md`

---

## 8. Deliverables

| # | File | Action |
|---|------|--------|
| 1 | `SAIKI/worker/command_registry.py` | CREATE |
| 2 | `SAIKI/worker/parser_registry.py` | CREATE |
| 3 | `SAIKI/tests/test_command_registry.py` | CREATE |
| 4 | `SAIKI/tests/test_parser_registry.py` | CREATE |
| 5 | `SAIKI/tests/test_parsers.py` | CREATE |
| 6 | `SAIKI/worker/skills/cek_nomor.py` | MODIFY |
| 7 | `SAIKI/worker/skills/cek_status.py` | MODIFY |
| 8 | `SAIKI/worker/skills/cek_nik.py` | MODIFY |
| 9 | `SAIKI/worker/skills/cek_kk.py` | MODIFY |
| 10 | `SAIKI/worker/skills/inject_reaktivasi.py` | MODIFY |
| 11 | `SAIKI/worker/skills/verify_grace.py` | MODIFY |
| 12 | `SAIKI/worker/skills/restart_hardware.py` | MODIFY |
| 13 | `SAIKI/worker/skills/reset_hardware.py` | DELETE |
| 14 | `SAIKI/worker/system_bootstrap.py` | MODIFY |
| 15 | `SAIKI/workflow/registry.py` | MODIFY |
| 16 | `SAIKI/worker/ui/controller.py` | MODIFY |
| 17 | `SAIKI/tests/test_skill_*.py` (7 files) | MODIFY |
| 18 | `SAIKI/tests/test_workflow_registry.py` | MODIFY |
| 19 | `SAIKI/docs/BUILD_A_REPORT.md` | CREATE |

**Total**: 19 files (6 create, 12 modify, 1 delete)

---

## 9. Success Criteria

- [ ] No AT/USSD command strings hardcoded in any skill
- [ ] All skills read from `CommandRegistry`
- [ ] All parsers from `ParserRegistry`
- [ ] CekNikSkill uses `*888*4444*1#` (not `*185#`)
- [ ] CekKkSkill uses cache type (not USSD)
- [ ] InjectReaktivasiSkill uses template with `{NIK}` and `{KK}`
- [ ] VerifyGraceSkill uses `verify_grace_response` parser
- [ ] ResetHardwareSkill deleted
- [ ] `hardware_reset` workflow removed
- [ ] `cmd.reset_modem` route removed
- [ ] All existing tests pass
- [ ] New registry + parser tests pass
- [ ] `BUILD_A_REPORT.md` delivered

---

## 10. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Breaking existing workflows | HIGH | Phase 1 creates registries without changing skills; Phase 2 refactors one skill at a time with test verification |
| Parser compatibility | MEDIUM | All GOOD parsers are pure functions — easy to port |
| Template injection for inject_reaktivasi | MEDIUM | NIK/KK come from workflow context — ensure context passes through |
| Test failures after refactor | HIGH | Run tests after each skill refactor, not batch |
