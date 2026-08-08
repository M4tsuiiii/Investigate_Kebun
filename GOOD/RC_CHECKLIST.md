# RC-1 Field-Test Checklist

## Sebelum instalasi

- [ ] ZIP diekstrak utuh dan struktur `app`, `docs`, dan `tests` tetap ada.
- [ ] Python 3.10+ tersedia di PC target.
- [ ] Driver modem dan port COM telah dikenali Windows.
- [ ] Tidak ada `license.key`, `telegram_login.session`, atau `hasil_panen.db` dari PC asal yang ikut dipindahkan.

## Instalasi

- [ ] Virtual environment dibuat di `app\.venv` (disarankan).
- [ ] `python -m pip install -r requirements.txt` selesai tanpa error.
- [ ] Aplikasi dapat dijalankan dari folder `app`.
- [ ] Aktivasi menggunakan Hardware ID PC target berhasil.

## Smoke test

- [ ] Port modem terdeteksi dan dapat dibuka aplikasi.
- [ ] Cek Nomor menghasilkan respons yang sesuai dari perangkat/operator.
- [ ] Test USSD opsional lulus: `python -m unittest test_ussd_response.py -v`.
- [ ] Bila menggunakan Telegram, login ulang pada PC target berhasil.

## Alur lapangan

- [ ] Cek Nomor awal mencatat status baseline.
- [ ] Cek NIK / matching KK mengikuti aturan di `docs\BUSINESS_RULES.md`.
- [ ] Inject dan verifikasi dijalankan hanya pada nomor yang memenuhi syarat.
- [ ] Hasil akhir, pesan UI, dan data hasil panen direview.
- [ ] Log atau detail error dilampirkan untuk setiap kegagalan.

## Penutupan test

- [ ] Rekap nomor uji, hasil, perangkat/modem, dan versi Python dicatat.
- [ ] Database PC field dicadangkan hanya bila diminta untuk analisis.
- [ ] Lisensi dan sesi Telegram PC field tidak dibagikan di luar PC tersebut.
