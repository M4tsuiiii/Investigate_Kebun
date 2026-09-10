"""Sprint 15M: Real Hardware Beta Validation Script.

Runs the SAIKI modem lifecycle pipeline for N minutes with a real modem.
Collects BetaStats + Delivery Report data.

Usage:
    python -m beta_test --duration 1800 --port COM3
    python -m beta_test  # defaults: 30 min, auto-detect port
"""

import argparse
import sys
import time
import logging
from unittest.mock import MagicMock
from datetime import datetime

# Configure logging to capture all audit traces
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("beta_test_log.txt", mode="w"),
    ],
)
logger = logging.getLogger("beta_test")


def main():
    parser = argparse.ArgumentParser(description="SAIKI Beta Validation Test")
    parser.add_argument("--duration", type=int, default=1800, help="Test duration in seconds (default: 1800)")
    parser.add_argument("--port", type=str, default=None, help="COM port (default: auto-detect)")
    parser.add_argument("--output", type=str, default="beta_test_log.txt", help="Log file path")
    args = parser.parse_args()

    print("=" * 60)
    print("SAIKI BETA VALIDATION TEST")
    print("=" * 60)
    print(f"Duration: {args.duration}s ({args.duration / 60:.1f} min)")
    print(f"Port: {args.port or 'auto-detect'}")
    print(f"Output: {args.output}")
    print("=" * 60)

    # Import SAIKI modules
    try:
        from automation.engine import AutomationEngine
        from automation.scheduler import Scheduler
        from automation.policy import AutoRunPolicy
        from automation.triggers import Trigger
        from workflow.runner import WorkflowRunner
        from workflow.definitions import WorkflowDefinition
        from worker.rules import AutoRunConfig
        from worker.port_worker import PortWorker
        from worker.cpin_runtime import CpinRuntime, BetaStats
        from app.domain.enums import CpinState
        from app.domain.classifier import parse_cpin_response
        from app.infrastructure.serial.at_client import ATClient
    except ImportError as e:
        print(f"ERROR: Failed to import SAIKI modules: {e}")
        print("Make sure you're running from the SAIKI directory.")
        sys.exit(1)

    # Auto-detect port if not specified
    port = args.port
    if not port:
        import serial.tools.list_ports
        ports = list(serial.tools.list_ports.comports())
        if not ports:
            print("ERROR: No COM ports found. Connect a modem and try again.")
            sys.exit(1)
        port = ports[0].device
        print(f"Auto-detected port: {port}")

    # Create components
    auto_run_config = AutoRunConfig()
    auto_run_config.set_enabled(True)  # Enable auto-run for beta test

    scheduler = Scheduler(auto_run_config)
    policy = AutoRunPolicy()
    runner = WorkflowRunner(skill_map={}, cooldown_seconds=5.0)
    engine = AutomationEngine(scheduler, policy, runner)

    # Create a mock serial for the modem
    serial_mock = MagicMock()
    serial_mock.port_name = port
    serial_mock.is_open = True
    serial_mock.write.return_value = True

    # Create AT client
    at_client = ATClient(serial_mock)

    # Create CPIN runtime (constructor: port_id, at_client, event_bus)
    from worker.ui.event_bus import EventBus
    event_bus = EventBus()
    cpin = CpinRuntime(port_id=port, at_client=at_client, event_bus=event_bus)

    # Create port worker (constructor: port_id, event_bus, auto_run_config)
    worker = PortWorker(
        port_id=port,
        event_bus=event_bus,
        auto_run_config=auto_run_config,
    )

    # Wire up event handlers (same as SystemBootstrap._wire_events)
    def on_cpin_transition(payload):
        port_id = payload.get("port", port)
        state = payload.get("state", "UNKNOWN")
        logger.info("[BETA] cpin.transition port=%s state=%s", port_id, state)

    def on_modem_online(payload):
        port_id = payload.get("port", port)
        logger.info("[BETA] modem.online port=%s", port_id)

    def on_modem_offline(payload):
        port_id = payload.get("port", port)
        reason = payload.get("reason", "unknown")
        logger.info("[BETA] modem.offline port=%s reason=%s", port_id, reason)

    event_bus.subscribe("cpin.transition", on_cpin_transition)
    event_bus.subscribe("modem.online", on_modem_online)
    event_bus.subscribe("modem.offline", on_modem_offline)

    print("\n[BETA TEST] Starting modem lifecycle...")
    print("[BETA TEST] Press Ctrl+C to stop early.\n")

    start_time = time.time()
    last_report = start_time

    try:
        # Start CPIN runtime
        cpin.start()

        while True:
            elapsed = time.time() - start_time
            remaining = args.duration - elapsed

            if remaining <= 0:
                break

            # Print progress every 60 seconds
            if time.time() - last_report >= 60:
                stats = engine.get_delivery_stats()
                cpin_stats = cpin.beta_stats
                print(f"[BETA TEST] Elapsed: {int(elapsed)}s (remaining: {int(remaining)}s)")
                print(f"  Triggers: {stats.get('triggers_received', 0)}")
                print(f"  Workflows started: {stats.get('workflows_started', 0)}")
                print(f"  Workflows completed: {stats.get('workflows_completed', 0)}")
                print(f"  Workflows failed: {stats.get('workflows_failed', 0)}")
                print(f"  Commands sent: {stats.get('commands_sent', 0)}")
                print(f"  Responses received: {stats.get('responses_received', 0)}")
                print(f"  Timeouts: {stats.get('timeouts', 0)}")
                if cpin_stats:
                    print(f"  CPIN ready_count: {cpin_stats.ready_count}")
                    print(f"  CPIN not_ready_count: {cpin_stats.not_ready_count}")
                    print(f"  CPIN unknown_count: {cpin_stats.unknown_count}")
                    print(f"  CPIN poll_count: {cpin_stats.cpin_poll_count}")
                print()
                last_report = time.time()

            time.sleep(1.0)

    except KeyboardInterrupt:
        print("\n[BETA TEST] Interrupted by user.")

    finally:
        # Stop CPIN runtime
        cpin.stop()

        # Print final report
        print("\n" + "=" * 60)
        print("[BETA TEST] COMPLETE")
        print("=" * 60)

        # Delivery Report
        print("\n[DELIVERY REPORT]")
        print(engine.get_delivery_report())

        # BetaStats
        if cpin.beta_stats:
            stats = cpin.beta_stats
            print("\nBetaStats:")
            print(f"  ready_count: {stats.ready_count}")
            print(f"  not_ready_count: {stats.not_ready_count}")
            print(f"  unknown_count: {stats.unknown_count}")
            print(f"  ready_to_not_ready: {stats.ready_to_not_ready}")
            print(f"  not_ready_to_ready: {stats.not_ready_to_ready}")
            print(f"  confirmation_poll_triggered: {stats.confirmation_poll_triggered}")
            print(f"  confirmation_poll_prevented: {stats.confirmation_poll_prevented}")
            print(f"  buffer_flush_count: {stats.buffer_flush_count}")
            print(f"  cpin_poll_count: {stats.cpin_poll_count}")

        # Summary
        elapsed = time.time() - start_time
        print(f"\nTotal runtime: {elapsed:.1f}s ({elapsed / 60:.1f} min)")
        print(f"Log saved to: {args.output}")
        print("=" * 60)


if __name__ == "__main__":
    main()
