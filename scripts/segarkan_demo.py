"""Segarkan data DEMO dengan tanggal terbaru (±3 bulan sampai hari ini).

Dipakai tepat sebelum demo, supaya beranda admin punya transaksi "hari ini".
Skema (validator, indeks, view) dan data master (akun, akun kas, kategori & tag)
TIDAK diubah; yang dibuat ulang hanya pengguna demo dan data transaksi.

Syarat: database sudah dipasang dengan database/garam_nias_demo_mobile.js
        (atau garam_nias_mongodb.js).

    python scripts/segarkan_demo.py

Menolak jalan bila database berisi transaksi yang bukan data demo.
"""
import logging
import random
import sys
import uuid as _uuid
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bcrypt  # noqa: E402
from bson import ObjectId  # noqa: E402
from gridfs import GridFSBucket  # noqa: E402

from app import config  # noqa: E402
from app.db import WIB, D, db, kini, sambung  # noqa: E402

acak = random.Random(20261103)
JAM = timedelta(hours=1)
HARI = timedelta(days=1)
FOLDER_NOTA = Path(__file__).resolve().parent / "demo_nota"
NILAI_NOTA = {"krosok": 5150000, "kio3": 1150000, "plastik": 2400000, "karung": 1100000,
              "bbm": 614000, "kapal": 1450000, "terpal": 1240000, "jual": 3550000}
PERAN_ADMIN = ("pemilik", "admin", "keuangan")
DIKOSONGKAN = ["pengguna", "kode_otp", "sesi", "kiriman_petugas", "transaksi", "periode", "jurnal", "notifikasi_wa",
               "log_audit", "penghitung", "lampiran.files", "lampiran.chunks"]
PELANGGAN = ["Warung Ina Dewi – Hiliweto", "Toko Faebua – Gunungsitoli", "Reseller Ama Yuni – Teluk Dalam",
             "Kios Sinar Laut – Lahewa", "Grosir Sökhi – Pasar Gunungsitoli", "RM Ina Mawar – Gunungsitoli",
             "Ama Edi – Nias Barat", "Toko Harapan Baru – Gido", "Warung Ama Fati – Idanoi"]
ALASAN = ["Foto nota tidak terbaca, mohon foto ulang", "Jumlah tidak sama dengan nota", "Sudah dicatat kemarin (dobel)",
          "Salah kategori, ini pembelian karung bukan BBM", "Tidak ada nota dan tidak ada keterangan"]


def antara(a, b): return a + acak.random() * (b - a)
def bulat(n, ke=5000): return int(round(n / ke) * ke)
def pilih(xs): return xs[int(acak.random() * len(xs))]
def peluang(p): return acak.random() < p
def uuid(): return "demo-" + str(_uuid.UUID(int=acak.getrandbits(128)))
def lokal(y, m, d, h=0.0): return datetime(y, m, d, tzinfo=WIB) + timedelta(hours=h)
def wib(t): return t.astimezone(WIB)
def yymm(t): return wib(t).strftime("%y%m")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sambung()

    # ---------- 0. pengaman & syarat ----------
    if db.transaksi.count_documents({}) and not db.pengaturan.find_one({"_id": "data_demo"}):
        print(f'Database "{config.DB_NAME}" berisi transaksi yang BUKAN data demo. Dibatalkan.')
        return 1
    if not db.kategori_transaksi.count_documents({}) or not db.akun.count_documents({}):
        print("Skema & data master belum ada. Pasang dulu: mongosh \"<connection string>/"
              f'{config.DB_NAME}" database/garam_nias_demo_mobile.js')
        return 1
    for n in DIKOSONGKAN:
        db[n].delete_many({})

    sekarang = kini()
    hari_ini = wib(sekarang)
    tgl_hari_ini = lokal(hari_ini.year, hari_ini.month, hari_ini.day)
    bln_awal = (hari_ini.month - 4) % 12 + 1          # 3 bulan sebelum bulan berjalan
    awal = lokal(hari_ini.year - (hari_ini.month <= 3), bln_awal, 1)

    for k, v in {"nama_usaha": "Usaha Garam Nias", "no_wa_usaha": "081200000001", "data_demo": True}.items():
        db.pengaturan.update_one({"_id": k}, {"$set": {"nilai": v, "diperbarui_at": sekarang}}, upsert=True)

    # ---------- 1. pengguna (PIN demo 1234) ----------
    pin = bcrypt.hashpw(b"1234", bcrypt.gensalt(10)).decode()
    orang = [
        ("pemilik", "Faozaro Harefa", "081200000001", True, "Samsung Galaxy A35"),
        ("admin", "Desi Telaumbanua", "081200000002", True, "Xiaomi Redmi Note 13"),
        ("keuangan", "Rina Gulo", "081200000003", True, "Oppo A79"),
        ("petugas", "Amoni Zalukhu", "081200000011", True, "Vivo Y17s"),          # bahan baku & tambak
        ("petugas", "Sozisokhi Laia", "081200000012", True, "Samsung Galaxy A05"),  # gudang & penjualan
        ("petugas", "Yosefa Mendrofa", "081200000013", True, "Infinix Hot 40"),    # pengantaran & BBM
        ("petugas", "Ina Lestari Waruwu", "081200000014", False, None),           # baru: belum punya PIN
        ("petugas", "Berkat Halawa", "081200000015", True, "Realme C51"),          # sudah dinonaktifkan
    ]
    P = {}
    daftar = awal - 5 * HARI
    for peran, nama, no_hp, punya_pin, hp in orang:
        nonaktif = nama == "Berkat Halawa"
        _id = ObjectId()
        P[nama.split()[0]] = {"_id": _id, "nama": nama, "peran": peran}
        perangkat = [{
            "device_id": uuid()[5:21], "nama_perangkat": hp, "biometrik_aktif": False, "versi_aplikasi": "1.0",
            "terakhir_sinkron_at": awal + 30 * HARI if nonaktif else sekarang - antara(0.2, 20) * JAM,
            "dicabut_at": awal + 31 * HARI if nonaktif else None, "didaftarkan_at": daftar,
        }] if hp else []
        db.pengguna.insert_one({
            "_id": _id, "nama": nama, "no_hp": no_hp, "email": None, "kata_sandi_hash": None,
            "pin_hash": pin if punya_pin else None, "peran": peran, "gudang_id": None, "foto_url": None,
            "aktif": not nonaktif, "perangkat": perangkat,
            "terakhir_masuk_at": sekarang - antara(1, 30) * JAM if hp else None,
            "dibuat_oleh": None, "dibuat_at": daftar, "diperbarui_at": daftar,
        })
    Faozaro, Desi, Rina, Amoni, Sozisokhi, Yosefa = (P[k] for k in
                                                       ["Faozaro", "Desi", "Rina", "Amoni", "Sozisokhi", "Yosefa"])
    db.pengguna.update_many({"peran": {"$ne": "pemilik"}}, {"$set": {"dibuat_oleh": Faozaro["_id"]}})

    # ---------- 2. data rujukan (tidak diubah) ----------
    kategori = list(db.kategori_transaksi.find())
    def K(arah, nama): return next(k for k in kategori if k["arah"] == arah and k["nama"] == nama)
    kas = {a["nama"]: a for a in db.akun_kas.find()}
    akun = {a["kode"]: a for a in db.akun.find()}
    nota = {f.stem: f.read_bytes() for f in FOLDER_NOTA.glob("*.jpg")}

    # ---------- 3. susun kejadian per hari ----------
    kejadian = []
    def catat(**e): kejadian.append(e)
    hari_lalu = []
    t = awal
    while t <= tgl_hari_ini:
        hari_lalu.append(t)
        t = lokal(*(lambda x: (x.year, x.month, x.day))(wib(t) + HARI))

    for hari in hari_lalu:
        if hari == tgl_hari_ini:
            continue  # hari ini diisi khusus di bawah
        w = wib(hari)
        d, dow = w.day, (w.weekday() + 1) % 7   # 0 = Minggu
        if dow != 0:  # penjualan Senin–Sabtu
            for _ in range(1 if peluang(0.5) else 2):
                pakai_nota = peluang(0.12)
                catat(hari=hari, jam=antara(8, 17), arah="masuk", kat="Penjualan",
                      tags=pilih([["Garam halus"], ["Garam halus", "Garam kasar"], ["Garam karung"], ["Garam kasar"]]),
                      jumlah=NILAI_NOTA["jual"] if pakai_nota else bulat(antara(800000, 3800000), 25000),
                      kas=pilih(["Kas"] * 5 + ["BRI"] * 3 + ["QRIS"]), ket=pilih(PELANGGAN),
                      oleh=Sozisokhi if peluang(0.7) else pilih([Desi, Rina]), nota="jual" if pakai_nota else None)
        if d in (12, 27):
            catat(hari=hari, jam=antara(9, 15), arah="masuk", kat="Pelunasan piutang",
                  tags=[pilih(["Warung", "Reseller", "Distributor"])], jumlah=bulat(antara(1500000, 2800000), 50000),
                  kas="BRI", ket="Pelunasan " + pilih(PELANGGAN), oleh=Rina)
        if dow == 2:  # Selasa: belanja krosok → satu kiriman "Lebih dari Satu Transaksi"
            kir, pakai_nota = uuid(), peluang(0.5)
            catat(hari=hari, jam=10.2, arah="keluar", kat="Bahan baku", tags=["Garam krosok"],
                  jumlah=NILAI_NOTA["krosok"] if pakai_nota else bulat(antara(3800000, 7000000), 50000), kas="Kas",
                  ket="Garam krosok dari petambak Lahewa", oleh=Amoni, nota="krosok" if pakai_nota else None, kiriman=kir)
            catat(hari=hari, jam=10.3, arah="keluar", kat="Transportasi & kapal", tags=["Sewa truk"],
                  jumlah=bulat(antara(300000, 450000), 25000), kas="Kas", ket="Sewa pikap angkut krosok", oleh=Amoni, kiriman=kir)
            if peluang(0.5):
                catat(hari=hari, jam=10.4, arah="keluar", kat="Transportasi & kapal", tags=["Bongkar muat"],
                      jumlah=bulat(antara(150000, 250000), 25000), kas="Kas", ket="Upah bongkar muat 4 orang", oleh=Amoni, kiriman=kir)
        if dow == 4:
            catat(hari=hari, jam=antara(14, 17), arah="keluar", kat="Gaji & upah", tags=["Upah panen petambak"],
                  jumlah=bulat(antara(1200000, 2100000), 50000), kas="Kas", ket="Upah panen mingguan", oleh=Amoni)
        if dow == 6:
            catat(hari=hari, jam=16.5, arah="keluar", kat="Gaji & upah", tags=["Upah harian pengemas"],
                  jumlah=bulat(antara(1800000, 2600000), 50000), kas="Kas", ket="6 pekerja pengemasan, 1 minggu", oleh=Sozisokhi)
        if dow in (1, 4):
            pakai_nota = peluang(0.3)
            catat(hari=hari, jam=antara(7, 9), arah="keluar", kat="Transportasi & kapal", tags=["BBM"],
                  jumlah=NILAI_NOTA["bbm"] if pakai_nota else bulat(antara(250000, 600000), 5000), kas="Kas",
                  ket="Solar mobil antar", oleh=Yosefa, nota="bbm" if pakai_nota else None)
        if dow == 3 and (d // 7) % 2 == 0:
            catat(hari=hari, jam=8, arah="keluar", kat="Transportasi & kapal", tags=["Ongkos kapal", "Bongkar muat"],
                  jumlah=NILAI_NOTA["kapal"], kas="Kas", ket="Kirim 40 karung ke Pulau Tello", oleh=Yosefa, nota="kapal")
        if d == 5:
            catat(hari=hari, jam=11, arah="keluar", kat="Bahan baku", tags=["Kalium iodat (KIO₃)"], jumlah=NILAI_NOTA["kio3"],
                  kas="Kas", ket="KIO₃ untuk yodisasi", oleh=Amoni, nota="kio3")
        if d in (2, 16):
            plastik = d == 2
            catat(hari=hari, jam=10, arah="keluar", kat="Kemasan",
                  tags=["Plastik 250 g", "Plastik 500 g", "Label"] if plastik else ["Karung 50 kg"],
                  jumlah=NILAI_NOTA["plastik" if plastik else "karung"], kas="Kas",
                  ket="Plastik kemasan & label" if plastik else "Karung 50 kg", oleh=Sozisokhi,
                  nota="plastik" if plastik else "karung")
        if d == 8:
            catat(hari=hari, jam=13, arah="keluar", kat="Perawatan tambak", tags=["Terpal"], jumlah=NILAI_NOTA["terpal"],
                  kas="Kas", ket="Terpal penutup meja garam", oleh=Amoni, nota="terpal")
        if d == 21:
            catat(hari=hari, jam=13, arah="keluar", kat="Perawatan tambak", tags=[pilih(["Pestisida & obat", "Perbaikan pematang"])],
                  jumlah=bulat(antara(350000, 900000), 25000), kas="Kas", ket="Perawatan petak tambak", oleh=Amoni)
        if d == 25:
            catat(hari=hari, jam=10, arah="keluar", kat="Gaji & upah", tags=["Gaji bulanan"], jumlah=14500000, kas="BRI",
                  ket="Gaji 5 karyawan tetap", oleh=Rina)
        if d == 20:
            catat(hari=hari, jam=11, arah="keluar", kat="Operasional", tags=["Listrik & air"],
                  jumlah=bulat(antara(850000, 1150000), 1000), kas="BRI", ket="Tagihan listrik gudang", oleh=Rina)
        if d == 3:
            catat(hari=hari, jam=9, arah="keluar", kat="Operasional", tags=["Pulsa & internet"], jumlah=350000, kas="QRIS",
                  ket="Paket data HP petugas", oleh=Rina)
        if d == 10:
            catat(hari=hari, jam=9, arah="keluar", kat="Angsuran pinjaman", tags=[], jumlah=3560000, kas="BRI",
                  ket="Angsuran KUR BRI", oleh=Rina)
        if hari == hari_lalu[41]:
            catat(hari=hari, jam=14, arah="keluar", kat="Peralatan & aset", tags=[], jumlah=4250000, kas="BRI",
                  ket="Timbangan digital 150 kg", oleh=Desi)
        if wib(hari + HARI).day == 1:
            catat(hari=hari, jam=17, arah="keluar", kat="Prive pemilik", tags=[], jumlah=5000000, kas="BRI",
                  ket="Prive bulanan", oleh=Faozaro)

    # Hari ini: penjualan, satu kiriman dari Amoni dan catatan Yosefa yang menunggu diperiksa
    kir, tunggu = uuid(), "menunggu_periksa"
    h = tgl_hari_ini
    catat(hari=h, jam=8.4, arah="masuk", kat="Penjualan", tags=["Garam halus", "Garam kasar"], jumlah=NILAI_NOTA["jual"],
          kas="Kas", ket="Toko Faebua – Gunungsitoli", oleh=Sozisokhi, nota="jual", status_paksa=tunggu)
    catat(hari=h, jam=10.5, arah="masuk", kat="Penjualan", tags=["Garam karung"], jumlah=2750000, kas="BRI",
          ket="Ama Edi – Nias Barat (transfer)", oleh=Desi)
    catat(hari=h, jam=11.2, arah="masuk", kat="Penjualan", tags=["Garam halus"], jumlah=1250000, kas="QRIS",
          ket="RM Ina Mawar – Gunungsitoli", oleh=Rina)
    catat(hari=h, jam=9.1, arah="keluar", kat="Bahan baku", tags=["Garam krosok"], jumlah=NILAI_NOTA["krosok"], kas="Kas",
          ket="Krosok 1.200 kg, petambak Tuhemberua", oleh=Amoni, nota="krosok", kiriman=kir, status_paksa=tunggu)
    catat(hari=h, jam=9.15, arah="keluar", kat="Transportasi & kapal", tags=["Sewa truk"], jumlah=400000, kas="Kas",
          ket="Sewa pikap", oleh=Amoni, kiriman=kir, status_paksa=tunggu)
    catat(hari=h, jam=9.2, arah="keluar", kat="Gaji & upah", tags=["Upah panen petambak"], jumlah=600000, kas="Kas",
          ket="Upah angkat karung", oleh=Amoni, kiriman=kir, status_paksa=tunggu)
    catat(hari=h, jam=7.6, arah="keluar", kat="Transportasi & kapal", tags=["BBM"], jumlah=NILAI_NOTA["bbm"], kas="Kas",
          ket="Solar + pertalite", oleh=Yosefa, nota="bbm", status_paksa=tunggu)

    for e in kejadian:
        e["dicatat_at"] = e["hari"] + e["jam"] * JAM
    nyata = sorted((e for e in kejadian if e["dicatat_at"] <= sekarang), key=lambda e: e["dicatat_at"])

    # ---------- 4. transaksi, lampiran, kiriman, jurnal ----------
    ember = GridFSBucket(db, bucket_name="lampiran")
    hitung: dict[str, int] = {}
    def nomor(prefix, t):
        k = f"{prefix}-{yymm(t)}"
        hitung[k] = hitung.get(k, 0) + 1
        return f"{k}-{hitung[k]:04d}"

    def baris_j(kode, debit, kredit, aktivitas=None):
        a = akun[kode]
        return {"akun_kode": kode, "akun_nama": a["nama"], "akun_tipe": a["tipe"], "is_kas": a["is_kas"],
                "debit": D(debit), "kredit": D(kredit), "aktivitas": aktivitas, "keterangan": None}

    jurnal = [{"tanggal": awal, "keterangan": "Saldo awal pembukuan", "sumber": {"koleksi": "manual", "id": None},
               "otomatis": False, "dibuat_oleh": Rina["_id"], "dibuat_at": awal, "baris": [
                   baris_j("1-1100", 18000000, 0), baris_j("1-1200", 120000000, 0), baris_j("1-1300", 2000000, 0),
                   baris_j("1-1400", 15000000, 0), baris_j("1-1500", 22000000, 0), baris_j("1-1600", 9500000, 0),
                   baris_j("1-2100", 160000000, 0), baris_j("1-2200", 85000000, 0), baris_j("2-2100", 0, 80000000),
                   baris_j("3-1000", 0, 351500000)]}]
    for hari in hari_lalu:  # tarik tunai BRI → Kas tiap tanggal 1 dan 15
        if wib(hari).day in (1, 15):
            jurnal.append({"tanggal": hari, "keterangan": "Tarik tunai BRI untuk kas operasional",
                           "sumber": {"koleksi": "manual", "id": None}, "otomatis": False, "dibuat_oleh": Rina["_id"],
                           "dibuat_at": hari + 9 * JAM,
                           "baris": [baris_j("1-1100", 8000000, 0, "operasi"), baris_j("1-1200", 0, 8000000, "operasi")]})

    kiriman, audit, wa = {}, [], []
    ambang_periksa = tgl_hari_ini - 3 * HARI
    ditolak_baru = 0
    for e in nyata:
        kat, oleh = K(e["arah"], e["kat"]), e["oleh"]
        is_admin = oleh["peran"] in PERAN_ADMIN
        tunda = antara(0, 0.05) if is_admin else (antara(2, 20) if peluang(0.25) else antara(0, 0.2))
        dibuat = min(e["dicatat_at"] + tunda * JAM, sekarang - timedelta(minutes=1))
        id_, cu = ObjectId(), uuid()

        status, alasan, pemeriksa, waktu_periksa = "disetujui", None, oleh, dibuat
        if not is_admin:
            baru = e["hari"] >= ambang_periksa
            if e.get("status_paksa") == tunggu or (baru and peluang(0.85)):
                status = tunggu
            else:
                minggu_ini = e["hari"] >= tgl_hari_ini - 6 * HARI
                tolak = (not baru and oleh is Amoni and ditolak_baru < 1) if minggu_ini else peluang(0.04)
                if tolak:
                    status = "ditolak"
                    alasan = ALASAN[0] if minggu_ini else pilih(ALASAN)
                    ditolak_baru += minggu_ini
                pemeriksa = Desi if peluang(0.75) else Rina
                waktu_periksa = min(dibuat + antara(1, 26) * JAM, sekarang - timedelta(seconds=30))

        ak = kas["Kas" if not is_admin and status != "disetujui" else e["kas"]]  # petugas tidak memilih akun kas
        lampiran = []
        if e.get("nota") in nota:
            lcu, isi = uuid(), nota[e["nota"]]
            fid = ember.upload_from_stream(lcu, isi, metadata={"client_uuid": lcu, "jenis": "foto_nota", "mime": "image/jpeg",
                                                               "durasi_detik": None, "diunggah_oleh": oleh["_id"]})
            lampiran.append({"jenis": "foto_nota", "url": f"/api/lampiran/{fid}", "mime": "image/jpeg", "ukuran_byte": len(isi),
                             "client_uuid": lcu, "diunggah_oleh": oleh["_id"], "dibuat_at": dibuat})

        kiriman_id = None
        if e.get("kiriman") and not is_admin:
            if e["kiriman"] not in kiriman:
                anggota = [x for x in nyata if x.get("kiriman") == e["kiriman"]]
                kiriman[e["kiriman"]] = {"_id": ObjectId(), "petugas": {"_id": oleh["_id"], "nama": oleh["nama"]},
                                         "arah": e["arah"], "jumlah_transaksi": len(anggota),
                                         "total": D(sum(x["jumlah"] for x in anggota)),
                                         "dikirim_at": anggota[-1]["dicatat_at"], "diterima_at": dibuat,
                                         "client_uuid": e["kiriman"]}
            kiriman_id = kiriman[e["kiriman"]]["_id"]

        tags = [{"_id": g["_id"], "nama": g["nama"]} for g in kat["tags"] if g["nama"] in e["tags"]] \
            if status == "disetujui" else []
        doc = {
            "_id": id_, "nomor": nomor("TRX", e["hari"]), "tanggal": e["hari"], "arah": e["arah"],
            "kategori": {"_id": kat["_id"], "nama": kat["nama"], "label_petugas": kat.get("label_petugas"),
                         "akun_kode": kat["akun_kode"], "aktivitas": kat["aktivitas"]},
            "akun_kas": {"_id": ak["_id"], "nama": ak["nama"], "akun_kode": ak["akun_kode"]},
            "jumlah": D(e["jumlah"]), "keterangan": e.get("ket"), "status": status,
            "sumber": "hp_admin" if is_admin else "hp_petugas", "tanpa_nota": not lampiran,
            "tags": tags, "lampiran": lampiran, "terkait": {}, "kiriman_id": kiriman_id,
            "dicatat_oleh": {"_id": oleh["_id"], "nama": oleh["nama"], "peran": oleh["peran"]}, "dicatat_at": e["dicatat_at"],
            "jurnal_id": None, "client_uuid": cu, "dibuat_at": dibuat,
            "diperbarui_at": dibuat if status == tunggu else waktu_periksa,
        }
        if status != tunggu:
            doc["pemeriksaan"] = {"oleh": {"_id": pemeriksa["_id"], "nama": pemeriksa["nama"]}, "at": waktu_periksa,
                                  "alasan_tolak": alasan}
        if status == "disetujui":
            jid = doc["jurnal_id"] = ObjectId()
            jml = e["jumlah"]
            ka, kk = kat["akun_kode"], ak["akun_kode"]
            jurnal.append({"_id": jid, "tanggal": e["hari"], "keterangan": f"{kat['nama']} · {e['ket']}" if e.get("ket") else kat["nama"],
                           "sumber": {"koleksi": "transaksi", "id": id_}, "otomatis": True, "dibuat_oleh": None,
                           "dibuat_at": waktu_periksa,
                           "baris": [baris_j(kk, jml, 0, kat["aktivitas"]), baris_j(ka, 0, jml)] if e["arah"] == "masuk"
                           else [baris_j(ka, jml, 0), baris_j(kk, 0, jml, kat["aktivitas"])]})
        if not is_admin and status != tunggu:
            audit.append({"pengguna_id": pemeriksa["_id"], "aksi": "setujui" if status == "disetujui" else "tolak",
                          "koleksi": "transaksi", "dok_id": id_, "sebelum": {"status": tunggu},
                          "sesudah": {"status": status, "kategori": kat["nama"], "tags": [g["nama"] for g in tags]}
                          if status == "disetujui" else {"status": status, "alasan": alasan},
                          "ip": None, "waktu": waktu_periksa})
            if status == "ditolak":
                no_hp = db.pengguna.find_one({"_id": oleh["_id"]})["no_hp"]
                wa.append({"no_tujuan": no_hp, "template": "transaksi_ditolak",
                           "data": {"kategori": kat.get("label_petugas") or kat["nama"],
                                    "jumlah": f"{e['jumlah']:,}".replace(",", "."), "alasan": alasan},
                           "status": "terkirim", "terkait": {"koleksi": "transaksi", "id": id_}, "percobaan": 1,
                           "galat": None, "dibuat_at": waktu_periksa, "dikirim_at": waktu_periksa + timedelta(seconds=4)})
        db.transaksi.insert_one(doc)

    if kiriman:
        db.kiriman_petugas.insert_many(list(kiriman.values()))

    # HPP akhir bulan (bulan yang sudah lewat): bahan baku & kemasan yang dibeli bulan itu terpakai
    beli: dict[str, float] = {}
    for j in jurnal:
        for b in j["baris"]:
            if j["otomatis"] and b["akun_kode"] == "1-1600":
                beli[yymm(j["tanggal"])] = beli.get(yymm(j["tanggal"]), 0) + float(b["debit"].to_decimal())
    for hari in hari_lalu:
        besok = hari + HARI
        if wib(besok).day != 1 or besok > sekarang or not beli.get(yymm(hari)):
            continue
        hpp = beli[yymm(hari)]
        jurnal.append({"tanggal": hari, "keterangan": "HPP garam terjual (hitung persediaan akhir bulan)",
                       "sumber": {"koleksi": "manual", "id": None}, "otomatis": False, "dibuat_oleh": Rina["_id"],
                       "dibuat_at": besok + 10 * JAM, "baris": [baris_j("5-1000", hpp, 0), baris_j("1-1600", 0, hpp)]})

    jurnal.sort(key=lambda j: j["tanggal"])
    for j in jurnal:
        w = wib(j["tanggal"])
        j.setdefault("_id", ObjectId())
        j["nomor"] = nomor("JU", j["tanggal"])
        j["periode"] = {"tahun": w.year, "bulan": w.month}
    db.jurnal.insert_many(jurnal)
    if audit:
        db.log_audit.insert_many(audit)
    if wa:
        db.notifikasi_wa.insert_many(wa)

    # periode: bulan lama ditutup, bulan lalu & bulan berjalan terbuka
    t = awal
    while t <= tgl_hari_ini:
        w = wib(t)
        mulai = lokal(w.year, w.month, 1)
        berikut = lokal(w.year + (w.month == 12), w.month % 12 + 1, 1)
        selesai = berikut - timedelta(milliseconds=1)
        tutup = selesai < lokal(hari_ini.year, hari_ini.month, 1) - 20 * HARI
        db.periode.insert_one({"tahun": w.year, "bulan": w.month, "mulai": mulai, "selesai": selesai,
                               "status": "ditutup" if tutup else "terbuka", "ditutup_oleh": Rina["_id"] if tutup else None,
                               "ditutup_at": selesai + 5 * HARI if tutup else None})
        t = berikut
    # penghitung nomor: catatan baru dari HP melanjutkan nomor terakhir
    db.penghitung.insert_many([{"_id": k, "n": n} for k, n in hitung.items()])

    # ---------- ringkasan ----------
    status = {x["_id"]: x["n"] for x in db.transaksi.aggregate([{"$group": {"_id": "$status", "n": {"$sum": 1}}}])}
    saldo = {x["_id"]: float(x["s"].to_decimal()) for x in db.jurnal.aggregate([
        {"$unwind": "$baris"}, {"$match": {"baris.is_kas": True}},
        {"$group": {"_id": "$baris.akun_nama", "s": {"$sum": {"$subtract": ["$baris.debit", "$baris.kredit"]}}}}])}
    print(f'Data demo "{config.DB_NAME}" diperbarui: {wib(awal):%d/%m/%Y} s.d. hari ini.')
    print("Transaksi:", status, "· Kiriman:", len(kiriman), "· Foto nota:", db["lampiran.files"].count_documents({}),
          "· Jurnal:", len(jurnal))
    print("Saldo kas:", {k: f"{v:,.0f}".replace(",", ".") for k, v in saldo.items()})
    print("Masuk demo: 0812-0000-0001 (pemilik), …0002 (admin), …0011 (petugas). PIN 1234.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
