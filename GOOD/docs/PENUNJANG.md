## **COMMAND**

* CEK NOMOR: \*185\#  
  Ini fungsinya untuk mengambil nomor dan grace date. Status ditentukan dari command ini juga karena perlu mengambil tgl untuk dimasukkan ke dalam rumus “grace date-today=masa aktif”  
* CEK NIK: \*888\*4444\*1\#  
  Berfungsi untuk mengambil serial nik  
* REAKTIVASI INJECTION: \*888\*89\*1\*{nik}\*{kk}\#  
  Berfungsi untuk command reaktivasi


## **RAW RESPON**

* \*185\#   
  “Good Morning , Your number 08586xxxxxxx, Balance Rp.0 Active 24-08-2026 How can we assist you? ^ 1.Account ^ 2.Content ^ 3.IMPoin ^ 4.Help ^ 5.IMEI ^ 6.DND ^ 7.Chat Us”

   (ada juga yang berbahasa Indonesia)

* \*888\*4444\*1\#  
  “Nomor IM3 kamu telah terdaftar dengan ^ NIK : 31750554xxxxxxxx”  
* \*888\*89\*1\*{nik}\*{kk}\#  
  * Kartu Hangus:   
    “Permintaan kamu sedang di proses, cek SMS untuk mengetahui status permintaan kamu”  
  * Kartu Tenggang:  
    “Nomor 08575xxxxxxx sedang dalam masa tenggang. SEGERA lalukan isi ulang/ beli paket agar nomor tetap AKTIF dan bisa menikmati layanan IM3”  
  * Kartu Aktif:  
    “Layanan Hanya Dapat Dilakukan Hanya Pada Kartu Hanggus”  
* Bot tele  
  * Pencarian data tunggal:   
    * Data tidak ditemukan:  
      NIK 352104xxxxxxxxxx  
      \-\> TIDAK DITEMUKAN  
      Baris kedua muncul respon berupa “TIDAK DITEMUKAN”  
    * Data ditemukan:  
      NIK: 640412xxxxxxxxxx  
      KK: 640412xxxxxxxxxx (terbit: 13/07/2007)  
      Baris kedua terdapat respon yang berisi serial angka  
  * Pencarian data massal:  
    * Bot akan memproses terlebih dahulu yang kemudian akan muncul file berupa XLSX yang siap di-*download.* Kemudian setelah itu buka filenya dan extract file dan sesuaikan pasangan nik kk nya  
    * Catatan: ini masih berupa wacana. Masukkan ke dalam docs future dulu

## **WORKFLOW**

* FULL REACTIVATION  
  Nanti tolong buatkan diagramnya. Alurnya begini:  
  Cek nomor(mengambil nomor, grace date, serta cek status sim) \> cek nik \> match kk \> reactivation \> success validation   
* REACTIVATION  
  Sending reactivation command \> cek nomor dan status sebagai validator sukses tidaknya


## **REACTIVATION**

Dinyatakan:

* Sukses: jika ada perubahan grace date setelah melakukan reaktivasi  
* Gagal: jika tidak ada perubahan grace date

## **OTHER FITUR**

* **Restart modem**  
  Scanning ulang, ya seperti saat startup awal. Hanya itu, tanpa lanjut auto run. Ini untuk port COM modem yang sudah tervalidasi dan terbentuk workernya. Fitur ini ada 2 jenis, massal dan tunggal. Aku lupa AT command-nya  
* **Cek data lokal**  
  Berguna untuk cek data nik kk pada SIM yang terkena bypass, barangkali user ingin memastikan datanya. Ini cukup pada fitur tunggal di context menu.  
* **Ambil kk tele**  
  Ini untuk mengirim query manual ke telegram secara tunggal. Ini juga ada di context menu

## **ERROR**

* Try again  
  Terkadang ada beberapa SIM sedang sibuk jadi muncul jawaban error seperti ini  
* Telegram timeout  
  Bot merespon dengan jawaban yang tidak semestinya. Sebenarnya query telegram memiliki batas timeout tersendiri setelah mengirim query.