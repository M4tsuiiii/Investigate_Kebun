# SENGKUNI — Modem Robustness Implementation Report

## Ringkasan

Implementasi 5 fase perbaikan untuk memastikan monitoring kinerja modem berfungsi dengan benar, mencegah false positive SIM detection, dan menangani stuck processes. **125/125 tests passing**.

---

## Phase 1: Buffer Safety

### `app/infrastructure/serial/at_client.py`

| Perubahan | Sebelum | Sesudah |
|-----------|---------|---------|
| `flush_first` parameter | Optional (default False) | **Dihapus** — flush SELALU dilakukan |
| Drain loop | Tidak ada | **20ms settling + read semua bytes sisa** |
| USSD flush | Tidak ada | **Selalu flush sebelum `send_ussd()`** |
| Echo filtering | Tidak ada | **Skip echo command + URC (+CREG, +CSQ, +WIND)** |
| USSD termination | Break saat `+CUSD:` ditemukan | **Baca sampai closing quote `",15` atau `OK`** |

**Impact**: Stale data dari CPIN poll tidak akan terbaca sebagai bagian dari USSD response, dan sebaliknya.

---

## Phase 2: False Positive Prevention

### `app/domain/classifier.py` — Parser Rewrite

| Perubahan | Sebelum | Sesudah |
|-----------|---------|---------|
| NOT_READY check | Setelah READY | **SEBELUM READY** (anti substring collision) |
| READY validation | Substring `"READY" in response` | **Regex `\+CPIN:\s*READY`** (wajib ada prefix) |
| +CME ERROR | Fallback ke NOT_READY | **Semua → NOT_INSERTED** |
| Fallback | `NOT_READY` | **`UNKNOWN`** (tidak asumsi tanpa sinyal eksplisit) |

### `worker/cpin_runtime.py` — READY Confirmation

| Perubahan | Sebelum | Sesudah |
|-----------|---------|---------|
| Any → READY | Langsung diterima | **Perlu 2x konfirmasi berturut-turut** |
| Double event | Publish di cpin_runtime + port_worker | **Hanya di port_worker** |
| Timestamp tracking | Tidak ada | **`last_poll_time`, `last_state_change_time`** |

### `worker/port_worker.py` — Auto-run Gate

| Perubahan | Sebelum | Sesudah |
|-----------|---------|---------|
| Auto-run trigger | 1x READY → langsung trigger | **READY + fresh poll (<5s) + rules check** |
| Stale poll check | Tidak ada | **Skip auto-run jika CPIN poll >5 detik lalu** |

---

## Phase 3: Race Condition & Session Safety

### `worker/ussd_runtime.py` — Session Management

| Perubahan | Sebelum | Sesudah |
|-----------|---------|---------|
| Fence acquire | Return value diabaikan | **Cek return, jika False → cancel + retry** |
| Stale session close | Tidak ada | **AT+CUSD=2 sebelum setiap dial** (M26 firmware fix) |
| Fence busy handling | Skip silently | **Cancel → wait 0.5s → retry → skip if still busy** |

### `worker/port_worker.py` — Stop Ordering

| Perubahan | Sebelum | Sesudah |
|-----------|---------|---------|
| Stop order | CPIN → Serial → Worker | **Worker → CPIN → Serial** (benar) |
| Worker join | Setelah serial close | **Sebelum serial close** (mencegah orphan thread) |

### `worker/port_worker.py` — Health Watchdog

| Perubahan | Sebelum | Sesudah |
|-----------|---------|---------|
| Health monitoring | Tidak ada | **30s interval, 60s stale threshold** |
| Health event | Tidak ada | **`port.worker.health` + `port.worker.stale` events** |
| Activity tracking | Tidak ada | **`_last_activity_time` update setiap poll/skill** |

---

## Phase 4: USSD Flow Fix

### `worker/parser_registry.py` — Payload Extraction

| Perubahan | Sebelum | Sesudah |
|-----------|---------|---------|
| Number extraction | Regex langsung di raw response | **Extract payload dari `+CUSD: N,"..."` dulu** |
| Grace date | Regex di raw response | **Extract payload dulu** |
| NIK extraction | Regex di raw response | **Extract payload dulu** |
| KK extraction | Regex di raw response | **Extract payload dulu** |
| Injection classify | String match di raw | **Extract payload dulu** |

**Pattern**: `_PAYLOAD_PATTERN = r'\+CUSD:\s*\d+,"(.*)"'` (re.DOTALL) — mirip GOOD.

---

## Phase 5: Monitoring & Observability

### `worker/ui/controller.py` — Health Event Handling

| Event | Handler | Effect |
|-------|---------|--------|
| `port.worker.health` | `_on_worker_health()` | Update UI status + respon |
| `port.worker.stale` | `_on_worker_stale()` | Log warning + UI warning status |

### `worker/port_worker.py` — Health Event Publishing

| Event | Interval | Data |
|-------|----------|------|
| `port.worker.health` | 30 detik | cpin_state, uptime, modem_online, restart_count |
| `port.worker.stale` | Saat stale terdeteksi | port, stale_seconds |

---

## Files Modified

| File | Perubahan Utama |
|------|-----------------|
| `app/infrastructure/serial/at_client.py` | Universal flush, drain loop, echo filtering, USSD reader fix |
| `app/domain/classifier.py` | Anti-false-positive CPIN parser |
| `worker/cpin_runtime.py` | READY confirmation threshold, timestamp tracking |
| `worker/port_worker.py` | Auto-run gate, stop ordering, health watchdog |
| `worker/ussd_runtime.py` | Session fence check, AT+CUSD=2 before dial |
| `worker/parser_registry.py` | Payload extraction for all parsers |
| `worker/ui/controller.py` | Health event handlers |

## Test Updates

| File | Perubahan |
|------|-----------|
| `tests/test_domain.py` | Updated for new classifier behavior + 5 new anti-false-positive tests |
| `tests/test_runtimes.py` | Updated for READY confirmation threshold |

---

## Test Results

```
125 passed in 40.59s
```

---

## Monitoring Checklist

| Item | Status |
|------|--------|
| Buffer flush sebelum setiap AT command | ✅ |
| Drain loop setelah flush | ✅ |
| Tidak ada stale data contamination | ✅ |
| READY memerlukan 2x konfirmasi | ✅ |
| Auto-run gate dengan freshness check | ✅ |
| Session fence berfungsi | ✅ |
| AT+CUSD=2 sebelum setiap dial | ✅ |
| Worker stop ordering benar | ✅ |
| Health watchdog aktif | ✅ |
| Health events ke UI | ✅ |
| USSD payload extraction | ✅ |
| Parser semua extract payload dulu | ✅ |

---

## Catatan untuk Hardware Test

1. **CPIN False Positive**: Test dengan modem tanpa SIM — pastikan tidak ada false READY
2. **USSD Response**: Test `cek_nomor` dengan SIM aktif — pastikan nomor ter-extract dengan benar
3. **Stuck Recovery**: Test dengan disconnect modem saat USSD running — pastikan health watchdog mendeteksi
4. **Session Collision**: Test rapid USSD dials — pastikan session fence berfungsi
