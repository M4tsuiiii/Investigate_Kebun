# PHONE CACHE FLOW

Analisis lengkap phone cache: GOOD flow, SAIKI current flow, dan recommended future flow.

---

## 1. GOOD Flow

### 1.1 Structure

```python
phone_cache = {
    "081234567890": {
        "nomor": "081234567890",
        "nik": "3276015001900001",
        "kk": "3276015001900002",
    }
}
```

### 1.2 Cache Lookup Flow

```
execute_full_flow()
  │
  ├── CEK NOMOR (*185#) → extract nomor
  │
  ├── CHECK CACHE: phone_cache[nomor]
  │     │
  │     ├── CACHE HIT
  │     │     ├── nik = phone_cache[nomor]["nik"]
  │     │     ├── kk = phone_cache[nomor]["kk"]
  │     │     └── SKIP NIK/KK LOOKUP → proceed to INJECT
  │     │
  │     └── CACHE MISS
  │           ├── CEK NIK (*888*4444*1#) → extract NIK
  │           │     │
  │           │     ├── FAIL → GAGAL_CEK_NIK
  │           │     │
  │           │     └── SUCCESS
  │           │           ├── SAVE to cache: phone_cache[nomor]["nik"] = NIK
  │           │           │
  │           │           └── CEK KK
  │           │                 │
  │           │                 ├── NIK&NIK MODE → KK = NIK
  │           │                 │
  │           │                 ├── LOCAL DB: db_cache[nik] → KK
  │           │                 │
  │           │                 ├── TELEGRAM: mock_telegram_gateway_query(nik)
  │           │                 │     └── HR-012: selalu return "DATA_TIDAK_DITEMUKAN"
  │           │                 │
  │           │                 └── FAIL → GAGAL_KK
  │           │
  │           └── SAVE to cache: phone_cache[nomor]["kk"] = KK
  │
  ├── INJECT (*888*89*1*NIK*KK#)
  │
  └── VERIFY (*185#)
```

### 1.3 Cache Behavior

- **Write timing**: Setelah NIK/KK berhasil diambil via USSD
- **Read timing**: Sebelum NIK/KK lookup
- **Lifetime**: In-memory saja, hilang saat aplikasi restart
- **Thread safety**: Tidak ada locking (potential race condition)
- **Size limit**: Tidak ada batasan

---

## 2. SAIKI Current Flow

### 2.1 Current State

```
SAIKI TIDAK MEMILIKI PHONE CACHE
```

### 2.2 Current Execution

```
reactivate_full workflow
  │
  ├── STEP 1: cek_nomor (*185#) → extract nomor
  │     → SkillResult.data = {"number": "081234567890"}
  │     → PortWorkerState.nomor = "081234567890"
  │
  ├── STEP 2: cek_status (AT+CPIN?) → READY
  │     → SkillResult.data = {"cpin_state": "READY"}
  │
  ├── STEP 3: cek_nik (*185#) → raw response
  │     → SkillResult.data = {"raw_response": "...", "has_payload": True}
  │     → NOMOR/NIK/KK columns TIDAK UPDATE (GAP-004)
  │
  ├── STEP 4: cek_kk (*185#) → raw response
  │     → SkillResult.data = {"raw_response": "...", "has_payload": True}
  │
  ├── STEP 5: inject_reaktivasi (*185#) → response
  │     → SkillResult.data = {"raw_response": "...", "injected": True}
  │
  └── STEP 6: verify_grace (*185#) → classify status
        → SkillResult.data = {"card_status": "AKTIF", "grace_date": "12/12/2026"}
```

### 2.3 Problems

1. **Setiap run mengirim 6 USSD calls** — tidak ada cache
2. **NIK/KK tidak di-extract** dari raw response — hanya return raw
3. **Tidak ada NIK source priority** — selalu USSD
4. **Tidak ada KK source priority** — selalu USSD
5. **Tidak ada local DB lookup**
6. **Tidak ada format mode** (NIK&NIK vs NIK&KK)

---

## 3. Recommended Future Flow

### 3.1 Cache Structure

```python
# In-memory cache (dict)
phone_cache: Dict[str, PhoneCacheEntry] = {}

@dataclass
class PhoneCacheEntry:
    nomor: str
    nik: str = ""
    kk: str = ""
    last_updated: float = 0.0
    source: str = ""  # "ussd", "db", "telegram"
```

### 3.2 Cache Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    REACTIVATION FLOW                         │
└─────────────────────────────────────────────────────────────┘

STEP 1: CEK NOMOR
  AT+CNUM → parse MSISDN → "081234567890"
  │
  ├── Save to context: context.nomor = "081234567890"
  └── Save to PortWorkerState: state.nomor = "081234567890"

STEP 2: CEK STATUS
  AT+CPIN? → "READY"
  │
  └── Save to context: context.status_awal = "READY"

STEP 3: CHECK CACHE
  phone_cache.get("081234567890")
  │
  ├── ┌─────────────────────────────────────────┐
  │   │           CACHE HIT                      │
  │   │                                           │
  │   │  nik = entry.nik                          │
  │   │  kk = entry.kk                            │
  │   │                                           │
  │   │  ┌─────────────────────────────────┐      │
  │   │  │     BYPASS FLAGS CHECK           │      │
  │   │  │                                   │      │
  │   │  │  IF abai_aktif=True AND           │      │
  │   │  │     card_status=AKTIF:            │      │
  │   │  │     → DONE + require_card_cycle   │      │
  │   │  │                                   │      │
  │   │  │  IF abai_tenggang=True AND        │      │
  │   │  │     card_status=TENGGANG:         │      │
  │   │  │     → DONE + require_card_cycle   │      │
  │   │  │                                   │      │
  │   │  │  ELSE → proceed to INJECT         │      │
  │   │  └─────────────────────────────────┘      │
  │   └─────────────────────────────────────────┘
  │
  └── ┌─────────────────────────────────────────┐
      │           CACHE MISS                     │
      │                                           │
      │  CEK NIK (*888*4444*1#)                   │
      │  │                                        │
      │  ├── FAIL → GAGAL_CEK_NIK                 │
      │  │                                        │
      │  └── SUCCESS → extract NIK                │
      │        │                                  │
      │        ├── Validate: re.fullmatch(\d{16}) │
      │        │                                  │
      │        ├── SAVE to cache:                 │
      │        │   phone_cache[nomor]["nik"] = NIK │
      │        │                                  │
      │        └── CEK KK                         │
      │              │                            │
      │              ├── FORMAT MODE CHECK        │
      │              │   IF "NIK & NIK":          │
      │              │     kk = nik               │
      │              │     → SKIP LOOKUP          │
      │              │                            │
      │              ├── LOCAL DB CHECK           │
      │              │   db_cache.get(nik)        │
      │              │   IF found: kk = result    │
      │              │                            │
      │              ├── TELEGRAM CHECK (future)  │
      │              │   telegram.query(nik)      │
      │              │   IF found: kk = result    │
      │              │                            │
      │              └── FAIL → GAGAL_KK          │
      │                                           │
      │  SAVE to cache:                           │
      │  phone_cache[nomor]["kk"] = KK             │
      └─────────────────────────────────────────┘

STEP 4: INJECT
  *888*89*1*{NIK}*{KK}#
  │
  └── Evaluate provisional success

STEP 5: VERIFY (15s delay)
  *185# → classify card status → extract grace date
  │
  └── Evaluate business outcome
```

### 3.3 Cache Integration Points

| Integration Point | Location | Description |
|-------------------|----------|-------------|
| Cache lookup | Before NIK skill | Check if nomor already cached |
| Cache write (NIK) | After NIK skill success | Save NIK to cache |
| Cache write (KK) | After KK skill success | Save KK to cache |
| Cache hit bypass | In workflow policy | Skip NIK/KK skills if cached |
| Bypass flag check | After cache hit | Check abai_aktif/abai_tenggang |
| Format mode | In KK lookup | NIK&NIK mode → KK=NIK |
| Local DB lookup | Before Telegram | Check panen_raya table |

### 3.4 New Skills Needed

| Skill | Purpose | Command |
|-------|---------|---------|
| `cek_limit` | Cek pulsa/quota | USSD configurable |
| `lookup_nik_db` | Cek NIK dari local DB | SQLite query |
| `lookup_kk_db` | Cek KK dari local DB | SQLite query |

### 3.5 Cache Invalidation

- **TTL**: Cache tidak expire (in-memory only)
- **Restart**: Cache hilang saat aplikasi restart
- **Manual**: User bisa clear cache via settings (future)
- **USB unplug**: Cache tetap ada (port-specific)

---

## 4. Cache Benefits

| Benefit | Impact |
|---------|--------|
| Reduce USSD charges | NIK/KK lookup hanya sekali per nomor |
| Faster reactivation | Cache hit skip 2 USSD calls (~8s) |
| Better UX | Respons lebih cepat untuk nomor yang sudah di-cache |
| Offline capability | Cache bisa digunakan tanpa modem (view only) |

---

## 5. Cache Risks

| Risk | Mitigation |
|------|------------|
| Stale data | Cache TTL atau manual invalidation |
| Memory usage | Limit cache size (e.g., 10000 entries) |
| Thread safety | Use threading.Lock for cache access |
| Data consistency | Cache is secondary to live USSD data |
