"""CommandRegistry — Central store for all modem commands.

Skills read commands from this registry. No hardcoded strings in skills.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class CommandProfile:
    """Definition of a single modem command.

    Attributes:
        name: Unique command name (matches skill name)
        command_type: "at" | "ussd" | "composite" | "hardware" | "cache"
        at_command: AT command string (for type "at")
        ussd_code: USSD code string (for type "ussd")
        ussd_template: USSD template with {NIK}, {KK} placeholders (for type "composite")
        parser_name: Name of parser function in ParserRegistry
        output_fields: Fields this command produces
        timeout: Default timeout in seconds
        description: Human-readable description
    """

    name: str
    command_type: str  # "at" | "ussd" | "composite" | "hardware" | "cache"
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
                ussd_code="",
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
                command_type="cache",
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

    def get_ussd_code(self, name: str, **kwargs: str) -> str:
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
