"""Jurnal otomatis untuk transaksi yang disetujui (dipanggil di dalam transaction)."""
from datetime import datetime, timedelta

from bson import ObjectId

from .db import WIB, D, db, kini, nomor_berikut, tahun_bulan
from .umum import Galat


def jurnal_transaksi(trx: dict, session) -> ObjectId:
    tahun, bulan = tahun_bulan(trx["tanggal"])

    # Periode buku: dibuat otomatis; bila sudah ditutup, transaksi tidak boleh masuk
    periode = db.periode.find_one({"tahun": tahun, "bulan": bulan}, session=session)
    if not periode:
        mulai = datetime(tahun, bulan, 1, tzinfo=WIB)
        selesai = datetime(tahun + (bulan == 12), bulan % 12 + 1, 1, tzinfo=WIB) - timedelta(milliseconds=1)
        db.periode.insert_one({"tahun": tahun, "bulan": bulan, "mulai": mulai, "selesai": selesai, "status": "terbuka"},
                              session=session)
    elif periode["status"] == "ditutup":
        raise Galat(409, f"Buku bulan {bulan}/{tahun} sudah ditutup. Ubah tanggal transaksi ke bulan berjalan.")

    akun_kategori = db.akun.find_one({"kode": trx["kategori"]["akun_kode"]}, session=session)
    akun_kas = db.akun.find_one({"kode": trx["akun_kas"]["akun_kode"]}, session=session)

    def baris(a: dict, debit, kredit, aktivitas=None) -> dict:
        return {"akun_kode": a["kode"], "akun_nama": a["nama"], "akun_tipe": a["tipe"], "is_kas": a["is_kas"],
                "debit": D(debit), "kredit": D(kredit), "aktivitas": aktivitas, "keterangan": None}

    jml = trx["jumlah"].to_decimal()
    aktivitas = trx["kategori"]["aktivitas"]
    if trx["arah"] == "masuk":   # kas bertambah: Debit kas, Kredit akun kategori (mis. Penjualan)
        isi = [baris(akun_kas, jml, 0, aktivitas), baris(akun_kategori, 0, jml)]
    else:                        # kas berkurang: Debit akun kategori (mis. Gaji), Kredit kas
        isi = [baris(akun_kategori, jml, 0), baris(akun_kas, 0, jml, aktivitas)]

    ket = trx["kategori"]["nama"] + (f" · {trx['keterangan']}" if trx.get("keterangan") else "")
    doc = {
        "nomor": nomor_berikut("JU", trx["tanggal"], session),
        "tanggal": trx["tanggal"],
        "periode": {"tahun": tahun, "bulan": bulan},
        "keterangan": ket,
        "sumber": {"koleksi": "transaksi", "id": trx["_id"]},
        "otomatis": True,
        "baris": isi,
        "dibuat_oleh": None,
        "dibuat_at": kini(),
    }
    return db.jurnal.insert_one(doc, session=session).inserted_id
