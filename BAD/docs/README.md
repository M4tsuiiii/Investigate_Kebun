# Kebun Reaktivasi — RC-1

Paket ini disiapkan untuk pengujian lapangan pada PC Windows lain. Salin dan ekstrak ZIP secara utuh; jangan memindahkan file dari dalam struktur paket.

## Prasyarat

- Windows dengan Python 3.10 atau lebih baru (3.11 atau 3.12 dianjurkan).
- Driver modem/port COM sudah terpasang.
- Akses internet bila fitur lookup Telegram akan digunakan.

## Instalasi

1. Ekstrak ZIP ke folder lokal, misalnya `C:\Kebun_Reaktivasi_RC-1`.
2. Buka Command Prompt di folder `app`.
3. Buat lingkungan Python terpisah (disarankan):

   ```bat
   python -m venv .venv
   .venv\Scripts\activate
   ```

4. Pasang dependensi:

   ```bat
   python -m pip install -r requirements.txt
   ```

5. Jalankan aplikasi:

   ```bat
   python "kebun_reaktivasi(rev).py"
   ```

## Aktivasi dan data lokal

- Saat aplikasi meminta aktivasi, catat Hardware ID PC field. Buat activation key pada PC admin dengan `app\license_generator.py`, lalu masukkan key tersebut ke aplikasi.
- `hasil_panen.db` dibuat otomatis oleh aplikasi pada PC field. Jangan menyalin database dari PC asal kecuali migrasi data memang telah disetujui.
- Login Telegram akan membuat sesi lokal `telegram_login.session` pada PC field. Jangan menyalin sesi dari PC asal.
- Log runtime (jika dibuat aplikasi) berada di `app\logs`.

## Uji opsional

Jalankan dari folder `tests`:

```bat
python -m unittest test_ussd_response.py -v
```

## Catatan dukungan

`docs\BUSINESS_RULES.md` adalah referensi workflow bisnis. Catat hasil pengujian, pesan galat, port COM yang dipakai, serta log terkait untuk setiap temuan field test.
