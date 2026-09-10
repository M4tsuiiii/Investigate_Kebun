# Future Ideas

## F-01: Connection Pool

**Idea**: Pool serial port connections instead of one-per-worker.
**Benefit**: Faster reconnection, reduced resource usage.
**Priority**: Low (current approach works).

## F-02: Health Watchdog

**Idea**: Periodic health check for each worker thread.
**Benefit**: Detect hung workers, auto-restart.
**Priority**: Medium (currently daemon threads die with main process).

## F-03: Persistent Settings

**Idea**: Save/load settings from JSON file.
**Benefit**: Settings survive restarts.
**Priority**: High (currently in-memory only).

## F-04: Structured Logging

**Idea**: Use `structlog` or `loguru` instead of rotating file handlers.
**Benefit**: Better log analysis, JSON output.
**Priority**: Low (current logging works).

## F-05: Async USSD

**Idea**: Use `asyncio` for USSD session management.
**Benefit**: Better concurrency, non-blocking reads.
**Priority**: Low (current threaded approach works).

## F-06: Plugin Architecture

**Idea**: Allow custom card status handlers via plugins.
**Benefit**: Extensibility for new carrier behaviors.
**Priority**: Low (premature optimization).

## F-07: Web Dashboard

**Idea**: Optional web UI alongside tkinter.
**Benefit**: Remote monitoring.
**Priority**: Low (out of scope).

## F-08: Database Migration

**Idea**: Use SQLAlchemy or SQLite migrations.
**Benefit**: Schema versioning, easier upgrades.
**Priority**: Medium (currently raw SQL).

## F-09: Configuration Validation

**Idea**: Pydantic models for all config values.
**Benefit**: Early error detection, type safety.
**Priority**: High (prevents magic value errors).

## F-10: Metrics Collection

**Idea**: Track reactivation success rates, timing, error distribution.
**Benefit**: Operational visibility.
**Priority**: Medium (useful for debugging).
