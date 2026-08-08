# RC-1 Field-Test Checklist

## Sebelum instalasi

- [v] ZIP diekstrak utuh dan struktur `app`, `docs`, dan `tests` tetap ada.
- [v] Python 3.10+ tersedia di PC target.
- [v] Driver modem dan port COM telah dikenali Windows.
- [v] Tidak ada `license.key`, `telegram_login.session`, atau `hasil_panen.db` dari PC asal yang ikut dipindahkan.

## Instalasi

- [v] Virtual environment dibuat di `app\.venv` (disarankan).
- [v] `python -m pip install -r requirements.txt` selesai tanpa error.
- [v] Aplikasi dapat dijalankan dari folder `app`.
- [v] Aktivasi menggunakan Hardware ID PC target berhasil.

## Smoke test

- [v] Port modem terdeteksi dan dapat dibuka aplikasi.
- [v] Cek Nomor menghasilkan respons yang sesuai dari perangkat/operator.
- [x] Test USSD opsional lulus: `python -m unittest test_ussd_response.py -v`.
- [x] Bila menggunakan Telegram, login ulang pada PC target berhasil.

## Alur lapangan

- [v] Cek Nomor awal mencatat status baseline.
- [v] Cek NIK / matching KK mengikuti aturan di `docs\BUSINESS_RULES.md`.
- [v] Inject dan verifikasi dijalankan hanya pada nomor yang memenuhi syarat.
- [v] Hasil akhir, pesan UI, dan data hasil panen direview.
- [v] Log atau detail error dilampirkan untuk setiap kegagalan.

## Penutupan test

- [v] Rekap nomor uji, hasil, perangkat/modem, dan versi Python dicatat.
- [v] Database PC field dicadangkan hanya bila diminta untuk analisis.
- [v] Lisensi dan sesi Telegram PC field tidak dibagikan di luar PC tersebut.
