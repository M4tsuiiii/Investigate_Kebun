# Business Rules — Reaktivasi Kartu

Dokumen ini adalah acuan untuk workflow, evaluator, dan perubahan transport USSD.

## Workflow resmi

```text
CEK NOMOR (snapshot_before)
→ PHONE CACHE
→ CEK NIK (hanya jika cache tidak ada)
→ MATCHING KK
→ INJECT
→ CEK NOMOR (snapshot_after)
→ EVALUASI
```

Snapshot cek nomor memuat nomor, Grace Date, dan respons mentah. Kedua cek nomor adalah pemeriksaan status; yang pertama adalah baseline, yang kedua adalah verifikasi.

## Istilah

- **Grace Date**: tanggal akhir masa tenggang yang diambil dari Cek Nomor; data mentah dari operator.
- **Status Kartu**: hasil evaluasi aplikasi atas Grace Date dan respons operator: `AKTIF`, `TENGGANG`, atau `HANGUS`.
- **Inject**: pengiriman perintah reaktivasi. Ini hanya membuktikan request terkirim, bukan reaktivasi berhasil.
- **Verifikasi**: Cek Nomor setelah inject.
- **Phone Cache**: peta nomor → NIK → KK untuk menghindari cek NIK berulang; bukan penentu status kartu.

## Keputusan akhir

| Hasil | Kondisi |
| --- | --- |
| `SUKSES` | Grace Date hasil verifikasi berubah dari snapshot sebelum inject. |
| `TENGGANG` | Respons verifikasi menyatakan kartu masih dalam masa tenggang. |
| `GAGAL` | Grace Date tidak berubah dan hasilnya bukan tenggang. |

Serial error, timeout, atau CME/CMS error berarti request tidak terkirim dan tidak boleh diperlakukan sebagai sukses reaktivasi.

## Invarian B2 — isolasi sesi USSD

- Satu request memiliki satu lifecycle dan pemilik respons.
- Sebelum dial berikutnya, aplikasi membatalkan konteks USSD sebelumnya dan membuang data serial hingga mencapai periode hening.
- Respons yang dibuang selama batas sesi dicatat sebagai `USSD_SESSION_FENCE` dan tidak boleh diteruskan ke parser/workflow.
- Retry tidak boleh membuat inject ganda tanpa keputusan workflow yang eksplisit.
- UI/database menerima hasil evaluator bisnis, bukan kesimpulan langsung dari respons inject.

## Audit terbuka

- Fungsi bisnis timestamp Panen Raya perlu diputuskan: anti-duplikasi, TTL cache, statistik, atau audit log.
- Uji perangkat nyata perlu memeriksa `USSD_SESSION_FENCE` pada respons operator yang terlambat dan memastikan tidak ada pencampuran respons antar-dial.
