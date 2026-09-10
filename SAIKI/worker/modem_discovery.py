"""ModemDiscovery — Enumeration, candidate filtering, AT probe, verified handoff.

Sprint 15Q: Replaces blind scan+validate with a disciplined pipeline.
Sprint 15R: Adds numeric sort, active-worker skip, priority candidate filter.

Pipeline:
  1. Enumerate Windows ports with metadata
  2. Filter candidates by metadata (priority-aware)
  3. Skip active workers
  4. Probe candidates at 115200 with AT → OK validation
  5. Hand off verified ports to worker creation (numerically sorted)

No port is considered connected until it passes the AT probe.
CPIN polling starts only after the worker is connected.

Configuration constants live in app/domain/constants.py.
"""

import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from app.domain.constants import (
    DISCOVERY_BAUD_RATE,
    DISCOVERY_PROBE_TIMEOUT,
    DISCOVERY_MAX_CONCURRENT,
    DISCOVERY_CANDIDATE_KEYWORDS,
    DISCOVERY_CANDIDATE_KEYWORDS_HIGH_PRIORITY,
    DISCOVERY_KNOWN_HWIDS,
    DISCOVERY_KNOWN_VIDS,
    DISCOVERY_RETRY_COOLDOWN,
)

logger = logging.getLogger("saiki.discovery")


# ------------------------------------------------------------------
# Task 1: Numeric COM port sort
# ------------------------------------------------------------------

def sort_com_ports(ports) -> list:
    """Sort COM port names numerically.

    COM9 before COM10, COM101 before COM122.
    Not lexical. Works on strings, PortMetadata objects, or VerifiedPort objects.
    """
    def _com_number(port):
        name = port.port_name if hasattr(port, "port_name") else str(port)
        m = re.search(r'(\d+)', name)
        return int(m.group(1)) if m else 0

    return sorted(ports, key=_com_number)


def _com_sort_key(port_name: str) -> int:
    """Extract numeric COM number for sorting."""
    m = re.search(r'(\d+)', port_name)
    return int(m.group(1)) if m else 0


# ------------------------------------------------------------------
# Data classes
# ------------------------------------------------------------------

class PortMetadata:
    """Metadata for an enumerated COM port."""

    __slots__ = ("port_name", "description", "manufacturer", "vid", "pid", "hwid")

    def __init__(
        self,
        port_name: str,
        description: str = "",
        manufacturer: str = "",
        vid: str = "",
        pid: str = "",
        hwid: str = "",
    ) -> None:
        self.port_name = port_name
        self.description = description
        self.manufacturer = manufacturer
        self.vid = vid
        self.pid = pid
        self.hwid = hwid

    def __repr__(self) -> str:
        return (
            f"PortMetadata({self.port_name}, desc={self.description!r}, "
            f"mfr={self.manufacturer!r}, vid={self.vid}, pid={self.pid})"
        )


class ProbeResult:
    """Result of an AT probe on a single port."""

    __slots__ = ("port_name", "baud_rate", "success", "response", "reason")

    def __init__(
        self,
        port_name: str,
        baud_rate: int = 0,
        success: bool = False,
        response: str = "",
        reason: str = "",
    ) -> None:
        self.port_name = port_name
        self.baud_rate = baud_rate
        self.success = success
        self.response = response
        self.reason = reason

    def __repr__(self) -> str:
        return (
            f"ProbeResult({self.port_name}, baud={self.baud_rate}, "
            f"ok={self.success}, reason={self.reason!r})"
        )


class VerifiedPort:
    """A port that has passed enumeration, candidate filter, and AT probe."""

    __slots__ = ("metadata", "probe_result")

    def __init__(self, metadata: PortMetadata, probe_result: ProbeResult) -> None:
        self.metadata = metadata
        self.probe_result = probe_result

    @property
    def port_name(self) -> str:
        return self.metadata.port_name

    @property
    def baud_rate(self) -> int:
        return self.probe_result.baud_rate


# ------------------------------------------------------------------
# Discovery pipeline
# ------------------------------------------------------------------

class ModemDiscovery:
    """Orchestrates port enumeration → candidate filter → AT probe → verified handoff.

    Usage:
        discovery = ModemDiscovery()
        verified = discovery.discover_all()  # returns list of VerifiedPort
    """

    def __init__(
        self,
        max_concurrent: int = DISCOVERY_MAX_CONCURRENT,
        baud_rate: int = DISCOVERY_BAUD_RATE,
        probe_timeout: float = DISCOVERY_PROBE_TIMEOUT,
    ) -> None:
        self._max_concurrent = max_concurrent
        self._baud_rate = baud_rate
        self._probe_timeout = probe_timeout
        self._candidate_keywords = DISCOVERY_CANDIDATE_KEYWORDS
        self._high_priority_keywords = DISCOVERY_CANDIDATE_KEYWORDS_HIGH_PRIORITY
        self._known_hwids = DISCOVERY_KNOWN_HWIDS
        self._known_vids = DISCOVERY_KNOWN_VIDS

    # ------------------------------------------------------------------
    # Task 1: Enumerate Windows ports with metadata
    # ------------------------------------------------------------------

    def enumerate_ports(self) -> List[PortMetadata]:
        """Enumerate all COM ports from Windows OS, collecting full metadata.

        Returns list of PortMetadata (unsorted — caller must sort).
        """
        try:
            import serial.tools.list_ports
        except ImportError:
            logger.warning("[DISCOVERY] pyserial not available — cannot enumerate ports")
            return []

        results: List[PortMetadata] = []
        for info in serial.tools.list_ports.comports():
            meta = PortMetadata(
                port_name=info.device,
                description=str(info.description) if info.description else "",
                manufacturer=str(info.manufacturer) if info.manufacturer else "",
                vid=str(info.vid) if info.vid else "",
                pid=str(info.pid) if info.pid else "",
                hwid=str(info.hwid) if info.hwid else "",
            )
            results.append(meta)
            logger.info(
                "[DISCOVERY ENUMERATED] PORT=%s DESCRIPTION=%s MANUFACTURER=%s VID=%s PID=%s HWID=%s",
                meta.port_name, meta.description, meta.manufacturer,
                meta.vid, meta.pid, meta.hwid,
            )

        logger.info("[DISCOVERY] Enumerated %d COM ports", len(results))
        return results

    # ------------------------------------------------------------------
    # Task 4: Candidate metadata filter (priority-aware)
    # ------------------------------------------------------------------

    def filter_candidates(self, ports: List[PortMetadata]) -> Tuple[List[PortMetadata], List[Tuple[PortMetadata, str]]]:
        """Filter ports by metadata to identify likely modem candidates.

        Priority-aware: XR21V1414/Exar/Quectel hardware is preferred.
        Generic "USB Serial" without matching VID/PID/HWID is rejected.

        Input should be pre-sorted numerically.
        Returns (candidates, skipped) where skipped is list of (port, reason).
        Candidates are returned in the same order as input (numerically sorted).
        """
        candidates: List[PortMetadata] = []
        skipped: List[Tuple[PortMetadata, str]] = []

        for meta in ports:
            reason = self._check_candidate(meta)
            if reason:
                candidates.append(meta)
                logger.info(
                    "[DISCOVERY CANDIDATE] PORT=%s REASON=%s",
                    meta.port_name, reason,
                )
            else:
                skipped.append((meta, "not_modem_candidate"))
                logger.info(
                    "[DISCOVERY SKIPPED] PORT=%s REASON=not_modem_candidate",
                    meta.port_name,
                )

        logger.info(
            "[DISCOVERY] Candidates: %d / %d ports",
            len(candidates), len(ports),
        )
        return candidates, skipped

    def _check_candidate(self, meta: PortMetadata) -> Optional[str]:
        """Check if a port's metadata matches known modem hardware.

        Priority order:
          1. HWID/VID:PID match for known hardware (XR21V1414, Quectel)
          2. Description contains high-priority keywords (XR21V1414, Quectel)
          3. Description/manufacturer contains other keywords

        Generic "USB Serial" is only accepted if VID/PID/HWID matches known hardware.
        Returns match reason string or None if not a candidate.
        """
        searchable = " ".join([
            meta.description,
            meta.manufacturer,
            meta.hwid,
        ]).lower()

        # Priority 1: HWID/VID:PID match for known hardware
        for hwid_pattern in self._known_hwids:
            if hwid_pattern.lower() in searchable:
                return f"hardware_match({hwid_pattern})"

        if meta.vid and meta.vid.upper() in self._known_vids:
            return f"vid_match({meta.vid})"

        # Priority 2: High-priority keywords (XR21V1414, Quectel)
        for keyword in self._high_priority_keywords:
            if keyword.lower() in searchable:
                return f"metadata_match({keyword})"

        # Priority 3: Generic keywords — but reject broad "USB Serial" without HWID match
        for keyword in self._candidate_keywords:
            if keyword.lower() in searchable:
                # If keyword is "USB Serial", require HWID/VID match
                if keyword.lower() == "usb serial":
                    # Check if HWID or VID matches known hardware
                    has_known_hwid = any(
                        h.lower() in searchable for h in self._known_hwids
                    )
                    has_known_vid = meta.vid and meta.vid.upper() in self._known_vids
                    if not has_known_hwid and not has_known_vid:
                        return None  # Reject generic USB Serial without hardware identity
                return f"metadata_match({keyword})"

        return None

    # ------------------------------------------------------------------
    # Task 3: Skip active workers
    # ------------------------------------------------------------------

    def filter_active_workers(
        self,
        candidates: List[PortMetadata],
        active_ports: Set[str],
        failed_ports: Optional[Dict[str, float]] = None,
    ) -> Tuple[List[PortMetadata], List[Tuple[PortMetadata, str]]]:
        """Remove active workers and recently-failed ports from candidate list.

        Returns (eligible, skipped).
        """
        eligible: List[PortMetadata] = []
        skipped: List[Tuple[PortMetadata, str]] = []
        now = time.time()

        for meta in candidates:
            port_id = meta.port_name

            if port_id in active_ports:
                skipped.append((meta, "already_active_worker"))
                logger.info(
                    "[DISCOVERY SKIPPED] PORT=%s REASON=already_active_worker",
                    port_id,
                )
                continue

            if failed_ports and port_id in failed_ports:
                last_fail = failed_ports[port_id]
                if now - last_fail < DISCOVERY_RETRY_COOLDOWN:
                    remaining = DISCOVERY_RETRY_COOLDOWN - (now - last_fail)
                    skipped.append((meta, f"retry_cooldown({remaining:.0f}s)"))
                    logger.info(
                        "[DISCOVERY SKIPPED] PORT=%s REASON=retry_cooldown(%.0fs remaining)",
                        port_id, remaining,
                    )
                    continue

            eligible.append(meta)

        return eligible, skipped

    # ------------------------------------------------------------------
    # Task 5: AT probe at 115200 (bounded concurrency preserved)
    # ------------------------------------------------------------------

    def probe_port(self, meta: PortMetadata) -> ProbeResult:
        """Probe a single port at the configured baud rate.

        Sends AT and requires explicit OK in response.
        Echoed AT without OK is rejected.
        Temporary probe handle is always closed.
        """
        port_name = meta.port_name
        baud = self._baud_rate

        logger.info("[DISCOVERY PROBE START] PORT=%s BAUD=%d", port_name, baud)

        try:
            import serial
        except ImportError:
            result = ProbeResult(port_name, baud, False, "", "pyserial_not_available")
            logger.info(
                "[DISCOVERY PROBE RESULT] PORT=%s BAUD=%d SUCCESS=NO REASON=pyserial_not_available",
                port_name, baud,
            )
            return result

        ser = None
        try:
            ser = serial.Serial(
                port=port_name,
                baudrate=baud,
                timeout=self._probe_timeout,
            )
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            ser.write(b"AT\r\n")

            response_bytes = b""
            deadline = time.time() + self._probe_timeout
            while time.time() < deadline:
                if ser.in_waiting:
                    chunk = ser.read(ser.in_waiting)
                    if chunk:
                        response_bytes += chunk
                        decoded = response_bytes.decode("utf-8", errors="replace")
                        if "OK" in decoded or "ERROR" in decoded:
                            break
                time.sleep(0.05)

            response = response_bytes.decode("utf-8", errors="replace").strip()

            if not response:
                result = ProbeResult(port_name, baud, False, "", "no_response")
                logger.info(
                    "[DISCOVERY PROBE RESULT] PORT=%s BAUD=%d SUCCESS=NO REASON=no_response",
                    port_name, baud,
                )
            elif "OK" in response.upper():
                result = ProbeResult(port_name, baud, True, response, "ok")
                logger.info(
                    "[DISCOVERY PROBE RESULT] PORT=%s BAUD=%d SUCCESS=YES RESPONSE=%s",
                    port_name, baud, response[:100],
                )
            else:
                result = ProbeResult(port_name, baud, False, response[:200], "at_no_ok")
                logger.info(
                    "[DISCOVERY PROBE RESULT] PORT=%s BAUD=%d SUCCESS=NO REASON=at_no_ok RESPONSE=%s",
                    port_name, baud, response[:100],
                )

            return result

        except Exception as e:
            result = ProbeResult(port_name, baud, False, "", f"exception:{e}")
            logger.info(
                "[DISCOVERY PROBE RESULT] PORT=%s BAUD=%d SUCCESS=NO REASON=exception:%s",
                port_name, baud, e,
            )
            return result
        finally:
            if ser is not None:
                try:
                    ser.close()
                except Exception:
                    pass

    def probe_concurrent(self, candidates: List[PortMetadata]) -> List[ProbeResult]:
        """Probe multiple candidates with bounded concurrency.

        Input candidates should be pre-sorted numerically.
        Uses ThreadPoolExecutor with max_concurrent workers.
        Returns list of ProbeResults (one per candidate, same order as input).
        """
        if not candidates:
            return []

        results: List[ProbeResult] = [None] * len(candidates)  # type: ignore[list-item]

        with ThreadPoolExecutor(max_workers=self._max_concurrent) as executor:
            future_to_idx = {
                executor.submit(self.probe_port, meta): idx
                for idx, meta in enumerate(candidates)
            }
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    results[idx] = future.result()
                except Exception as e:
                    meta = candidates[idx]
                    results[idx] = ProbeResult(
                        meta.port_name, self._baud_rate, False, "",
                        f"executor_exception:{e}",
                    )

        probe_count = sum(1 for r in results if r and r.success)
        logger.info(
            "[DISCOVERY] Probe complete: %d / %d candidates verified",
            probe_count, len(candidates),
        )
        return results

    # ------------------------------------------------------------------
    # Full pipeline convenience method
    # ------------------------------------------------------------------

    def discover_all(
        self,
        active_ports: Optional[Set[str]] = None,
        failed_ports: Optional[Dict[str, float]] = None,
    ) -> List[VerifiedPort]:
        """Run the full discovery pipeline: enumerate → filter → probe → verified.

        Input: ports from Windows enumeration only.
        No hard-coded COM range; no detached probe range.

        Returns numerically sorted list of VerifiedPort objects.
        """
        all_ports = self.enumerate_ports()
        if not all_ports:
            return []

        # Sort numerically before filtering
        all_ports = sort_com_ports(all_ports)

        candidates, _skipped_meta = self.filter_candidates(all_ports)
        if not candidates:
            return []

        # Filter out active workers
        if active_ports:
            candidates, _skipped_active = self.filter_active_workers(
                candidates, active_ports, failed_ports,
            )

        if not candidates:
            return []

        # Probe candidates (bounded concurrency, numerically sorted input)
        probe_results = self.probe_concurrent(candidates)

        # Collect verified ports (output numerically sorted — guaranteed by bounded probing)
        verified: List[VerifiedPort] = []
        for meta, probe in zip(candidates, probe_results):
            if probe and probe.success:
                verified.append(VerifiedPort(meta, probe))

        logger.info("[DISCOVERY] discover_all: %d verified ports", len(verified))
        return verified
