"""PortWorker — per-port runtime engine (Sprint 5, 15B).

One thread per COM port. Owns serial connection, AT client, CPIN monitor,
USSD runtime, cleanup manager, and hardware state machine.

Architecture: ARCHITECTURE.md §4.2, DESIGN_DECISIONS DD-013 through DD-019.
"""

import logging
import threading
import time
from typing import Optional, Any

from app.domain.enums import CpinState, PortStatus
from app.domain.constants import (
    STABILIZATION_SECONDS,
    DIAL_COOLDOWN_SECONDS,
    CPIN_POLL_INTERVAL,
    CPIN_POLL_TIMEOUT,
)
from app.domain.classifier import parse_cpin_response
from app.domain.state_machine.hw_sm import HwStateMachine, HwState
from worker.state import PortWorkerState
from worker.cpin_runtime import CpinRuntime
from worker.ussd_runtime import UssdRuntime
from worker.cleanup import CleanupManager
from worker.rules import AutoRunConfig, should_block_auto_run

logger = logging.getLogger("saiki.worker")


class PortWorker:
    """Per-port runtime engine.
    
    Responsibilities:
    - Own serial connection (SerialAdapter)
    - Own AT client (ATClient)
    - Own CPIN monitor (CpinRuntime)
    - Own USSD runtime (UssdRuntime)
    - Own cleanup manager (CleanupManager)
    - Own hardware state machine (HwStateMachine)
    - Publish UI events via EventBus
    - Execute automation steps
    
    Thread model: One daemon thread per port.
    """
    
    def __init__(
        self,
        port_id: str,
        event_bus: Any,
        auto_run_config: AutoRunConfig,
        baud_rate: int = 115200,
    ) -> None:
        self._port_id: str = port_id
        self._event_bus: Any = event_bus
        self._auto_run_config: AutoRunConfig = auto_run_config
        self._baud_rate: int = baud_rate
        
        # State
        self._state: PortWorkerState = PortWorkerState(port_name=port_id)
        self._hw_state: HwStateMachine = HwStateMachine(port_name=port_id)
        
        # Thread
        self._thread: Optional[threading.Thread] = None
        self._running: threading.Event = threading.Event()
        self._lock: threading.RLock = threading.RLock()
        
        # Hardware (initialized in connect())
        self._serial: Optional[Any] = None
        self._at_client: Optional[Any] = None
        self._cpin_runtime: Optional[CpinRuntime] = None
        self._ussd_runtime: Optional[UssdRuntime] = None
        self._cleanup: Optional[CleanupManager] = None
        
        # Modem state
        self._modem_lock: threading.Lock = threading.Lock()
        self._modem_online: bool = False
        self._sim_state: CpinState = CpinState.UNKNOWN
    
    @property
    def port_id(self) -> str:
        return self._port_id
    
    @property
    def state(self) -> PortWorkerState:
        return self._state
    
    @property
    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()
    
    @property
    def modem_online(self) -> bool:
        with self._modem_lock:
            return self._modem_online

    @property
    def cpin_state(self) -> CpinState:
        """Current CPIN state from CpinRuntime."""
        if self._cpin_runtime:
            return self._cpin_runtime.cpin_state
        return CpinState.UNKNOWN

    @property
    def beta_stats_report(self) -> str:
        """Beta stats report from CpinRuntime (Sprint 15K)."""
        if self._cpin_runtime:
            return self._cpin_runtime.beta_stats.format_report(self._port_id)
        return f"[BETA STATS] PORT={self._port_id}\nNO_CPIN_RUNTIME=YES"
    
    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------
    
    def connect(self, serial_adapter: Any, at_client: Any) -> None:
        """Wire hardware components and start CpinRuntime.

        Sprint 15Q: Verifies serial adapter is open before starting CPIN polling.
        CPIN starts only after: enumeration → AT probe → worker connection → serial open.
        """
        self._serial = serial_adapter
        self._at_client = at_client
        self._cleanup = CleanupManager(serial_adapter)
        self._cpin_runtime = CpinRuntime(self._port_id, at_client, self._event_bus)
        self._ussd_runtime = UssdRuntime(self._port_id, at_client, self._event_bus)

        serial_id = id(serial_adapter)
        logger.info("[WORKER OWNERSHIP] EVENT=connect PORT=%s SERIAL_ID=%d", self._port_id, serial_id)

        # Sprint 15Q: Verify serial adapter is open before starting CPIN
        is_open = hasattr(serial_adapter, 'is_open') and serial_adapter.is_open
        if not is_open:
            logger.warning("[WORKER] %s: Serial adapter not open — cannot start CPIN", self._port_id)
            return

        # Disable modem echo (ATE0) before CPIN polling (Sprint 15D fix)
        logger.info("[AT] %s: Sending ATE0 (disable echo)", self._port_id)
        try:
            self._at_client.send_command("ATE0", timeout=2.0)
            logger.info("[AT] %s: Echo disabled successfully", self._port_id)
        except Exception as e:
            logger.warning("[AT] %s: ATE0 failed (continuing anyway): %s", self._port_id, e)

        # Start CpinRuntime polling (Sprint 15B fix — was never started)
        logger.info("[CPIN] %s: Starting CpinRuntime", self._port_id)
        self._cpin_runtime.reset_stabilization()  # P1-003: clean state on connect
        self._cpin_runtime.start()
        logger.info("[CPIN] %s: CpinRuntime started", self._port_id)

        # Transition hardware state
        self._hw_state.transition(HwState.MODEM_DETECTED, "Serial connected")
        logger.info("[FSM] %s: MODEM_DETECTED", self._port_id)
    
    def disconnect(self) -> None:
        """Disconnect hardware."""
        serial_id = id(self._serial) if self._serial else 0
        logger.info("[WORKER] %s: Disconnecting", self._port_id)
        logger.info("[WORKER OWNERSHIP] EVENT=disconnect PORT=%s SERIAL_ID=%d", self._port_id, serial_id)
        if self._cpin_runtime:
            self._cpin_runtime.stop()
            self._cpin_runtime.reset_stabilization()  # P1-003
            logger.info("[CPIN] %s: CpinRuntime stopped + reset", self._port_id)
        if self._serial:
            logger.info("[PORT CLOSED TRACE] PORT=%s SERIAL_ID=%d CALLER=PortWorker REASON=disconnect", self._port_id, serial_id)
            self._serial.close()
            logger.info("[SERIAL] %s: Serial closed", self._port_id)
        with self._modem_lock:
            self._modem_online = False
        self._hw_state.transition(HwState.OFFLINE, "Disconnected")
        logger.info("[FSM] %s: OFFLINE", self._port_id)
    
    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    
    def start(self) -> None:
        """Start worker thread."""
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._running.set()
            self._thread = threading.Thread(
                target=self._run_loop,
                name=f"Worker-{self._port_id}",
                daemon=True,
            )
            self._thread.start()
        self._publish_status(PortStatus.READY, "Worker started")
    
    def stop(self, timeout: float = 5.0) -> None:
        """Stop worker thread."""
        self._running.clear()
        with self._lock:
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=timeout)
        if self._cpin_runtime:
            self._cpin_runtime.stop()
        self._state.set_status(PortStatus.OFF, "Worker stopped")
        self._publish_status(PortStatus.OFF, "Worker stopped")
    
    def restart(self) -> None:
        """Hardware restart (DD-013)."""
        self.stop()
        self._state.request_reset()
        self._state.reset_cpin_counters()
        self._state.reset_prompt_recovery()
        self._state.clear_card_data()

        # P1-003: Reset CPIN runtime stabilization counters
        if self._cpin_runtime:
            self._cpin_runtime.reset_stabilization()

        # Execute hardware restart
        self._execute_hardware_restart()

        self.start()
    
    # ------------------------------------------------------------------
    # External Commands
    # ------------------------------------------------------------------
    
    def force_retry(self) -> None:
        self._state.set_force_retry()
    
    def queue_auto_run(self) -> None:
        self._state.queue_auto_run()
    
    def set_single_action(self, action: str) -> None:
        self._state.set_single_action(action)
    
    def set_modem_online(self, online: bool) -> None:
        with self._modem_lock:
            self._modem_online = online
    
    # ------------------------------------------------------------------
    # Main Loop
    # ------------------------------------------------------------------
    
    def _run_loop(self) -> None:
        """Main worker loop."""
        logger.info("[WORKER] %s: Main loop started", self._port_id)
        self._state.set_status(PortStatus.READY, "Running")
        while self._running.is_set():
            try:
                self._tick()
            except Exception as e:
                self._publish_status(PortStatus.GAGAL, f"Error: {e}")
                self._state.set_status(PortStatus.GAGAL, str(e))
                # Notify WorkerManager for lifecycle handling (Sprint 13)
                self._publish_event("modem.offline", {"port": self._port_id})
                logger.error("[WORKER] %s: Exception in tick: %s", self._port_id, e)
                time.sleep(1.0)
    
    def _tick(self) -> None:
        """Single iteration of worker loop."""
        # 0. Check modem
        with self._modem_lock:
            modem_online = self._modem_online
        if not modem_online:
            time.sleep(1.0)
            return
        
        # 1. Reset → hardware restart
        if self._state.consume_reset():
            self._execute_hardware_restart()
            return
        
        # 2. Single action
        action = self._state.consume_single_action()
        if action is not None:
            self._execute_step(action)
            return
        
        # 3. Force retry
        if self._state.consume_force_retry():
            self._execute_step("cek_nomor")
            return
        
        # 4. Auto-run — gated by rules
        snapshot = self._state.snapshot()
        blocked, reason = should_block_auto_run(snapshot, self._auto_run_config, modem_online)
        
        if not blocked and self._state.consume_auto_run():
            self._execute_auto_run()
            return
        
        # Idle
        time.sleep(0.1)
    
    # ------------------------------------------------------------------
    # Step Execution (DD-015)
    # ------------------------------------------------------------------
    
    def _execute_step(self, action: str) -> None:
        """Execute a single step with cleanup discipline."""
        self._state.set_status(PortStatus.BUSY, f"Executing: {action}")
        self._publish_status(PortStatus.BUSY, f"Executing: {action}")
        
        if self._at_client:
            # Check CPIN first
            sim_state = self._check_sim()
            if sim_state != CpinState.READY:
                self._state.set_status(PortStatus.CHECKING, f"SIM: {sim_state.value}")
                self._publish_status(PortStatus.CHECKING, f"SIM: {sim_state.value}")
                return
            
            # Execute AT command based on action
            if action == "cek_nomor":
                self._at_client.send_command("AT", timeout=3.0)
            elif action == "cek_status":
                self._at_client.send_command("AT+CPIN?", timeout=3.0)
            elif action == "cek_nik" or action == "cek_kk":
                # USSD dial for NIK/KK check
                if self._ussd_runtime:
                    self._ussd_runtime.dial("*185#", timeout=30.0)
            elif action == "reaktivasi":
                # Reactivation flow
                if self._ussd_runtime:
                    self._ussd_runtime.dial("*185#", timeout=30.0)
        else:
            time.sleep(DIAL_COOLDOWN_SECONDS)
        
        # Cleanup after step
        if self._cleanup:
            self._cleanup.full_cleanup()
        
        self._state.set_status(PortStatus.READY, f"Done: {action}")
        self._publish_status(PortStatus.READY, f"Done: {action}")
    
    def _execute_auto_run(self) -> None:
        """Execute full auto-run sequence."""
        steps = ["cek_nomor", "cek_status", "cek_nik", "cek_kk", "reaktivasi"]
        
        for step in steps:
            if not self._running.is_set():
                break
            
            with self._modem_lock:
                if not self._modem_online:
                    self._state.set_status(PortStatus.CHECKING, "Modem offline")
                    self._publish_status(PortStatus.CHECKING, "Modem offline")
                    break
            
            self._execute_step(step)
    
    def _execute_hardware_restart(self) -> None:
        """Execute hardware restart flow (DD-013)."""
        logger.info("[WORKER] %s: Hardware restart initiated", self._port_id)
        self._state.set_status(PortStatus.RESET, "Restarting modem")
        self._publish_status(PortStatus.RESET, "Restarting modem")
        
        # Transition hardware state
        self._hw_state.transition(HwState.OFFLINE, "Restart initiated")
        logger.info("[FSM] %s: OFFLINE (restart initiated)", self._port_id)
        
        if self._at_client:
            # Send restart command
            logger.info("[AT] %s: Sending ATZ", self._port_id)
            self._at_client.send_command("ATZ", timeout=5.0)
            time.sleep(STABILIZATION_SECONDS)
            
            # Check if modem came back
            logger.info("[AT] %s: Checking modem with AT", self._port_id)
            online = self._at_client.check_modem()
            logger.info("[AT] %s: Modem online=%s", self._port_id, online)
            
            if online:
                # Detect SIM
                sim_state = self._check_sim()
                
                with self._modem_lock:
                    self._modem_online = True
                    self._sim_state = sim_state
                
                # Transition hardware state
                self._hw_state.transition(HwState.MODEM_DETECTED, "Modem online")
                logger.info("[FSM] %s: MODEM_DETECTED", self._port_id)
                self._hw_state.transition(HwState.PORT_READY, "Port ready")
                logger.info("[FSM] %s: PORT_READY", self._port_id)
                
                if sim_state != CpinState.NOT_INSERTED:
                    self._hw_state.transition(HwState.SIM_INSERTED, f"SIM: {sim_state.value}")
                    logger.info("[FSM] %s: SIM_INSERTED (state=%s)", self._port_id, sim_state.value)
                
                if sim_state == CpinState.READY:
                    self._hw_state.transition(HwState.CPIN_READY, "CPIN ready")
                    logger.info("[FSM] %s: CPIN_READY", self._port_id)
                    self._hw_state.transition(HwState.READY, "Fully ready")
                    logger.info("[FSM] %s: READY — full hardware bring-up complete", self._port_id)
                    
                    # Evaluate post-restart
                    if self._auto_run_config.auto_run_enabled:
                        self._state.queue_auto_run()
                        self._state.set_status(PortStatus.READY, "Restart complete, queuing automation")
                        self._publish_status(PortStatus.READY, "Restart complete, queuing automation")
                    else:
                        self._state.set_status(PortStatus.IDLE, "Restart complete, standby")
                        self._publish_status(PortStatus.IDLE, "Restart complete, standby")
                else:
                    self._state.set_status(PortStatus.IDLE, f"Restart complete, SIM: {sim_state.value}")
                    self._publish_status(PortStatus.IDLE, f"Restart complete, SIM: {sim_state.value}")
            else:
                with self._modem_lock:
                    self._modem_online = False
                self._state.set_status(PortStatus.GAGAL, "Restart failed — modem offline")
                self._publish_status(PortStatus.GAGAL, "Restart failed — modem offline")
        else:
            time.sleep(STABILIZATION_SECONDS)
            self._state.set_status(PortStatus.READY, "Reset complete")
            self._publish_status(PortStatus.READY, "Reset complete")
    
    def _check_sim(self) -> CpinState:
        """Check SIM state via AT+CPIN?."""
        if self._at_client:
            logger.info("[AT] %s: Sending AT+CPIN?", self._port_id)
            response = self._at_client.send_command("AT+CPIN?", timeout=CPIN_POLL_TIMEOUT)
            logger.info("[AT] %s: Response=%s", self._port_id, response.raw[:100] if response.raw else "EMPTY")
            state = parse_cpin_response(response.raw)
            logger.info("[CPIN] %s: Parsed state=%s", self._port_id, state.value)
            return state
        return CpinState.UNKNOWN
    
    # ------------------------------------------------------------------
    # EventBus Publishing
    # ------------------------------------------------------------------
    
    def _publish_status(self, status: PortStatus, detail: str = "") -> None:
        if self._event_bus:
            logger.info("[UI] %s: status=%s detail=%s", self._port_id, status.value, detail)
            self._event_bus.publish("ui.port.update", {
                "port": self._port_id,
                "status": status.value,
                "detail": detail,
            })
    
    def _publish_event(self, event_name: str, payload: dict) -> None:
        if self._event_bus:
            self._event_bus.publish(event_name, payload)
