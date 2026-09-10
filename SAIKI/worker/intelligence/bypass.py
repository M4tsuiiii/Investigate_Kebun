"""BypassFlags — Workflow policy flags for skipping unnecessary steps.

Adopted from GOOD: abai_aktif, abai_tenggang, status_update_only, format_mode.

Controls whether to skip injection/verification based on card status.
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("saiki.intelligence.bypass")


class BypassFlags:
    """Workflow bypass policy flags.

    Flags control whether to skip certain workflow steps:
    - abai_aktif: Skip injection for ACTIVE cards
    - abai_tenggang: Skip injection for TENGGANG cards
    - status_update_only: Only check status, no injection
    - format_mode: "NIK & KK" or "NIK & NIK" (skip KK lookup)
    """

    def __init__(
        self,
        abai_aktif: bool = False,
        abai_tenggang: bool = False,
        status_update_only: bool = False,
        format_mode: str = "NIK & KK",
    ) -> None:
        self.abai_aktif = abai_aktif
        self.abai_tenggang = abai_tenggang
        self.status_update_only = status_update_only
        self.format_mode = format_mode

    def should_skip_injection(self, card_status: str) -> Optional[str]:
        """Check if injection should be skipped based on card status.

        Returns reason string if should skip, None if should proceed.
        """
        card_status = str(card_status or "").upper().strip()

        if self.status_update_only:
            return "status_update_only"

        if card_status == "AKTIF" and self.abai_aktif:
            return "abai_aktif"

        if card_status == "TENGGANG" and self.abai_tenggang:
            return "abai_tenggang"

        return None

    def should_skip_kk_lookup(self) -> bool:
        """Check if KK lookup should be skipped (NIK & NIK mode)."""
        return self.format_mode.upper().strip() == "NIK & NIK"

    def evaluate(self, card_status: str) -> Dict[str, Any]:
        """Full evaluation of bypass flags for a card.

        Returns dict with decisions.
        """
        skip_reason = self.should_skip_injection(card_status)
        skip_kk = self.should_skip_kk_lookup()

        result = {
            "skip_injection": skip_reason is not None,
            "skip_reason": skip_reason,
            "skip_kk_lookup": skip_kk,
            "card_status": card_status,
            "flags": {
                "abai_aktif": self.abai_aktif,
                "abai_tenggang": self.abai_tenggang,
                "status_update_only": self.status_update_only,
                "format_mode": self.format_mode,
            },
        }

        if skip_reason:
            logger.info("[BYPASS] SKIP_INJECTION status=%s reason=%s", card_status, skip_reason)
        if skip_kk:
            logger.info("[BYPASS] SKIP_KK_LOOKUP format_mode=%s", self.format_mode)

        return result

    def to_dict(self) -> Dict[str, Any]:
        """Serialize flags for persistence."""
        return {
            "abai_aktif": self.abai_aktif,
            "abai_tenggang": self.abai_tenggang,
            "status_update_only": self.status_update_only,
            "format_mode": self.format_mode,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BypassFlags":
        """Deserialize flags from dict."""
        return cls(
            abai_aktif=data.get("abai_aktif", False),
            abai_tenggang=data.get("abai_tenggang", False),
            status_update_only=data.get("status_update_only", False),
            format_mode=data.get("format_mode", "NIK & KK"),
        )
