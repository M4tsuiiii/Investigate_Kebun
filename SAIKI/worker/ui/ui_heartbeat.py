"""UI Heartbeat — detects UI thread freeze and dumps thread stacks.

Sprint 15P: UI freeze forensics.
"""

import logging
import sys
import threading
import time
from typing import Optional

logger = logging.getLogger("saiki.ui.heartbeat")


class UIHeartbeat:
    """Monitors UI thread responsiveness via heartbeat.

    The UI thread must call tick() every second.
    If tick() is not called for >5 seconds, a freeze is detected
    and all thread stacks are dumped.
    """

    def __init__(self, freeze_threshold: float = 5.0) -> None:
        self._freeze_threshold = freeze_threshold
        self._last_tick: float = time.time()
        self._monitor_thread: Optional[threading.Thread] = None
        self._running = threading.Event()
        self._dump_done: bool = False

    def start(self) -> None:
        """Start the heartbeat monitor thread."""
        self._running.set()
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            name="UIHeartbeat",
            daemon=True,
        )
        self._monitor_thread.start()

    def stop(self) -> None:
        """Stop the heartbeat monitor."""
        self._running.clear()

    def tick(self) -> None:
        """Called by UI thread every frame/second to signal liveness."""
        self._last_tick = time.time()
        self._dump_done = False

    def _monitor_loop(self) -> None:
        """Check heartbeat freshness every second."""
        while self._running.is_set():
            elapsed = time.time() - self._last_tick
            if elapsed > self._freeze_threshold and not self._dump_done:
                self._dump_done = True
                logger.error("[UI FREEZE DETECTED] DURATION_SECONDS=%.1f", elapsed)
                self._dump_thread_stacks()
            time.sleep(1.0)

    def _dump_thread_stacks(self) -> None:
        """Dump all thread stacks for forensic analysis."""
        try:
            frames = sys._current_frames()
            thread_names = {t.ident: t.name for t in threading.enumerate()}

            logger.error("=" * 60)
            logger.error("THREAD DUMP — %d threads", len(frames))
            logger.error("=" * 60)

            for thread_id, frame in frames.items():
                thread_name = thread_names.get(thread_id, f"thread-{thread_id}")
                logger.error("--- Thread: %s (id=%d) ---", thread_name, thread_id)

                import traceback
                for line in traceback.format_stack(frame):
                    logger.error("  %s", line.rstrip())

            logger.error("=" * 60)
            logger.error("THREAD DUMP COMPLETE")
            logger.error("=" * 60)

        except Exception as e:
            logger.error("[THREAD DUMP FAILED] error=%s", e)
