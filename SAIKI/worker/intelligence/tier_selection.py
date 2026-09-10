"""TierSelection — Select best USSD command based on operator, history, fallback.

Adopted from GOOD: 9-tier USSD classification.
Selects the optimal command tier based on:
- Operator type (IM3, Telkomsel, etc.)
- Success history per tier
- Automatic fallback on failure

Tier priority: Primary → Secondary → Tertiary → Fallback
"""

import logging
import threading
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger("saiki.intelligence.tier_selection")


@dataclass
class TierCommand:
    """A single USSD command tier."""
    name: str
    ussd_code: str
    description: str = ""
    priority: int = 0  # Lower = higher priority
    success_count: int = 0
    failure_count: int = 0

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        return self.success_count / total if total > 0 else 0.0

    def record_success(self) -> None:
        self.success_count += 1

    def record_failure(self) -> None:
        self.failure_count += 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "ussd_code": self.ussd_code,
            "priority": self.priority,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "success_rate": self.success_rate,
        }


@dataclass
class TierProfile:
    """A set of USSD command tiers for an intent."""
    intent: str
    tiers: List[TierCommand] = field(default_factory=list)

    def select_best(self) -> Optional[TierCommand]:
        """Select the best tier based on priority and success rate.

        Higher success rate + lower priority number = better.
        """
        if not self.tiers:
            return None

        # Sort: priority first, then success rate (descending)
        sorted_tiers = sorted(
            self.tiers,
            key=lambda t: (t.priority, -t.success_rate),
        )

        # Prefer tiers with >0 success rate if available
        for tier in sorted_tiers:
            if tier.success_count > 0:
                return tier

        # Fall back to highest priority
        return sorted_tiers[0] if sorted_tiers else None

    def select_next_fallback(self, failed_tier_name: str) -> Optional[TierCommand]:
        """Select the next tier after a failure."""
        remaining = [t for t in self.tiers if t.name != failed_tier_name]
        if not remaining:
            return None
        return sorted(remaining, key=lambda t: t.priority)[0]


class TierSelection:
    """USSD Tier Selection engine.

    Maintains per-intent tier lists and selects the best command
    based on operator, history, and fallback rules.
    """

    def __init__(self) -> None:
        self._profiles: Dict[str, TierProfile] = {}
        self._lock = threading.Lock()
        self._register_defaults()

    def _register_defaults(self) -> None:
        """Register default tier profiles for each intent."""
        # CEK NOMOR: AT+CNUM → USSD fallback
        self.register(TierProfile(
            intent="cek_nomor",
            tiers=[
                TierCommand(name="at_cnum", ussd_code="AT+CNUM", priority=0, description="AT+CNUM primary"),
                TierCommand(name="ussd_185", ussd_code="*185#", priority=1, description="USSD *185# fallback"),
            ],
        ))

        # CEK STATUS: AT+CPIN? → USSD fallback
        self.register(TierProfile(
            intent="cek_status",
            tiers=[
                TierCommand(name="at_cpin", ussd_code="AT+CPIN?", priority=0, description="AT+CPIN? primary"),
                TierCommand(name="ussd_185", ussd_code="*185#", priority=1, description="USSD *185# fallback"),
            ],
        ))

        # CEK NIK: *888*4444*1# (single tier)
        self.register(TierProfile(
            intent="cek_nik",
            tiers=[
                TierCommand(name="nik_primary", ussd_code="*888*4444*1#", priority=0, description="NIK primary USSD"),
            ],
        ))

        # CEK KK: Cache/DB/Telegram (no USSD)
        self.register(TierProfile(
            intent="cek_kk",
            tiers=[
                TierCommand(name="cache", ussd_code="", priority=0, description="Phone cache lookup"),
                TierCommand(name="db", ussd_code="", priority=1, description="Local DB lookup"),
                TierCommand(name="telegram", ussd_code="", priority=2, description="Telegram gateway"),
            ],
        ))

        # INJECT REAKTIVASI: *888*89*1*{NIK}*{KK}# (single tier)
        self.register(TierProfile(
            intent="inject_reaktivasi",
            tiers=[
                TierCommand(name="inject_primary", ussd_code="*888*89*1*{NIK}*{KK}#", priority=0, description="Reaktivasi primary"),
            ],
        ))

        # VERIFY GRACE: *185# (single tier)
        self.register(TierProfile(
            intent="verify_grace",
            tiers=[
                TierCommand(name="grace_primary", ussd_code="*185#", priority=0, description="Grace verification primary"),
            ],
        ))

    def register(self, profile: TierProfile) -> None:
        """Register a tier profile for an intent."""
        with self._lock:
            self._profiles[profile.intent] = profile

    def select(self, intent: str) -> Optional[TierCommand]:
        """Select the best tier for an intent."""
        with self._lock:
            profile = self._profiles.get(intent)
            if not profile:
                logger.warning("[TIER_SELECT] NO_PROFILE intent=%s", intent)
                return None
            best = profile.select_best()
            if best:
                logger.info("[TIER_SELECT] SELECT intent=%s tier=%s ussd=%s rate=%.2f",
                            intent, best.name, best.ussd_code, best.success_rate)
            return best

    def select_fallback(self, intent: str, failed_tier: str) -> Optional[TierCommand]:
        """Select next tier after a failure."""
        with self._lock:
            profile = self._profiles.get(intent)
            if not profile:
                return None
            fallback = profile.select_next_fallback(failed_tier)
            if fallback:
                logger.info("[TIER_SELECT] FALLBACK intent=%s from=%s to=%s",
                            intent, failed_tier, fallback.name)
            return fallback

    def record_success(self, intent: str, tier_name: str) -> None:
        """Record a successful USSD call for a tier."""
        with self._lock:
            profile = self._profiles.get(intent)
            if profile:
                for tier in profile.tiers:
                    if tier.name == tier_name:
                        tier.record_success()
                        logger.info("[TIER_SELECT] SUCCESS intent=%s tier=%s rate=%.2f",
                                    intent, tier_name, tier.success_rate)
                        break

    def record_failure(self, intent: str, tier_name: str) -> None:
        """Record a failed USSD call for a tier."""
        with self._lock:
            profile = self._profiles.get(intent)
            if profile:
                for tier in profile.tiers:
                    if tier.name == tier_name:
                        tier.record_failure()
                        logger.info("[TIER_SELECT] FAILURE intent=%s tier=%s rate=%.2f",
                                    intent, tier_name, tier.success_rate)
                        break

    def snapshot(self) -> Dict[str, Any]:
        """Return all tier profiles for debugging."""
        with self._lock:
            return {
                intent: {
                    "tiers": [t.to_dict() for t in profile.tiers],
                    "best": profile.select_best().name if profile.select_best() else None,
                }
                for intent, profile in self._profiles.items()
            }
