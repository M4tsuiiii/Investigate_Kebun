# COMMAND REGISTRY DESIGN

Arsitektur Command Registry untuk SAIKI — single source of truth untuk semua modem commands.

---

## 1. Why Command Registry?

### Current Problem

- Each skill has hardcoded USSD code + parser
- No central place to see all commands
- Duplicated parsers in multiple files
- No validation that commands are correct
- Hard to change USSD codes (must edit each skill)

### Solution

Command Registry: single dict mapping feature name → command definition.

---

## 2. Registry Structure

```python
from dataclasses import dataclass, field
from typing import Callable, Optional

@dataclass(frozen=True)
class CommandDefinition:
    """Single source of truth for a modem command."""
    
    name: str                           # Feature name (e.g., "cek_nomor")
    description: str                    # Human-readable description
    
    # Command specification
    at_command: Optional[str] = None    # AT command (e.g., "AT+CNUM")
    ussd_code: Optional[str] = None     # USSD code (e.g., "*185#")
    ussd_template: Optional[str] = None # Template with placeholders (e.g., "*888*89*1*{NIK}*{KK}#")
    
    # Parser specification
    parser_name: Optional[str] = None   # Parser function name
    parser_module: Optional[str] = None # Module containing parser
    
    # Output specification
    output_fields: tuple[str, ...] = () # Fields returned by skill
    success_rule: str = ""              # How to determine success
    
    # Workflow integration
    workflow: str = ""                  # Target workflow name
    scope: str = "per_port"             # "per_port" | "mass" | "global"
    eligibility: str = "sim_ready"      # "sim_ready" | "hw_ready" | "worker_alive" | "none"
    
    # UI integration
    ui_label: str = ""                  # Button label
    ui_column: Optional[str] = None     # Target UI column
    
    # Metadata
    source: str = ""                    # "GOOD" | "SAIKI" | "NEW"
    priority: str = "P0"               # "P0" | "P1" | "P2"
```

---

## 3. Registry Entries

```python
COMMAND_REGISTRY: dict[str, CommandDefinition] = {
    "cek_nomor": CommandDefinition(
        name="cek_nomor",
        description="Cek nomor dan grace date via AT+CNUM atau *185#. Status kartu DIHITUNG dari grace_date - today.",
        at_command="AT+CNUM",
        ussd_code="*185#",
        parser_name="_parse_cnum + _parse_ussd_number + _extract_grace_date + _classify_card_status",
        output_fields=("number", "grace_date", "card_status", "modem_responsive"),
        success_rule="number is not None and number != '-'",
        workflow="check_number",
        scope="per_port",
        eligibility="sim_ready",
        ui_label="Cek Nomor",
        ui_column="NOMOR",
        source="SAIKI",
        priority="P0",
    ),
    
    "cek_status": CommandDefinition(
        name="cek_status",
        description="Cek status SIM card via AT+CPIN?",
        at_command="AT+CPIN?",
        parser_name="parse_cpin_response",
        output_fields=("cpin_state", "sim_ready"),
        success_rule="cpin_state == CpinState.READY",
        workflow="check_status",
        scope="per_port",
        eligibility="sim_ready",
        ui_label="Cek Status SIM",
        ui_column="STATUS",
        source="SAIKI",
        priority="P0",
    ),
    
    "cek_nik": CommandDefinition(
        name="cek_nik",
        description="Cek NIK via USSD *888*4444*1#",
        ussd_code="*888*4444*1#",
        parser_name="_extract_nik",
        output_fields=("nik",),
        success_rule="nik is not None and len(nik) == 16",
        workflow="check_nik",
        scope="per_port",
        eligibility="sim_ready",
        ui_label="Cek NIK",
        ui_column="NIK",
        source="GOOD",
        priority="P0",
    ),
    
    "cek_kk": CommandDefinition(
        name="cek_kk",
        description="Cek KK via cache/DB/Telegram",
        parser_name="_extract_kk",
        output_fields=("kk", "source"),
        success_rule="kk is not None and len(kk) == 16",
        workflow="check_kk",
        scope="per_port",
        eligibility="sim_ready",
        ui_label="Cari KK",
        ui_column="KK",
        source="NEW",
        priority="P0",
    ),
    
    "inject_reaktivasi": CommandDefinition(
        name="inject_reaktivasi",
        description="Reaktivasi injection via USSD *888*89*1*{NIK}*{KK}#",
        ussd_template="*888*89*1*{NIK}*{KK}#",
        parser_name="classify_injection_response + _evaluate_provisional",
        output_fields=("injected", "provisional", "card_status"),
        success_rule="injected == True or provisional == 'PROVISIONAL_SUCCESS'",
        workflow="reactivate_full",
        scope="per_port",
        eligibility="sim_ready",
        ui_label="Reaktivasi",
        ui_column="RESPON",
        source="GOOD",
        priority="P0",
    ),
    
    "verify_grace": CommandDefinition(
        name="verify_grace",
        description="Verifikasi grace date via USSD *185#",
        ussd_code="*185#",
        parser_name="_extract_grace_date + _classify_card_status + has_grace_date_changed + evaluate_business_outcome",
        output_fields=("grace_date_after", "card_status", "success", "outcome"),
        success_rule="success == True",
        workflow="reactivate_full",
        scope="per_port",
        eligibility="sim_ready",
        ui_label="Verifikasi",
        ui_column="MASA AKTIF",
        source="GOOD",
        priority="P0",
    ),
    
    "cek_limit": CommandDefinition(
        name="cek_limit",
        description="Cek pulsa/quota via USSD (configurable)",
        ussd_code="configurable",
        parser_name="_extract_pulsa",
        output_fields=("pulsa",),
        success_rule="pulsa is not None",
        workflow="check_limit",
        scope="per_port",
        eligibility="sim_ready",
        ui_label="Cek Limit",
        ui_column="RESPON",
        source="NEW",
        priority="P1",
    ),
    
    "restart_hardware": CommandDefinition(
        name="restart_hardware",
        description="Restart modem via ATZ — scanning ulang seperti startup awal, tanpa auto run. Tunggal (1 port) atau massal (semua port).",
        at_command="ATZ",
        parser_name="check_modem",
        output_fields=("restart_sent", "modem_online"),
        success_rule="modem_online == True",
        workflow="hardware_restart",
        scope="per_port | mass",
        eligibility="hw_ready",
        ui_label="Restart Port / Restart All",
        ui_column="RESPON",
        source="SAIKI",
        priority="P0",
    ),
}
```

**Note**: `reset_hardware` DIHAPUS. Hanya `restart_hardware` yang dipakai.
```

---

## 4. Registry API

```python
def get_command(name: str) -> CommandDefinition:
    """Get command definition by name."""
    if name not in COMMAND_REGISTRY:
        raise KeyError(f"Unknown command: {name}")
    return COMMAND_REGISTRY[name]


def get_ussd_code(name: str) -> str | None:
    """Get USSD code for a command."""
    cmd = get_command(name)
    return cmd.ussd_code


def get_at_command(name: str) -> str | None:
    """Get AT command for a command."""
    cmd = get_command(name)
    return cmd.at_command


def get_parser(name: str) -> str | None:
    """Get parser function name for a command."""
    cmd = get_command(name)
    return cmd.parser_name


def get_output_fields(name: str) -> tuple[str, ...]:
    """Get output fields for a command."""
    cmd = get_command(name)
    return cmd.output_fields


def get_all_commands() -> dict[str, CommandDefinition]:
    """Get all registered commands."""
    return COMMAND_REGISTRY.copy()


def get_commands_by_workflow(workflow: str) -> list[CommandDefinition]:
    """Get all commands for a specific workflow."""
    return [cmd for cmd in COMMAND_REGISTRY.values() if cmd.workflow == workflow]


def get_commands_by_scope(scope: str) -> list[CommandDefinition]:
    """Get all commands with a specific scope."""
    return [cmd for cmd in COMMAND_REGISTRY.values() if cmd.scope == scope]
```

---

## 5. Integration Points

### 5.1 Skill Integration

Skills read command definition from registry:

```python
class CekNikSkill(Skill):
    def execute(self, port: str, **kwargs) -> SkillResult:
        cmd = get_command("cek_nik")
        ussd_code = cmd.ussd_code  # "*888*4444*1#"
        
        resolver = kwargs.get("skill_resolver")
        ussd = resolver.get_ussd_runtime()
        raw = ussd.dial(ussd_code, timeout=30.0)
        
        # Use parser from registry
        nik = _extract_nik(raw)
        
        return self._success(port, {"nik": nik})
```

### 5.2 Controller Integration

Controller reads command definitions for routing:

```python
class UIController:
    def _log_router_ready(self):
        for name, cmd in get_all_commands().items():
            log.info(f"[COMMAND ROUTER READY] {name} → {cmd.workflow}")
```

### 5.3 Factory Integration

Factories create skills based on registry:

```python
class _CekNikSkillFactory(_SkillFactoryBase):
    def create(self, **deps):
        cmd = get_command("cek_nik")
        return CekNikSkill()
```

### 5.4 Eligibility Integration

Controller checks eligibility from registry:

```python
def _check_port_eligibility(self, port_id: str, workflow: str) -> str | None:
    for cmd in get_commands_by_workflow(workflow):
        if cmd.eligibility == "sim_ready":
            # check SIM state
            pass
        elif cmd.eligibility == "hw_ready":
            # check modem online
            pass
    return None
```

---

## 6. Benefits

| Benefit | Description |
|---------|-------------|
| **Single Source of Truth** | All commands in one place |
| **Easy to Change** | Change USSD code in registry, all skills update |
| **Self-Documenting** | Registry is documentation |
| **Validation** | Can validate all commands at startup |
| **Testability** | Can test registry independently |
| **Maintainability** | New commands = new registry entry |

---

## 7. Migration Path

### Phase 1: Create Registry (no integration)
- Create `SAIKI/worker/commands/registry.py`
- Define all 9 command entries
- Write tests for registry API

### Phase 2: Integrate with Skills (one at a time)
- Update each skill to read from registry
- Keep hardcoded values as fallback
- Run tests after each skill

### Phase 3: Integrate with Controller
- Update COMMAND_ROUTES to use registry
- Update eligibility checks
- Run full test suite

### Phase 4: Remove Hardcoded Values
- Remove all hardcoded USSD codes from skills
- Remove duplicate parsers
- Run full test suite

---

## 8. Testing Strategy

### Unit Tests

```python
def test_registry_has_all_commands():
    assert len(COMMAND_REGISTRY) == 8  # was 9, reset_hardware removed

def test_cek_nik_uses_correct_ussd():
    cmd = get_command("cek_nik")
    assert cmd.ussd_code == "*888*4444*1#"

def test_cek_nomor_has_grace_date_field():
    cmd = get_command("cek_nomor")
    assert "grace_date" in cmd.output_fields

def test_inject_has_provisional_field():
    cmd = get_command("inject_reaktivasi")
    assert "provisional" in cmd.output_fields

def test_all_commands_have_parser():
    for name, cmd in get_all_commands().items():
        assert cmd.parser_name is not None, f"{name} missing parser"
```

### Integration Tests

```python
def test_skill_uses_registry_ussd():
    skill = CekNikSkill()
    result = skill.execute("COM3", skill_resolver=mock_resolver)
    # Verify *888*4444*1# was sent (not *185#)
```
