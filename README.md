# Garam Nias API (Python)

Backend untuk aplikasi mobile Garam Nias (admin & petugas). FastAPI + PyMongo + MongoDB Atlas.
Alamat API, data yang dikirim, dan pesan galatnya sama persis,
jadi aplikasi Flutter tidak perlu diubah.

## Struktur — mulai menelusuri dari sini

| File | Isi |
|---|---|
| `app/main.py` | Titik masuk: menyambung database, mendaftarkan rute, mengubah galat menjadi `{"pesan": ...}` |
| `app/config.py` | Semua pengaturan dari `.env` / Railway Variables |
| `app/db.py` | Koneksi MongoDB, pesan galat koneksi, bantuan angka/tanggal, transaction, nomor TRX/JU |
| `app/auth.py` | Token login (JWT) dan pengecekan pengguna yang masuk |
| `app/rute_auth.py` | `/api/auth/*` — nomor HP → kode WhatsApp → buat PIN / masuk PIN |
| `app/rute_transaksi.py` | `/api/master`, `/api/lampiran`, `/api/sync`, `/api/transaksi/saya` — dipakai HP petugas & admin |
| `app/rute_admin.py` | `/api/admin/*` — beranda, periksa (setujui/tolak), rincian per kategori, kelola pengguna |
| `app/jurnal.py` | Jurnal otomatis saat transaksi disetujui |
| `app/wa.py` | Kirim WhatsApp lewat Fonnte (tanpa token: hanya dicetak di log) |
| `app/umum.py` | Kelas `Galat` dan pengubah ObjectId/Decimal128/tanggal → JSON |
| `scripts/cek_koneksi.py` | Cek koneksi ke Atlas |
| `scripts/segarkan_demo.py` | Buat ulang data demo dengan tanggal terbaru (foto nota contoh di `scripts/demo_nota/`) |
| `database/garam_nias_demo_mobile.js` | Skema + data demo, dipasang dengan mongosh |
| `database/garam_nias_mongodb.js` | Skema kosong + data master untuk produksi |

Dokumentasi API otomatis (bisa dicoba langsung): `http://localhost:3000/docs`

## Menjalankan di laptop

```bash
cd garam-nias-backend          # folder hasil clone repo
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                     # lalu isi MONGODB_URI
python scripts/cek_koneksi.py
uvicorn app.main:app --reload --port 3000
```

## Database

Skema dipasang dengan `mongosh`, bukan oleh server:

```bash
# demo (skema + data dummy)
mongosh "mongodb+srv://USER:PASSWORD@cluster.xxxxx.mongodb.net/garam_nias" database/garam_nias_demo_mobile.js
# produksi (skema kosong + data master)
mongosh "mongodb+srv://USER:PASSWORD@cluster.xxxxx.mongodb.net/garam_nias" database/garam_nias_mongodb.js
```

Sebelum demo, segarkan tanggal data supaya beranda admin punya transaksi "hari ini":

```bash
python scripts/segarkan_demo.py
```

## Railway

1. Buat service dari repo GitHub ini (New → GitHub Repo). Root directory dibiarkan kosong.
2. Variables: isi seperti `.env.example` (`MONGODB_URI`, `MONGODB_DB`, `JWT_SECRET`, `APP_ENV=production`, `DEV_OTP`, `ADMIN_NO_HP`)
3. Perintah start sudah ada di `Procfile`.
4. Di Atlas → Network Access, izinkan `0.0.0.0/0` (IP Railway berubah-ubah).
