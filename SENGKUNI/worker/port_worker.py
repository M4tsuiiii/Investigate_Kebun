"""PortWorker — Simplified per-port runtime.

One thread per COM port. Handles:
- Serial connection
- AT command execution
- CPIN polling
- Auto-run on SIM READY (with false-positive prevention)
- Health watchdog for stuck processes
"""

import logging
import threading
import time
from typing import Any, Dict, Optional

from app.domain.enums import CpinState, PortStatus
from app.domain.constants import (
    CPIN_POLL_INTERVAL, CPIN_POLL_TIMEOUT, DIAL_COOLDOWN_SECONDS,
    STABILIZATION_SECONDS, MODEM_BAUD_RATES
)
from app.domain.classifier import parse_cpin_response
from app.domain.state_machine.hw_sm import HwStateMachine, HwState
from app.infrastructure.serial.serial_adapter import SerialAdapter
from app.infrastructure.serial.at_client import ATClient
from app.infrastructure.events import EventBus
from worker.state import PortWorkerState
from worker.rules import AutoRunConfig, should_block_auto_run
from worker.cpin_runtime import CpinRuntime
from worker.ussd_runtime import UssdRuntime
from worker.command_registry import CommandRegistry
from worker.parser_registry import ParserRegistry
from worker.intelligence.phone_cache import PhoneCache
from worker.intelligence.session_fence import SessionFence

logger = logging.getLogger("sengkuni.port_worker")

# Health watchdog constants
_HEALTH_CHECK_INTERVAL = 30.0  # Check worker health every 30 seconds
_STALE_THRESHOLD = 60.0  # Worker considered stuck if no activity for 60 seconds


class PortWorker:
    """Simplified per-port runtime.

    Lifecycle:
    1. start() → open serial, detect baud, start CPIN poll
    2. _run_loop() → process auto-run requests, health watchdog
    3. stop() → stop worker thread, stop CPIN poll, close serial (correct order)

    Auto-run trigger (anti-false-positive):
    - CPIN READY detected (confirmed by 2x consecutive polls in CpinRuntime)
    - AND timestamp check: last_cpin_poll < 5 seconds ago
    - AND should_block_auto_run() returns False
    - _run_loop() consumes pending_auto_run → execute workflow

    Health watchdog:
    - Monitors _last_activity_time every 30 seconds
    - If stale > 60 seconds → force restart worker thread
    """

    def __init__(
        self,
        port_id: str,
        event_bus: EventBus,
        auto_run_config: AutoRunConfig,
        command_registry: CommandRegistry,
        parser_registry: ParserRegistry,
        phone_cache: PhoneCache,
        session_fence: SessionFence,
        preferred_baud: Optional[int] = None,
    ) -> None:
        self.port_id = port_id
        self._event_bus = event_bus
        self._auto_run_config = auto_run_config
        self._cmd_reg = command_registry
        self._parser_reg = parser_registry
        self._phone_cache = phone_cache
        self._session_fence = session_fence
        self._preferred_baud = preferred_baud

        # Hardware components
        self._serial: Optional[SerialAdapter] = None
        self._at_client: Optional[ATClient] = None
        self._cpin_runtime: Optional[CpinRuntime] = None
        self._ussd_runtime: Optional[UssdRuntime] = None

        # State
        self._state = PortWorkerState(port_id)
        self._hw_state = HwStateMachine(port_id)
        self._running = threading.Event()
        self._pending_auto_run = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # Health watchdog
        self._last_activity_time: float = time.time()
        self._last_health_check: float = time.time()
        self._restart_count: int = 0

    def start(self) -> None:
        """Open serial, detect baud, start CPIN poll."""
        if self._running.is_set():
            return

        # Create serial adapter
        self._serial = SerialAdapter(self.port_id)

        # Detect baud rate — try preferred first, then full scan
        if self._preferred_baud:
            baud = self._try_baud(self._preferred_baud)
            if baud is None:
                baud = self._detect_baud()
        else:
            baud = self._detect_baud()

        if baud is None:
            logger.warning("[PORT_WORKER] %s: No modem detected", self.port_id)
            self._publish_event("modem.offline")
            return

        # Open serial
        self._serial.set_baud_rate(baud)
        if not self._serial.open():
            logger.warning("[PORT_WORKER] %s: Failed to open serial", self.port_id)
            self._publish_event("modem.offline")
            return

        # Create AT client
        self._at_client = ATClient(self._serial)

        # Disable echo
        self._at_client.send_command("ATE0", timeout=2.0)

        # Create USSD runtime
        self._ussd_runtime = UssdRuntime(
            at_client=self._at_client,
            session_fence=self._session_fence,
            port_id=self.port_id,
        )

        # Create and start CPIN runtime
        self._cpin_runtime = CpinRuntime(
            at_client=self._at_client,
            on_cpin_transition=self._on_cpin_transition,
            port_id=self.port_id,
        )
        self._cpin_runtime.start()

        # Mark modem online
        self._state.modem_online = True
        self._hw_state.transition(HwState.MODEM_DETECTED)
        self._publish_event("modem.online")

        # Start worker thread
        self._running.set()
        self._last_activity_time = time.time()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

        logger.info("[PORT_WORKER] %s: Started (baud=%d)", self.port_id, baud)

    def stop(self) -> None:
        """Stop worker thread FIRST, then CPIN, then serial (correct order).

        Previous order stopped CPIN before worker thread, which could cause
        the worker to access already-closed serial/ATClient.
        """
        logger.info("[PORT_WORKER] %s: Stopping...", self.port_id)

        # Step 1: Stop worker thread first (it uses serial via skills)
        self._running.clear()
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None

        # Step 2: Stop CPIN runtime (it uses ATClient which uses serial)
        if self._cpin_runtime:
            self._cpin_runtime.stop()
            self._cpin_runtime = None

        # Step 3: Close serial port last
        if self._serial:
            self._serial.close()
            self._serial = None

        # Step 4: Null out references
        self._at_client = None
        self._ussd_runtime = None
        self._state.modem_online = False
        self._hw_state.force_offline()
        self._publish_event("modem.offline")

        logger.info("[PORT_WORKER] %s: Stopped", self.port_id)

    def restart(self) -> None:
        """Restart the worker."""
        self.stop()
        time.sleep(1.0)
        self.start()

    def restart_hardware(self) -> None:
        """Restart hardware (alias for restart)."""
        self.restart()

    @property
    def is_alive(self) -> bool:
        """Check if worker thread is running."""
        return self._running.is_set() and self._thread is not None and self._thread.is_alive()

    @property
    def cpin_ready(self) -> bool:
        """Check if SIM is READY."""
        return self._state.cpin_state == CpinState.READY

    @property
    def cpin_state(self) -> CpinState:
        """Get current CPIN state."""
        return self._state.cpin_state

    def run_skills(self, skills: list) -> None:
        """Execute a list of skills asynchronously."""
        def _run():
            try:
                self._execute_workflow(skills)
            except Exception as e:
                logger.error("[PORT_WORKER] %s: run_skills failed: %s", self.port_id, e)
        threading.Thread(target=_run, daemon=True).start()

    def force_retry(self) -> None:
        """Force retry auto-run."""
        with self._lock:
            self._pending_auto_run = True

    def queue_auto_run(self) -> None:
        """Queue auto-run."""
        with self._lock:
            self._pending_auto_run = True

    def _try_baud(self, baud: int) -> Optional[int]:
        """Try a single baud rate. Returns baud if modem responds, else None."""
        self._serial.set_baud_rate(baud)
        if self._serial.open():
            resp = self._serial.send_at("AT", timeout=1.0)
            self._serial.close()
            if resp and "OK" in resp:
                return baud
            time.sleep(0.1)
        return None

    def _detect_baud(self) -> Optional[int]:
        """Detect modem baud rate by trying all known rates."""
        for baud in MODEM_BAUD_RATES:
            result = self._try_baud(baud)
            if result:
                return result
        return None

    def _run_loop(self) -> None:
        """Main worker loop with health watchdog."""
        while self._running.is_set():
            try:
                now = time.time()

                # Health watchdog — check if worker is stuck
                if now - self._last_health_check >= _HEALTH_CHECK_INTERVAL:
                    self._last_health_check = now
                    stale_seconds = now - self._last_activity_time
                    if stale_seconds > _STALE_THRESHOLD:
                        logger.warning(
                            "[PORT_WORKER] %s: Worker stale for %.0fs (threshold %.0fs), considering restart",
                            self.port_id, stale_seconds, _STALE_THRESHOLD,
                        )
                        # Don't auto-restart — just log. UI can trigger manual restart.
                        self._event_bus.publish("port.worker.stale", {
                            "port": self.port_id,
                            "stale_seconds": stale_seconds,
                        })

                    # Publish health status for UI monitoring
                    self._event_bus.publish("port.worker.health", {
                        "port": self.port_id,
                        "cpin_state": self._state.cpin_state.value if self._state.cpin_state else "UNKNOWN",
                        "uptime": now - self._last_activity_time,
                        "modem_online": self._state.modem_online,
                        "restart_count": self._restart_count,
                    })

                # Process auto-run
                with self._lock:
                    pending = self._pending_auto_run
                    self._pending_auto_run = False

                if pending and self._state.modem_online:
                    self._execute_auto_run()

                # Update activity timestamp
                self._last_activity_time = now

                time.sleep(0.1)
            except Exception as e:
                logger.error("[PORT_WORKER] %s: Error in run loop: %s", self.port_id, e)
                time.sleep(1.0)

    def _on_cpin_transition(self, old_state: CpinState, new_state: CpinState) -> None:
        """Handle CPIN state change.

        Anti-false-positive gate for auto-run:
        1. new_state must be READY
        2. auto_run must be enabled
        3. last CPIN poll must be < 5 seconds ago (fresh data, not stale)
        4. should_block_auto_run() must return False
        """
        self._state.cpin_state = new_state
        self._last_activity_time = time.time()

        # Publish event for UI
        self._event_bus.publish("cpin.transition", {
            "port": self.port_id,
            "old": old_state.value if old_state else "NONE",
            "new": new_state.value,
        })

        # Trigger auto-run on READY — with freshness gate
        if new_state == CpinState.READY:
            if self._auto_run_config.enabled:
                # Freshness gate: ensure CPIN poll is recent
                if self._cpin_runtime:
                    poll_age = time.time() - self._cpin_runtime.last_poll_time
                    if poll_age > 5.0:
                        logger.warning(
                            "[PORT_WORKER] %s: SKIP auto-run — CPIN poll stale (%.1fs ago)",
                            self.port_id, poll_age,
                        )
                        return

                # Block check
                if should_block_auto_run(self._state):
                    logger.info("[PORT_WORKER] %s: Auto-run blocked by rules", self.port_id)
                    return

                with self._lock:
                    self._pending_auto_run = True
                    logger.info("[PORT_WORKER] %s: Auto-run queued (CPIN READY, poll fresh)", self.port_id)

    def _execute_auto_run(self) -> None:
        """Execute workflow based on current mode."""
        logger.info("[PORT_WORKER] %s: Executing auto-run", self.port_id)
        self._last_activity_time = time.time()

        try:
            # Execute check_data workflow (cek_nomor → cek_nik → cek_kk)
            self._execute_workflow(["cek_nomor", "cek_nik", "cek_kk"])
        except Exception as e:
            logger.error("[PORT_WORKER] %s: Auto-run failed: %s", self.port_id, e)

    def _execute_workflow(self, steps: list) -> None:
        """Execute a workflow with given steps."""
        # Create skill resolver
        resolver = SkillDependencyResolver(self.port_id, self)

        context = {}
        for step_name in steps:
            # Check if worker is still running before each step
            if not self._running.is_set():
                logger.info("[PORT_WORKER] %s: Worker stopped, aborting workflow", self.port_id)
                break

            # Resolve skill
            skill = self._resolve_skill(step_name, resolver)
            if not skill:
                logger.warning("[PORT_WORKER] %s: Unknown skill: %s", self.port_id, step_name)
                continue

            # Execute skill
            result = skill.execute(self.port_id, skill_resolver=resolver, **context)

            # Update activity timestamp
            self._last_activity_time = time.time()

            # Store result in context
            context.update(result.data)

            # Publish result — flatten data into top-level payload
            publish_payload = {
                "port": self.port_id,
                "skill": step_name,
                "success": result.success,
            }
            publish_payload.update(result.data)
            self._event_bus.publish("port.data.updated", publish_payload)

            if not result.success:
                logger.info("[PORT_WORKER] %s: Step %s failed: %s", self.port_id, step_name, result.error)
                break

            # Cooldown between steps
            time.sleep(1.0)

    def _resolve_skill(self, name: str, resolver: 'SkillDependencyResolver') -> Optional[Any]:
        """Resolve a skill by name."""
        from worker.skills.cek_nomor import CekNomorSkill
        from worker.skills.cek_nik import CekNikSkill
        from worker.skills.cek_kk import CekKkSkill
        from worker.skills.inject_reaktivasi import InjectReaktivasiSkill
        from worker.skills.verify_grace import VerifyGraceSkill
        from worker.skills.restart_hardware import RestartHardwareSkill
        from worker.skills.reset_hardware import ResetHardwareSkill

        skills = {
            "cek_nomor": lambda: CekNomorSkill(
                at_client=self._at_client,
                ussd_runtime=self._ussd_runtime,
                command_registry=self._cmd_reg,
                parser_registry=self._parser_reg,
                phone_cache=self._phone_cache,
            ),
            "cek_nik": lambda: CekNikSkill(
                ussd_runtime=self._ussd_runtime,
                command_registry=self._cmd_reg,
                parser_registry=self._parser_reg,
                phone_cache=self._phone_cache,
            ),
            "cek_kk": lambda: CekKkSkill(
                command_registry=self._cmd_reg,
                parser_registry=self._parser_reg,
                phone_cache=self._phone_cache,
            ),
            "inject_reaktivasi": lambda: InjectReaktivasiSkill(
                ussd_runtime=self._ussd_runtime,
                command_registry=self._cmd_reg,
                parser_registry=self._parser_reg,
            ),
            "verify_grace": lambda: VerifyGraceSkill(
                ussd_runtime=self._ussd_runtime,
                command_registry=self._cmd_reg,
                parser_registry=self._parser_reg,
            ),
            "restart_hardware": lambda: RestartHardwareSkill(
                at_client=self._at_client,
                command_registry=self._cmd_reg,
                parser_registry=self._parser_reg,
            ),
            "reset_hardware": lambda: ResetHardwareSkill(
                serial_adapter=self._serial,
                at_client=self._at_client,
                cpin_runtime=self._cpin_runtime,
            ),
        }

        factory = skills.get(name)
        if factory:
            return factory()
        return None

    def _publish_event(self, event_name: str) -> None:
        """Publish an event with port info."""
        self._event_bus.publish(event_name, {"port": self.port_id})

    def _publish_status(self, status: str, detail: str = "") -> None:
        """Publish status update for UI."""
        self._event_bus.publish_ui_update(self.port_id, "status", status)
        if detail:
            self._event_bus.publish_ui_update(self.port_id, "respon", detail)


class SkillDependencyResolver:
    """Resolves per-port hardware dependencies."""

    def __init__(self, port_id: str, worker: PortWorker) -> None:
        self._port = port_id
        self._worker = worker

    @property
    def port(self) -> str:
        return self._port

    def get_at_client(self) -> Optional[ATClient]:
        return self._worker._at_client

    def get_ussd_runtime(self) -> Optional[UssdRuntime]:
        return self._worker._ussd_runtime

    def get_serial(self) -> Optional[SerialAdapter]:
        return self._worker._serial

    def get_cpin_runtime(self) -> Optional[CpinRuntime]:
        return self._worker._cpin_runtime
