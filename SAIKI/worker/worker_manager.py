"""WorkerManager — port lifecycle management with modem validation (Sprint 11A, 13).

Scans COM ports, validates modems, creates/destroys PortWorker instances.
Only VALID_MODEM ports become active workers.

Port participation:
  ACTIVE   — participates in automation, auto-run, mass actions
  EXCLUDED — connected and monitored, but ignored by workflows

Architecture reference: ARCHITECTURE.md §4.1, §4.2

Sprint 15Q: Integrates ModemDiscovery pipeline for reliable scan.
Sprint 15R: Single-flight scan, active-worker skip, numeric sort, candidate filter priority.
"""

import logging
import re
import threading
import time
from typing import Dict, Optional, List, Callable, Any

from app.domain.enums import PortState, ValidationResult
from worker.port_worker import PortWorker
from worker.rules import AutoRunConfig
from worker.modem_validator import ModemValidator, PortValidationResult

logger = logging.getLogger("saiki.worker")


class WorkerManager:
    """Manages PortWorker instances for all validated COM ports.

    Responsibilities:
    - Scan COM ports (background thread)
    - Validate modems before worker creation
    - Create PortWorker for validated modems only
    - Inject hardware dependencies (SerialAdapter, ATClient, USSDRuntime)
    - Destroy PortWorker for removed ports
    - Maintain registry of active workers and port states
    - Provide participation control (exclude/include)
    - Provide public API for global commands
    - Cache detected baud rates per port (Sprint 13)
    - Handle modem.offline events for reconnect via scan (Sprint 13)
    """

    def __init__(
        self,
        event_bus: object,
        auto_run_config: AutoRunConfig,
        config: object = None,
        serial_factory: Optional[Callable[..., Any]] = None,
        at_client_factory: Optional[Callable[[Any], Any]] = None,
        ussd_factory: Optional[Callable[[str, Any, Any], Any]] = None,
        modem_validator: Optional[ModemValidator] = None,
        modem_discovery: Optional[Any] = None,
    ) -> None:
        self._event_bus: object = event_bus
        self._auto_run_config: AutoRunConfig = auto_run_config
        self._config: object = config
        self._serial_factory = serial_factory
        self._at_client_factory = at_client_factory
        self._ussd_factory = ussd_factory
        self._modem_validator: ModemValidator = modem_validator or ModemValidator()
        self._modem_discovery = modem_discovery  # Sprint 15Q: ModemDiscovery pipeline
        self._workers: Dict[str, PortWorker] = {}
        self._port_states: Dict[str, PortState] = {}
        self._validation_results: Dict[str, PortValidationResult] = {}
        self._validated_ports: set = set()  # Ports already validated (VALID or INVALID)
        self._baud_rates: Dict[str, int] = {}  # Cached detected baud rates per port (Sprint 13)
        self._failed_ports: Dict[str, float] = {}  # Port → last failure timestamp (Sprint 15R)
        self._lock: threading.RLock = threading.RLock()
        self._scan_thread: Optional[threading.Thread] = None
        self._scanning: threading.Event = threading.Event()
        self._scan_active: threading.Lock = threading.Lock()  # Sprint 15R: single-flight
        self._rescan_pending: threading.Event = threading.Event()  # Sprint 15R: coalesced rescan
        self._scan_interval: float = 3.0  # seconds (reduced from 5s)
        self._initial_scan_done: threading.Event = threading.Event()
        self._scan_count: int = 0

        # Subscribe modem.offline for reconnect (Sprint 13)
        self._subscribe_modem_events()

    # ------------------------------------------------------------------
    # Modem Event Subscription (Sprint 13)
    # ------------------------------------------------------------------

    def _subscribe_modem_events(self) -> None:
        """Subscribe to modem.offline for WorkerManager-driven reconnect."""
        def on_modem_offline(payload):
            port = payload.get("port")
            if port:
                self._handle_modem_offline(port)

        self._event_bus.subscribe("modem.offline", on_modem_offline)

    def _handle_modem_offline(self, port_id: str) -> None:
        """Handle modem offline: mark port offline, destroy worker, wait for scan revalidation."""
        with self._lock:
            state = self._port_states.get(port_id)
            worker = self._workers.get(port_id)

        if worker is None:
            return

        logger.info("[WORKER] %s: OFFLINE — destroying worker, awaiting scan revalidation", port_id)

        # Destroy worker — scan loop will revalidate and recreate if modem returns
        self.destroy_worker(port_id)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def workers(self) -> Dict[str, PortWorker]:
        """Snapshot of all active workers."""
        with self._lock:
            return dict(self._workers)

    def get_worker(self, port_id: str) -> Optional[PortWorker]:
        """Get worker by port ID."""
        with self._lock:
            return self._workers.get(port_id)

    def get_port_state(self, port_id: str) -> Optional[PortState]:
        """Get port participation state."""
        with self._lock:
            return self._port_states.get(port_id)

    def get_all_port_states(self) -> Dict[str, PortState]:
        """Snapshot of all port states."""
        with self._lock:
            return dict(self._port_states)

    def get_validation_results(self) -> Dict[str, PortValidationResult]:
        """Snapshot of validation results (for startup report)."""
        with self._lock:
            return dict(self._validation_results)

    def get_active_ports(self) -> List[str]:
        """Return list of port IDs in ACTIVE state."""
        with self._lock:
            return [p for p, s in self._port_states.items() if s == PortState.ACTIVE]

    def get_excluded_ports(self) -> List[str]:
        """Return list of port IDs in EXCLUDED state."""
        with self._lock:
            return [p for p, s in self._port_states.items() if s == PortState.EXCLUDED]

    def is_port_active(self, port_id: str) -> bool:
        """Check if a port is in ACTIVE state ( participates in automation)."""
        with self._lock:
            state = self._port_states.get(port_id)
            return state == PortState.ACTIVE

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------

    def start_scanning(self) -> None:
        """Start background port scanning. Non-blocking."""
        self._scanning.set()
        self._scan_thread = threading.Thread(
            target=self._scan_loop,
            name="PortScanner",
            daemon=True,
        )
        self._scan_thread.start()
        logger.info("[SCAN] Background scan started (interval=%.1fs)", self._scan_interval)

    def stop_scanning(self) -> None:
        """Stop background port scanning."""
        self._scanning.clear()

    def scan_once(self) -> List[str]:
        """Scan COM ports once and return list of port IDs (numeric sorted)."""
        from worker.modem_discovery import sort_com_ports
        raw = self._scan_ports_raw()
        return sort_com_ports(raw)

    def _scan_ports_raw(self) -> List[str]:
        """Raw COM port enumeration (no sorting)."""
        try:
            import serial.tools.list_ports
            ports: List[str] = []
            for port in serial.tools.list_ports.comports():
                ports.append(port.device)
            return ports
        except ImportError:
            return []

    def _scan_ports_with_metadata(self) -> List[Any]:
        """Enumerate COM ports with full metadata using ModemDiscovery."""
        if self._modem_discovery is not None:
            return self._modem_discovery.enumerate_ports()
        return []

    def _scan_loop(self) -> None:
        """Background scan loop — single-flight with coalesced rescan."""
        while self._scanning.is_set():
            # Wait before scanning
            self._scanning.wait(self._scan_interval)

            if not self._scanning.is_set():
                break

            # Single-flight: only one scan at a time
            acquired = self._scan_active.acquire(blocking=False)
            if not acquired:
                logger.info("[SCAN ALREADY RUNNING] Coalescing pending rescan")
                self._rescan_pending.set()
                continue

            try:
                scan_start = time.time()
                scan_id = self._scan_count + 1
                logger.info("[SCAN START] ID=%d", scan_id)

                self._scan_and_update()

                scan_duration = time.time() - scan_start
                self._scan_count += 1
                logger.info(
                    "[SCAN COMPLETE] ID=%d DURATION=%.2f WORKERS=%d",
                    scan_id, scan_duration, len(self._workers),
                )
                if not self._initial_scan_done.is_set():
                    self._initial_scan_done.set()
            except Exception as e:
                logger.error("[SCAN ERROR] %s", e)
            finally:
                self._scan_active.release()

            # If a rescan was coalesced while we were running, run again
            if self._rescan_pending.is_set():
                self._rescan_pending.clear()
                continue

    def _scan_and_update(self) -> None:
        """Scan ports, validate modems, create/destroy workers."""
        scan_start = time.time()

        if self._modem_discovery is not None:
            self._scan_with_discovery()
        else:
            self._scan_with_validator()

        scan_duration = time.time() - scan_start
        self._scan_count += 1
        if self._scan_count == 1:
            logger.info("[SCAN] First scan completed in %.2fs", scan_duration)
        if not self._initial_scan_done.is_set():
            self._initial_scan_done.set()

    def _scan_with_discovery(self) -> None:
        """Scan using Sprint 15Q ModemDiscovery pipeline.

        Sprint 15R: Uses numeric sort, active-worker skip, candidate filter priority.
        """
        from worker.modem_discovery import sort_com_ports

        discovery = self._modem_discovery

        # Stage 1: Enumerate
        all_ports = discovery.enumerate_ports()
        detected_set = {meta.port_name for meta in all_ports}
        detected_list = sort_com_ports(list(detected_set))
        logger.info("[COM] Discovery: %d ports enumerated", len(all_ports))

        with self._lock:
            current_workers = set(self._workers.keys())
            active_ports = set(p for p, s in self._port_states.items()
                               if s in (PortState.ACTIVE, PortState.EXCLUDED))

        # Handle removed ports first
        for port_id in current_workers - detected_set:
            logger.info("[SCAN] %s: PORT_REMOVED", port_id)
            self.destroy_worker(port_id)

        # Stage 2: Filter candidates (priority-aware, numerically sorted input)
        candidates, skipped_candidates = discovery.filter_candidates(all_ports)

        # Stage 3: Skip active workers and retry-cooldown ports
        eligible, skipped_active = discovery.filter_active_workers(
            candidates, active_ports, self._failed_ports,
        )
        logger.info(
            "[SCAN] Candidates: %d, eligible: %d, active-skip: %d",
            len(candidates), len(eligible), len(skipped_active),
        )

        # Stage 4: Probe eligible candidates (bounded concurrency, numerically sorted input)
        probe_results = discovery.probe_concurrent(eligible)

        # Stage 5: Hand off verified ports (output numerically sorted — guaranteed by bounded probing)
        verified_count = 0
        for meta, probe in zip(eligible, probe_results):
            port_id = meta.port_name

            if port_id in current_workers:
                continue

            if probe is None or not probe.success:
                if probe:
                    logger.info("[DISCOVERY REJECTED] PORT=%s REASON=%s", port_id, probe.reason)
                with self._lock:
                    self._validated_ports.add(port_id)
                    self._failed_ports[port_id] = time.time()
                continue

            # Port passed AT probe — verified
            logger.info("[DISCOVERY VERIFIED] PORT=%s BAUD=%d", port_id, probe.baud_rate)

            with self._lock:
                self._port_states[port_id] = PortState.VALID_MODEM
                self._baud_rates[port_id] = probe.baud_rate
                self._validated_ports.add(port_id)

            self.create_worker(port_id)
            verified_count += 1

        logger.info("[SCAN] Discovery scan: verified=%d", verified_count)

        # Mark offline ports
        with self._lock:
            for port_id, state in list(self._port_states.items()):
                if state in (PortState.ACTIVE, PortState.EXCLUDED) and port_id not in detected_set:
                    self._port_states[port_id] = PortState.OFFLINE

        # Publish scan complete
        self._event_bus.publish("ui.scan.complete", {
            "ports": [{"id": p, "online": True} for p in detected_list],
        })

    def _scan_with_validator(self) -> None:
        """Scan using legacy ModemValidator path (fallback)."""
        from worker.modem_discovery import sort_com_ports

        detected_list = sort_com_ports(self._scan_ports_raw())
        detected_set = set(detected_list)
        logger.info("[COM] Scan complete: %d ports", len(detected_list))

        with self._lock:
            current_workers = set(self._workers.keys())
            known_ports = set(self._validated_ports)

        # New ports — validate only if not previously validated (preserves numeric order)
        for port_id in detected_list:
            if port_id in current_workers:
                continue
            if port_id in known_ports:
                # Previously validated — skip revalidation
                cached_baud = self._baud_rates.get(port_id)
                if cached_baud:
                    logger.info("[SCAN] %s: REVALIDATED (cached baud=%d)", port_id, cached_baud)
                else:
                    logger.info("[SCAN] %s: WORKER_REUSED (reappearing validated port)", port_id)
                self.create_worker(port_id)
                continue

            logger.info("[SCAN] %s: NEW_PORT", port_id)
            with self._lock:
                self._port_states[port_id] = PortState.DISCOVERED
            self._event_bus.publish("ui.port.discovered", {"port": port_id})

            val_start = time.time()
            validation = self._validate_port(port_id)
            val_duration = time.time() - val_start
            logger.info("[VALIDATOR] %s: Validation took %.2fs", port_id, val_duration)
            with self._lock:
                self._validation_results[port_id] = validation
                self._validated_ports.add(port_id)
                if validation.baud_rate > 0:
                    self._baud_rates[port_id] = validation.baud_rate

            if validation.status == ValidationResult.VALID_MODEM:
                baud_info = f" baud={validation.baud_rate}" if validation.baud_rate else ""
                logger.info("[SCAN] %s: VALIDATED%s — creating worker", port_id, baud_info)
                with self._lock:
                    self._port_states[port_id] = PortState.VALID_MODEM
                self.create_worker(port_id)
            else:
                logger.info("[SCAN] %s: %s — ignoring", port_id, validation.status.value)
                with self._lock:
                    self._port_states.pop(port_id, None)

        # Removed ports — destroy workers
        for port_id in current_workers - detected_set:
            logger.info("[SCAN] %s: PORT_REMOVED", port_id)
            self.destroy_worker(port_id)

        # Mark offline ports
        with self._lock:
            for port_id, state in list(self._port_states.items()):
                if state in (PortState.ACTIVE, PortState.EXCLUDED) and port_id not in detected_set:
                    self._port_states[port_id] = PortState.OFFLINE

        # Publish scan complete
        self._event_bus.publish("ui.scan.complete", {
            "ports": [{"id": p, "online": True} for p in detected_list],
        })

    def _validate_port(self, port_id: str) -> PortValidationResult:
        """Validate a COM port using ModemValidator."""
        logger.info("[VALIDATOR] %s: Validation started", port_id)
        if not self._serial_factory:
            # No factory — skip validation, treat as unresponsive
            logger.info("[VALIDATOR] %s: No serial factory — UNRESPONSIVE", port_id)
            return PortValidationResult(
                port_id=port_id,
                status=ValidationResult.UNRESPONSIVE,
                error="No serial factory configured",
            )
        result = self._modem_validator.validate(port_id, self._serial_factory)
        logger.info("[VALIDATOR] %s: Validation complete — %s", port_id, result.status.value)
        return result

    # ------------------------------------------------------------------
    # Worker Lifecycle
    # ------------------------------------------------------------------

    def create_worker(self, port_id: str) -> PortWorker:
        """Create a new PortWorker for a validated COM port with hardware dependencies."""
        with self._lock:
            if port_id in self._workers:
                logger.info("[WORKER] %s: Already exists — skipping", port_id)
                return self._workers[port_id]

            # 1. Create worker
            worker = PortWorker(port_id, self._event_bus, self._auto_run_config)
            logger.info("[WORKER] %s: Created", port_id)
            logger.info("[WORKER OWNERSHIP] EVENT=create PORT=%s WORKER_ID=%d", port_id, id(worker))

            # 2. Inject hardware dependencies
            self._inject_dependencies(port_id, worker)

            # 3. Register and start
            self._workers[port_id] = worker
            # Set state to ACTIVE (worker is created = validated modem)
            if self._port_states.get(port_id) != PortState.EXCLUDED:
                self._port_states[port_id] = PortState.ACTIVE
            worker.start()
            logger.info("[WORKER] %s: Started (state=%s)", port_id, self._port_states.get(port_id))

        self._event_bus.publish("ui.port.discovered", {"port": port_id})
        logger.info("[UI] %s: port.discovered published", port_id)
        return worker

    def _inject_dependencies(self, port_id: str, worker: PortWorker) -> None:
        """Inject hardware dependencies into a worker using cached baud rate."""
        serial_adapter = None
        at_client = None

        # Get cached baud rate (Sprint 13)
        baud_rate = self._baud_rates.get(port_id, 115200)

        # Create serial adapter with detected baud rate
        if self._serial_factory:
            try:
                serial_adapter = self._serial_factory(port_id, baud_rate)
                logger.info("[SERIAL] %s: Created (baud=%d)", port_id, baud_rate)
            except Exception as e:
                logger.error("[SERIAL] %s: Creation failed: %s", port_id, e)

        # Create AT client
        if self._at_client_factory and serial_adapter:
            try:
                at_client = self._at_client_factory(serial_adapter)
                logger.info("[AT] %s: Created", port_id)
            except Exception as e:
                logger.error("[AT] %s: Creation failed: %s", port_id, e)

        # Connect worker to hardware
        if serial_adapter and at_client:
            worker.connect(serial_adapter, at_client)
            serial_id = id(serial_adapter)
            logger.info("[WORKER CONNECTED] PORT=%s BAUD=%d SERIAL_ID=%d", port_id, baud_rate, serial_id)
            logger.info("[CPIN START ELIGIBLE] PORT=%s", port_id)
        else:
            logger.warning("[WORKER] %s: No hardware — running in offline mode", port_id)

    def destroy_worker(self, port_id: str) -> None:
        """Destroy a PortWorker."""
        with self._lock:
            worker = self._workers.pop(port_id, None)
            # Transition port state
            old_state = self._port_states.get(port_id)
            if old_state in (PortState.ACTIVE, PortState.EXCLUDED):
                self._port_states[port_id] = PortState.REMOVED
            elif old_state == PortState.OFFLINE:
                self._port_states[port_id] = PortState.REMOVED
        if worker:
            worker_id = id(worker)
            serial_id = id(getattr(worker, '_serial', None)) if getattr(worker, '_serial', None) else 0
            logger.info("[WORKER OWNERSHIP] EVENT=destroy PORT=%s WORKER_ID=%d SERIAL_ID=%d", port_id, worker_id, serial_id)
            worker.disconnect()
            worker.stop()
            logger.info("[WORKER] Destroyed: %s", port_id)
            self._event_bus.publish("ui.port.removed", {"port": port_id})

    # ------------------------------------------------------------------
    # Participation Control (Sprint 11A)
    # ------------------------------------------------------------------

    def exclude_port(self, port_id: str) -> bool:
        """Exclude a port from automation participation.

        EXCLUDED ports remain connected and monitored but are ignored
        by auto-run, mass actions, and workflow scheduling.

        Returns True if state changed.
        """
        with self._lock:
            old_state = self._port_states.get(port_id)
            if old_state != PortState.ACTIVE:
                logger.info("[PARTICIPATE] %s: cannot exclude (state=%s)", port_id, old_state)
                return False
            self._port_states[port_id] = PortState.EXCLUDED
        logger.info("[PARTICIPATE] %s: EXCLUDED", port_id)
        self._event_bus.publish("port.state_changed", {
            "port": port_id,
            "old_state": old_state.value,
            "new_state": PortState.EXCLUDED.value,
        })
        # Cancel any queued workflow for this port
        self._event_bus.publish("port.excluded", {"port": port_id})
        return True

    def include_port(self, port_id: str) -> bool:
        """Include a port back into automation participation.

        Returns True if state changed.
        """
        with self._lock:
            old_state = self._port_states.get(port_id)
            if old_state != PortState.EXCLUDED:
                logger.info("[PARTICIPATE] %s: cannot include (state=%s)", port_id, old_state)
                return False
            self._port_states[port_id] = PortState.ACTIVE
        logger.info("[PARTICIPATE] %s: ACTIVE", port_id)
        self._event_bus.publish("port.state_changed", {
            "port": port_id,
            "old_state": old_state.value,
            "new_state": PortState.ACTIVE.value,
        })
        return True

    # ------------------------------------------------------------------
    # Global Commands
    # ------------------------------------------------------------------

    def stop_all(self) -> None:
        """Stop all workers and scanning."""
        self.stop_scanning()
        with self._lock:
            for worker in self._workers.values():
                worker.disconnect()
                worker.stop()
            self._workers.clear()
            self._port_states.clear()
            self._validated_ports.clear()
            self._baud_rates.clear()
            self._failed_ports.clear()
            self._scan_count = 0
        self._initial_scan_done.clear()
        self._rescan_pending.clear()

    def clear_validation_cache(self) -> None:
        """Clear validated ports cache, baud rate cache, and failed-ports cooldown."""
        with self._lock:
            self._validated_ports.clear()
            self._baud_rates.clear()
            self._failed_ports.clear()
        logger.info("[SCAN] Validation + baud + failed-ports cache cleared")

    def restart_all(self) -> None:
        """Restart all ACTIVE workers."""
        with self._lock:
            for port_id, worker in self._workers.items():
                if self._port_states.get(port_id) == PortState.ACTIVE:
                    worker.force_retry()

    def queue_auto_run_all(self) -> None:
        """Queue auto-run on all ACTIVE workers only."""
        with self._lock:
            for port_id, worker in self._workers.items():
                if self._port_states.get(port_id) == PortState.ACTIVE:
                    worker.queue_auto_run()
