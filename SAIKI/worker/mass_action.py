"""MassAction — Coordinated mass operations across all ports.

Requirement 1: Mass Number Check — "Cek Nomor" toolbar button.
Requirement 2: Mass Reactivation — "Reaktivasi Massal" toolbar button.
Requirement 5: UI feedback — progress, success count, failed count.
"""

import threading
import time
from typing import Dict, Any, Optional, List

from app.domain.enums import PortStatus


class MassActionProgress:
    """Tracks progress of a mass action across multiple ports."""

    def __init__(self, action_name: str, total: int) -> None:
        self._lock: threading.RLock = threading.RLock()
        self._action_name: str = action_name
        self._total: int = total
        self._completed: int = 0
        self._success: int = 0
        self._failed: int = 0
        self._started_at: float = time.time()
        self._port_results: Dict[str, str] = {}

    @property
    def action_name(self) -> str:
        return self._action_name

    @property
    def total(self) -> int:
        return self._total

    @property
    def completed(self) -> int:
        with self._lock:
            return self._completed

    @property
    def success(self) -> int:
        with self._lock:
            return self._success

    @property
    def failed(self) -> int:
        with self._lock:
            return self._failed

    @property
    def is_complete(self) -> bool:
        with self._lock:
            return self._completed >= self._total

    @property
    def elapsed(self) -> float:
        return time.time() - self._started_at

    def record_success(self, port_id: str) -> None:
        """Record a successful completion for a port."""
        with self._lock:
            self._completed += 1
            self._success += 1
            self._port_results[port_id] = "success"

    def record_failure(self, port_id: str, reason: str = "") -> None:
        """Record a failure for a port."""
        with self._lock:
            self._completed += 1
            self._failed += 1
            self._port_results[port_id] = f"failed: {reason}"

    def snapshot(self) -> Dict[str, Any]:
        """Thread-safe snapshot of progress."""
        with self._lock:
            return {
                "action_name": self._action_name,
                "total": self._total,
                "completed": self._completed,
                "success": self._success,
                "failed": self._failed,
                "is_complete": self.is_complete,
                "elapsed": round(self.elapsed, 1),
                "port_results": dict(self._port_results),
            }


class MassAction:
    """Coordinates mass operations across all eligible ports.

    Responsibilities:
    - Determine eligible ports
    - Execute action on each port sequentially
    - Track progress (total, completed, success, failed)
    - Publish progress updates to EventBus
    - Publish final summary
    """

    def __init__(self, event_bus: object) -> None:
        self._event_bus: object = event_bus
        self._lock: threading.RLock = threading.RLock()
        self._current_action: Optional[MassActionProgress] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def is_running(self) -> bool:
        """Check if a mass action is currently executing."""
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    @property
    def progress(self) -> Optional[MassActionProgress]:
        """Get current mass action progress."""
        return self._current_action

    def get_eligible_ports(self, workers: Dict[str, object]) -> List[str]:
        """Return list of port IDs eligible for mass action.

        Eligible: worker is alive AND modem is online.
        """
        eligible: List[str] = []
        for port_id, worker in workers.items():
            if worker.is_alive and worker.modem_online:
                eligible.append(port_id)
        return eligible

    # ------------------------------------------------------------------
    # Mass Number Check
    # ------------------------------------------------------------------

    def start_mass_number_check(self, workers: Dict[str, object]) -> None:
        """Start mass number check on all eligible ports.

        Requirement 1: "Cek Nomor" toolbar button.
        Processes all eligible ports.
        """
        if self.is_running:
            return

        eligible = self.get_eligible_ports(workers)
        if not eligible:
            self._event_bus.publish("mass.action.complete", {
                "action": "cek_nomor",
                "total": 0,
                "success": 0,
                "failed": 0,
                "message": "No eligible ports",
            })
            return

        self._current_action = MassActionProgress("cek_nomor", len(eligible))
        self._thread = threading.Thread(
            target=self._execute_mass_action,
            args=(workers, eligible, "cek_nomor"),
            name="MassCekNomor",
            daemon=True,
        )
        self._thread.start()

    # ------------------------------------------------------------------
    # Mass Reactivation
    # ------------------------------------------------------------------

    def start_mass_reactivation(self, workers: Dict[str, object]) -> None:
        """Start mass reactivation on all eligible ports.

        Requirement 2: "Reaktivasi Massal" toolbar button.
        Only executes final stages: inject -> verify grace date.
        """
        if self.is_running:
            return

        eligible = self.get_eligible_ports(workers)
        if not eligible:
            self._event_bus.publish("mass.action.complete", {
                "action": "reaktivasi",
                "total": 0,
                "success": 0,
                "failed": 0,
                "message": "No eligible ports",
            })
            return

        self._current_action = MassActionProgress("reaktivasi", len(eligible))
        self._thread = threading.Thread(
            target=self._execute_mass_action,
            args=(workers, eligible, "reaktivasi"),
            name="MassReaktivasi",
            daemon=True,
        )
        self._thread.start()

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def _execute_mass_action(
        self,
        workers: Dict[str, object],
        eligible_ports: List[str],
        action: str,
    ) -> None:
        """Execute mass action on eligible ports sequentially.

        Publishes progress after each port completes.
        """
        progress = self._current_action
        if progress is None:
            return

        for port_id in eligible_ports:
            worker = workers.get(port_id)
            if worker is None:
                progress.record_failure(port_id, "worker not found")
                self._publish_progress(progress)
                continue

            try:
                worker.set_single_action(action)
                self._wait_for_completion(worker, timeout=60.0)

                if worker.state.status in (PortStatus.READY, PortStatus.SUKSES):
                    progress.record_success(port_id)
                else:
                    progress.record_failure(port_id, worker.state.status_detail)
            except Exception as e:
                progress.record_failure(port_id, str(e))

            self._publish_progress(progress)

        self._event_bus.publish("mass.action.complete", progress.snapshot())
        self._current_action = None

    def _wait_for_completion(self, worker: object, timeout: float = 60.0) -> None:
        """Wait for a worker to complete its action."""
        start = time.time()
        while time.time() - start < timeout:
            if worker.state.status not in (PortStatus.BUSY, PortStatus.CHECKING):
                return
            time.sleep(0.5)

    def _publish_progress(self, progress: MassActionProgress) -> None:
        """Publish progress update to EventBus."""
        self._event_bus.publish("mass.action.progress", progress.snapshot())
