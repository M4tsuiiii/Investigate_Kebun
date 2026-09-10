"""ModemMonitor — Detects COM appearance/disappearance and modem state.

DD-018: System must detect COM appearance, disappearance, modem online/offline,
SIM inserted/not inserted. UI and backend must update immediately.
"""

import threading
import time
from typing import Optional, Set, Dict, List, Tuple, Any

try:
    import serial.tools.list_ports
except ImportError:
    serial = None

from app.domain.enums import CpinState
from app.domain.classifier import parse_cpin_response
from app.domain.constants import CPIN_POLL_INTERVAL, CPIN_POLL_TIMEOUT, DEFAULT_AT_TIMEOUT


class ModemMonitor:
    """Monitors modem presence and state.

    Detects:
    - COM appearance → "modem.appeared"
    - COM disappearance → "modem.disappeared"
    - Modem online/offline → "modem.online" / "modem.offline"
    - SIM inserted/not inserted → via AT+CPIN?

    Integration:
    - Notifies PortWorker via set_modem_online()
    - Publishes events to EventBus for UI updates
    """

    def __init__(self, event_bus: object, check_interval: float = 5.0) -> None:
        self._event_bus = event_bus
        self._check_interval = check_interval
        self._known_ports: Set[str] = set()
        self._online_ports: Set[str] = set()
        self._sim_states: Dict[str, CpinState] = {}
        self._modem_ports: Dict[str, object] = {}  # port_id -> modem adapter
        self._lock: threading.RLock = threading.RLock()
        self._thread: Optional[threading.Thread] = None
        self._running: threading.Event = threading.Event()

    def start(self) -> None:
        """Start monitoring thread."""
        self._running.set()
        self._thread = threading.Thread(
            target=self._monitor_loop,
            name="ModemMonitor",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop monitoring thread."""
        self._running.clear()

    def register_modem(self, port_id: str, modem: object) -> None:
        """Register a modem adapter for a port."""
        with self._lock:
            self._modem_ports[port_id] = modem

    def unregister_modem(self, port_id: str) -> None:
        """Unregister a modem adapter."""
        with self._lock:
            self._modem_ports.pop(port_id, None)
            self._online_ports.discard(port_id)
            self._sim_states.pop(port_id, None)

    @property
    def known_ports(self) -> Set[str]:
        with self._lock:
            return set(self._known_ports)

    @property
    def online_ports(self) -> Set[str]:
        with self._lock:
            return set(self._online_ports)

    def get_sim_state(self, port_id: str) -> CpinState:
        """Get cached SIM state for a port."""
        with self._lock:
            return self._sim_states.get(port_id, CpinState.UNKNOWN)

    # ------------------------------------------------------------------
    # Port Detection
    # ------------------------------------------------------------------

    def check_ports(self) -> Set[str]:
        """Check current COM ports."""
        current: Set[str] = set()
        if serial is None:
            return current
        for port in serial.tools.list_ports.comports():
            current.add(port.device)
        return current

    def check_modem_online(self, port_id: str) -> bool:
        """Check if modem at port is online (responds to AT)."""
        with self._lock:
            modem = self._modem_ports.get(port_id)

        if modem is None:
            return False

        try:
            response = modem.send_at("AT", timeout=DEFAULT_AT_TIMEOUT)
            return response is not None
        except Exception:
            return False

    def check_sim_state(self, port_id: str) -> CpinState:
        """Check SIM state via AT+CPIN?."""
        with self._lock:
            modem = self._modem_ports.get(port_id)

        if modem is None:
            return CpinState.UNKNOWN

        try:
            response = modem.send_at("AT+CPIN?", timeout=CPIN_POLL_TIMEOUT)
            return parse_cpin_response(response)
        except Exception:
            return CpinState.UNKNOWN

    # ------------------------------------------------------------------
    # Monitor Loop
    # ------------------------------------------------------------------

    def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        self._known_ports = self.check_ports()

        while self._running.is_set():
            try:
                self._check_ports()
                self._check_modems()
            except Exception:
                pass
            time.sleep(self._check_interval)

    def _check_ports(self) -> None:
        """Check for COM appearance/disappearance."""
        current = self.check_ports()

        events_to_publish: List[Tuple[str, dict]] = []

        with self._lock:
            # New ports
            appeared = current - self._known_ports
            for port in appeared:
                events_to_publish.append(("modem.appeared", {"port": port}))

            # Removed ports
            disappeared = self._known_ports - current
            for port in disappeared:
                events_to_publish.append(("modem.disappeared", {"port": port}))
                self._online_ports.discard(port)
                self._sim_states.pop(port, None)

            self._known_ports = current

        for event_name, payload in events_to_publish:
            self._event_bus.publish(event_name, payload)

    def _check_modems(self) -> None:
        """Check modem online/offline and SIM state for all registered ports."""
        with self._lock:
            ports_to_check = list(self._modem_ports.keys())

        events_to_publish: List[Tuple[str, dict]] = []

        for port_id in ports_to_check:
            # Check online
            online = self.check_modem_online(port_id)

            with self._lock:
                was_online = port_id in self._online_ports

            if online and not was_online:
                self.mark_online(port_id)
            elif not online and was_online:
                self.mark_offline(port_id)

            # Check SIM if online
            if online:
                sim_state = self.check_sim_state(port_id)
                with self._lock:
                    old_sim = self._sim_states.get(port_id, CpinState.UNKNOWN)
                    self._sim_states[port_id] = sim_state

                if sim_state != old_sim:
                    events_to_publish.append(("modem.sim_changed", {
                        "port": port_id,
                        "old_state": old_sim.value,
                        "new_state": sim_state.value,
                    }))

        for event_name, payload in events_to_publish:
            self._event_bus.publish(event_name, payload)

    # ------------------------------------------------------------------
    # Online Status
    # ------------------------------------------------------------------

    def mark_online(self, port_id: str) -> None:
        """Mark a port as online and notify."""
        with self._lock:
            if port_id not in self._online_ports:
                self._online_ports.add(port_id)

        self._event_bus.publish("modem.online", {"port": port_id})

    def mark_offline(self, port_id: str) -> None:
        """Mark a port as offline and notify."""
        with self._lock:
            self._online_ports.discard(port_id)

        self._event_bus.publish("modem.offline", {"port": port_id})
