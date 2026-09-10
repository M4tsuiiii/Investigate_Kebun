"""SAIKI — Kebun Reaktivasi Massal v3.0

Runtime wiring (Sprint 10A):
- WorkerManager scans COM ports
- PortWorkers created with hardware dependencies
- Skills wired to hardware
- Workflows registered
- Automation engine ready

Usage:
    python main.py
"""

import sys
import os
import signal
import time
import logging
import threading

# Add app/ to path for domain imports
SAIKI_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SAIKI_ROOT, "app"))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("saiki")

from worker.system_bootstrap import SystemBootstrap
from worker.modem_monitor import ModemMonitor
from worker.ui.events import CommandEvent, UIEvent
from automation.triggers import Trigger


def print_banner():
    print("=" * 60)
    print("  SAIKI — Kebun Reaktivasi Massal v3.0")
    print("  Architecture: Modular, Event-Driven, Thread-Safe")
    print("=" * 60)
    print()


def print_status(bootstrap):
    engine = bootstrap.automation_engine
    wm = bootstrap.worker_manager

    workers = wm.workers
    port_states = wm.get_all_port_states()
    queue_size = engine.get_queue_size()
    running = engine.get_running_count()
    auto_run = bootstrap.auto_run_config.auto_run_enabled

    active_count = sum(1 for s in port_states.values() if s.value == "ACTIVE")
    excluded_count = sum(1 for s in port_states.values() if s.value == "EXCLUDED")

    print(f"\n--- Status ---")
    print(f"  Ports: {len(workers)} (active={active_count}, excluded={excluded_count})")
    for port_id, worker in workers.items():
        state = port_states.get(port_id)
        state_str = state.value if state else "?"
        hw = "ONLINE" if worker.modem_online else "OFFLINE"
        print(f"    {port_id}: {hw} [{state_str}] (alive={worker.is_alive})")
    print(f"  Queue: {queue_size} pending, {running} running")
    print(f"  Auto Run: {'ON' if auto_run else 'OFF'}")
    print(f"  Mode: {engine.mode.value}")
    print(f"  Results: {len(engine.get_results())}")
    skills = list(bootstrap._skill_map.keys())
    print(f"  Skills: {', '.join(skills) if skills else 'NONE'}")
    print()


def print_help():
    print("\n--- Commands ---")
    print("  status              - Show system status")
    print("  auto on/off         - Toggle auto-run")
    print("  check               - Mass check number")
    print("  reactivate          - Mass reactivation")
    print("  restart <port>      - Restart hardware on port")
    print("  reset <port>        - Reset hardware on port")
    print("  exclude <port>      - Exclude port from automation")
    print("  include <port>      - Include port back into automation")
    print("  mode <name>         - Set mode (CHECK_DATA/REACTIVATE_FAST/REACTIVATE_FULL)")
    print("  list                - List registered workflows")
    print("  scan                - Force COM rescan")
    print("  help                - Show this help")
    print("  quit                - Exit")
    print()


def main():
    print_banner()

    # Initialize and start system
    logger.info("[BOOT] Initializing system...")
    bootstrap = SystemBootstrap()

    # Start everything (scanning, automation, validation)
    bootstrap.start()

    # Start modem monitor for online/offline detection of registered workers
    modem_monitor = ModemMonitor(bootstrap.event_bus, check_interval=3.0)

    # Register existing workers with modem monitor
    for port_id, worker in bootstrap.worker_manager.workers.items():
        at_client = getattr(worker, '_at_client', None)
        if at_client:
            modem_monitor.register_modem(port_id, at_client)

    modem_monitor.start()
    logger.info("[BOOT] ModemMonitor started")

    # Subscribe to new worker creation to register with modem monitor
    def on_port_discovered(payload):
        port = payload.get("port")
        if port:
            worker = bootstrap.worker_manager.get_worker(port)
            if worker:
                at_client = getattr(worker, '_at_client', None)
                if at_client:
                    modem_monitor.register_modem(port, at_client)
                    logger.info("[MONITOR] Registered %s with ModemMonitor", port)

    bootstrap.event_bus.subscribe("ui.port.discovered", on_port_discovered)

    # Event listeners for realtime display
    def on_port_update(payload):
        port = payload.get("port", "?")
        status = payload.get("status", "?")
        detail = payload.get("detail", "")
        print(f"  [{port}] {status} — {detail}")

    def on_auto_run_changed(payload):
        enabled = payload.get("enabled", False)
        print(f"  Auto Run: {'ON' if enabled else 'OFF'}")

    def on_automation_started(payload):
        port = payload.get("port", "?")
        workflow = payload.get("workflow", "?")
        print(f"  [{port}] Workflow started: {workflow}")

    def on_automation_completed(payload):
        port = payload.get("port", "?")
        workflow = payload.get("workflow", "?")
        duration = payload.get("duration", 0)
        print(f"  [{port}] Workflow completed: {workflow} ({duration:.1f}s)")

    def on_automation_failed(payload):
        port = payload.get("port", "?")
        workflow = payload.get("workflow", "?")
        error = payload.get("error", "")
        print(f"  [{port}] Workflow FAILED: {workflow} — {error}")

    bootstrap.event_bus.subscribe("ui.port.update", on_port_update)
    bootstrap.event_bus.subscribe(UIEvent.AUTO_RUN_CHANGED.value, on_auto_run_changed)
    bootstrap.event_bus.subscribe("automation.started", on_automation_started)
    bootstrap.event_bus.subscribe("automation.completed", on_automation_completed)
    bootstrap.event_bus.subscribe("automation.failed", on_automation_failed)

    # Signal handler
    def shutdown(signum, frame):
        print("\n[SHUTDOWN] Stopping...")
        modem_monitor.stop()
        bootstrap.stop()
        print("[SHUTDOWN] Done.")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Main command loop
    try:
        while True:
            try:
                cmd = input("saiki> ").strip()
            except EOFError:
                break

            if not cmd:
                continue

            parts = cmd.split()
            action = parts[0].lower()

            if action == "quit" or action == "exit":
                break
            elif action == "help":
                print_help()
            elif action == "status":
                print_status(bootstrap)
            elif action == "auto":
                if len(parts) > 1:
                    if parts[1].lower() == "on":
                        bootstrap.auto_run_config.set_enabled(True)
                        print("  Auto Run: ON")
                    elif parts[1].lower() == "off":
                        bootstrap.auto_run_config.set_enabled(False)
                        print("  Auto Run: OFF")
                    else:
                        print("  Usage: auto on|off")
                else:
                    bootstrap.auto_run_config.toggle()
                    state = "ON" if bootstrap.auto_run_config.auto_run_enabled else "OFF"
                    print(f"  Auto Run toggled: {state}")
            elif action == "check":
                print("  Starting mass check...")
                bootstrap.event_bus.publish(CommandEvent.MASS_CEK_NOMOR.value, {})
            elif action == "reactivate":
                print("  Starting mass reactivation...")
                bootstrap.event_bus.publish(CommandEvent.MASS_REAKTIVASI.value, {})
            elif action == "restart":
                if len(parts) > 1:
                    port = parts[1]
                    print(f"  Restarting {port}...")
                    bootstrap.event_bus.publish(CommandEvent.RESET_MODEM.value, {"port": port})
                else:
                    print("  Usage: restart <port>")
            elif action == "reset":
                if len(parts) > 1:
                    port = parts[1]
                    print(f"  Resetting {port}...")
                    bootstrap.automation_engine.enqueue_workflow(port, "hardware_reset", priority=1)
                else:
                    print("  Usage: reset <port>")
            elif action == "exclude":
                if len(parts) > 1:
                    port = parts[1]
                    if bootstrap.worker_manager.exclude_port(port):
                        print(f"  {port}: EXCLUDED from automation")
                    else:
                        print(f"  {port}: cannot exclude (not ACTIVE)")
                else:
                    print("  Usage: exclude <port>")
            elif action == "include":
                if len(parts) > 1:
                    port = parts[1]
                    if bootstrap.worker_manager.include_port(port):
                        print(f"  {port}: ACTIVE in automation")
                    else:
                        print(f"  {port}: cannot include (not EXCLUDED)")
                else:
                    print("  Usage: include <port>")
            elif action == "mode":
                if len(parts) > 1:
                    mode_name = parts[1].upper()
                    bootstrap.automation_engine.set_mode_from_name(mode_name)
                    print(f"  Mode: {bootstrap.automation_engine.mode.value}")
                else:
                    print(f"  Current mode: {bootstrap.automation_engine.mode.value}")
            elif action == "list":
                workflows = bootstrap.workflow_registry.list_workflows()
                print(f"  Registered workflows: {', '.join(workflows)}")
            elif action == "scan":
                print("  Forcing COM rescan...")
                bootstrap.worker_manager._scan_and_update()
                print_status(bootstrap)
            else:
                print(f"  Unknown command: {action}. Type 'help' for commands.")

    except KeyboardInterrupt:
        pass
    finally:
        print("\n[SHUTDOWN] Stopping...")
        modem_monitor.stop()
        bootstrap.stop()
        print("[SHUTDOWN] Done.")


if __name__ == "__main__":
    main()
