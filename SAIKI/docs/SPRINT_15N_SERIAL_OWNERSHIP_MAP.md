# Sprint 15N: Serial Ownership Map

## Serial Handle Lifecycle

### Owner Chain

```
SystemBootstrap._create_serial(port_id, baud_rate)
  → SerialAdapter(port_id, baud_rate, timeout=1.0)  [ONE instance]
    → adapter.open()                                  [OPENS]

WorkerManager._inject_dependencies(port_id, worker)
  → serial_factory(port_id, baud_rate)                [calls _create_serial]
  → at_client_factory(serial_adapter)                 [ATClient wraps SerialAdapter]
  → worker.connect(serial_adapter, at_client)         [passes both]

PortWorker.connect(serial_adapter, at_client)
  → self._serial = serial_adapter                     [STORES reference]
  → self._at_client = at_client                       [STORES reference]
  → self._cleanup = CleanupManager(serial_adapter)    [SAME adapter]
  → self._cpin_runtime = CpinRuntime(port_id, at_client, event_bus)  [ATClient]
  → self._ussd_runtime = UssdRuntime(port_id, at_client, event_bus)  [ATClient]

SystemBootstrap._wire_skills_for_worker(port_id, worker)
  → serial = getattr(worker, '_serial', None)         [REACH-IN to get adapter]
  → at_client = getattr(worker, '_at_client', None)   [REACH-IN to get ATClient]
  → ResetHardwareSkill(serial, at_client)             [SAME adapter]
```

### Ownership Table

| Class | Receives SerialAdapter From | Stores Reference | Calls Open | Calls Close | Calls Write | Calls Read |
|-------|---------------------------|-----------------|-----------|------------|------------|-----------|
| **SerialAdapter** | N/A (creates internally) | `self._serial` (pyserial) | `open()` line 66 | `close()` line 83 | `write()` line 104 | `read()` line 117, `readline()` line 127 |
| **ATClient** | Constructor arg | `self._serial` | No | No | `self._serial.write()` line 64,95 | `self._serial.readline()` line 134 |
| **PortWorker** | `connect()` arg | `self._serial`, `self._at_client` | No | `self._serial.close()` line 151 | Via ATClient | Via ATClient |
| **CpinRuntime** | Constructor arg (ATClient) | `self._at_client` | No | No | Via ATClient | Via ATClient |
| **CleanupManager** | Constructor arg | `self._modem` | No | No | `self._modem.send_at()` line 41 | `self._modem.reset_input_buffer()` line 52 |
| **ResetHardwareSkill** | Constructor arg | `self._serial`, `self._at_client` | `self._serial.open()` line 48 | `self._serial.close()` line 42 | Via ATClient | Via ATClient |
| **WorkerManager** | N/A (creates via factory) | `self._serial_factory`, `self._workers` | Via `_inject_dependencies` | Via `destroy_worker` → `worker.disconnect()` | No | No |
| **SystemBootstrap** | N/A (creates via factory) | `self._skill_map`, `self._workers` | Via `_create_serial` | No | No | No |

### SerialAdapter Lifecycle

```
CREATED:
  system_bootstrap.py _create_serial() line 170
  → SerialAdapter(port_id, baud_rate, timeout=1.0)
  → adapter.open()

OPENED:
  serial_adapter.py open() line 56-76
  → serial.Serial(port, baudrate, timeout, write_timeout)
  → self._is_open = True

SHARED (5+ consumers):
  port_worker.py connect() line 116-137
  → self._serial = serial_adapter
  → self._at_client = at_client (wraps serial_adapter)
  → self._cleanup = CleanupManager(serial_adapter)
  → self._cpin_runtime = CpinRuntime(port_id, at_client, event_bus)
  → self._ussd_runtime = UssdRuntime(port_id, at_client, event_bus)

  system_bootstrap.py _wire_skills_for_worker() line 185-206
  → serial = getattr(worker, '_serial', None)
  → ResetHardwareSkill(serial, at_client)

CLOSED (multiple callers):
  serial_adapter.py close() line 78-88
  → self._serial.close()
  → self._is_open = False
  → self._serial = None        ← ALL consumers see port_not_open

  port_worker.py disconnect() line 143-156
  → self._serial.close()

  skills/reset_hardware.py execute() line 42
  → self._serial.close()
  → time.sleep(wait_seconds)
  → self._serial.open()

  serial_adapter.py reconnect() line 149-156
  → self.close()
  → time.sleep(delay)
  → self.open()
```

### Single Adapter, Multiple Consumers

```
                    ┌─ PortWorker._serial
                    ├─ ATClient._serial
SerialAdapter ─────┼─ CleanupManager._modem
 (ONE instance)    ├─ ResetHardwareSkill._serial
                    ├─ CpinRuntime._at_client._serial  (via getattr reach-in)
                    └─ UssdRuntime._at_client._serial  (via ATClient)
```

### Critical Finding: Who Can Close the Port?

| Caller | File:Line | Triggers |
|--------|-----------|----------|
| `ResetHardwareSkill.execute()` | `skills/reset_hardware.py:42` | Workflow execution |
| `PortWorker.disconnect()` | `port_worker.py:151` | WorkerManager.destroy_worker(), stop_all() |
| `SerialAdapter.reconnect()` | `serial_adapter.py:152` | Connection failure recovery |
| `SerialAdapter.open()` (internal) | `serial_adapter.py:64` | Re-opening closes old handle first |

### Critical Finding: Who Can Reopen the Port?

| Caller | File:Line | Triggers |
|--------|-----------|----------|
| `ResetHardwareSkill.execute()` | `skills/reset_hardware.py:48` | After close + sleep |
| `SerialAdapter.reconnect()` | `serial_adapter.py:154` | After close + sleep |
| `SerialAdapter.open()` | `serial_adapter.py:56` | Fresh creation |
