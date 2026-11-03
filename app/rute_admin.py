"""Rute khusus admin (pemilik, admin, keuangan): beranda, periksa catatan petugas, rincian, kelola pengguna."""
import re
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Body, Depends, Request

from .auth import admin_masuk, ringkas_pengguna
from .db import WIB, angka, dalam_transaksi, db, kini, oid
from .jurnal import jurnal_transaksi
from .umum import Galat
from .wa import kirim_wa

r = APIRouter(prefix="/api/admin")


def awal_hari() -> datetime:
    """Pukul 00.00 WIB hari ini."""
    w = kini().astimezone(WIB)
    return datetime(w.year, w.month, w.day, tzinfo=WIB)


def audit(request: Request, p: dict, aksi: str, koleksi: str, dok_id, sebelum, sesudah) -> None:
    db.log_audit.insert_one({"pengguna_id": p["_id"], "aksi": aksi, "koleksi": koleksi, "dok_id": dok_id,
                             "sebelum": sebelum, "sesudah": sesudah,
                             "ip": request.client.host if request.client else None, "waktu": kini()})


@r.get("/ringkasan")
def ringkasan(p: dict = Depends(admin_masuk)):
    """Beranda admin: saldo tiap akun kas, masuk/keluar hari ini, jumlah catatan menunggu diperiksa."""
    saldo = {x["_id"]: x["saldo"] for x in db.jurnal.aggregate([
        {"$unwind": "$baris"}, {"$match": {"baris.is_kas": True}},
        {"$group": {"_id": "$baris.akun_kode", "saldo": {"$sum": {"$subtract": ["$baris.debit", "$baris.kredit"]}}}},
    ])}
    hari = {x["_id"]: {"total": angka(x["total"]), "n": x["n"]} for x in db.transaksi.aggregate([
        {"$match": {"tanggal": {"$gte": awal_hari()}, "status": {"$ne": "ditolak"}}},
        {"$group": {"_id": "$arah", "total": {"$sum": "$jumlah"}, "n": {"$sum": 1}}},
    ])}
    terbaru = list(db.transaksi.find({}, {"nomor": 1, "tanggal": 1, "arah": 1, "kategori.nama": 1, "jumlah": 1, "status": 1,
                                          "tags": 1, "dicatat_oleh.nama": 1, "dicatat_at": 1, "akun_kas": 1})
                   .sort("dicatat_at", -1).limit(8))
    return {
        "kas": [{"nama": a["nama"], "saldo": angka(saldo.get(a["akun_kode"]))} for a in db.akun_kas.find({"aktif": True})],
        "masuk_hari_ini": hari.get("masuk", {"total": 0, "n": 0}),
        "keluar_hari_ini": hari.get("keluar", {"total": 0, "n": 0}),
        "menunggu_periksa": db.transaksi.count_documents({"status": "menunggu_periksa"}),
        "terbaru": terbaru,
    }


@r.get("/periksa")
def daftar_periksa(p: dict = Depends(admin_masuk)):
    """Antrean catatan petugas yang perlu diperiksa (paling lama dulu)."""
    return {"transaksi": list(db.transaksi.find({"status": "menunggu_periksa"}).sort("dicatat_at", 1).limit(200))}


@r.post("/transaksi/{id_}/setujui")
def setujui(id_: str, request: Request, body: dict = Body(default={}), p: dict = Depends(admin_masuk)):
    """Setujui catatan petugas. Admin boleh membetulkan kategori, akun kas, dan memilih tag. Jurnal dibuat otomatis."""
    tag_ids = body.get("tag_ids") or []
    kategori_id, akun_kas_id = body.get("kategori_id"), body.get("akun_kas_id")

    def proses(session):
        t = db.transaksi.find_one({"_id": oid(id_)}, session=session)
        if not t:
            raise Galat(404, "Transaksi tidak ditemukan")
        if t["status"] != "menunggu_periksa":
            raise Galat(409, "Transaksi ini sudah diperiksa")
        if kategori_id and kategori_id != str(t["kategori"]["_id"]):
            kat = db.kategori_transaksi.find_one({"_id": oid(kategori_id), "arah": t["arah"]}, session=session)
        else:
            kat = db.kategori_transaksi.find_one({"_id": t["kategori"]["_id"]}, session=session)
        if not kat:
            raise Galat(400, "Kategori tidak dikenal")
        kas = db.akun_kas.find_one({"_id": oid(akun_kas_id)}, session=session) if akun_kas_id else None
        sekarang = kini()
        ubah = {
            "status": "disetujui",
            "kategori": {"_id": kat["_id"], "nama": kat["nama"], "label_petugas": kat.get("label_petugas"),
                         "akun_kode": kat["akun_kode"], "aktivitas": kat["aktivitas"]},
            "tags": [{"_id": g["_id"], "nama": g["nama"]} for g in kat["tags"] if str(g["_id"]) in tag_ids],
            "pemeriksaan": {"oleh": {"_id": p["_id"], "nama": p["nama"]}, "at": sekarang, "alasan_tolak": None},
            "diperbarui_at": sekarang,
        }
        if kas:
            ubah["akun_kas"] = {"_id": kas["_id"], "nama": kas["nama"], "akun_kode": kas["akun_kode"]}
        ubah["jurnal_id"] = jurnal_transaksi({**t, **ubah}, session)
        db.transaksi.update_one({"_id": t["_id"]}, {"$set": ubah}, session=session)
        return {"sebelum": {"status": t["status"], "kategori": t["kategori"]["nama"]},
                "sesudah": {"status": "disetujui", "kategori": kat["nama"], "tags": [g["nama"] for g in ubah["tags"]]},
                "nomor": t["nomor"]}

    h = dalam_transaksi(proses)
    audit(request, p, "setujui", "transaksi", oid(id_), h["sebelum"], h["sesudah"])
    return {"ok": True, "nomor": h["nomor"]}


@r.post("/transaksi/{id_}/tolak")
def tolak(id_: str, request: Request, latar: BackgroundTasks, body: dict = Body(default={}),
          p: dict = Depends(admin_masuk)):
    """Tolak catatan petugas (wajib beralasan). Petugas diberi tahu lewat WhatsApp dan di aplikasinya."""
    alasan = str(body.get("alasan") or "").strip()
    if not alasan:
        raise Galat(400, "Tulis alasan penolakan")
    t = db.transaksi.find_one({"_id": oid(id_)})
    if not t:
        raise Galat(404, "Transaksi tidak ditemukan")
    if t["status"] != "menunggu_periksa":
        raise Galat(409, "Transaksi ini sudah diperiksa")
    db.transaksi.update_one({"_id": t["_id"]}, {"$set": {
        "status": "ditolak", "diperbarui_at": kini(),
        "pemeriksaan": {"oleh": {"_id": p["_id"], "nama": p["nama"]}, "at": kini(), "alasan_tolak": alasan},
    }})
    audit(request, p, "tolak", "transaksi", t["_id"], {"status": t["status"]}, {"status": "ditolak", "alasan": alasan})
    petugas = db.pengguna.find_one({"_id": t["dicatat_oleh"]["_id"]})
    if petugas:  # dikirim setelah respons, supaya admin tidak menunggu WhatsApp
        latar.add_task(kirim_wa, petugas["no_hp"], "transaksi_ditolak", {
            "kategori": t["kategori"].get("label_petugas") or t["kategori"]["nama"],
            "jumlah": f"{angka(t['jumlah']):,.0f}".replace(",", "."), "alasan": alasan,
        }, {"koleksi": "transaksi", "id": t["_id"]})
    return {"ok": True}


@r.get("/per-kategori")
def per_kategori(bulan: str | None = None, p: dict = Depends(admin_masuk)):
    """Rincian transaksi disetujui per kategori dan tag, untuk bulan berjalan atau ?bulan=2026-10."""
    if not bulan or not re.fullmatch(r"\d{4}-\d{2}", bulan):
        bulan = kini().astimezone(WIB).strftime("%Y-%m")
    y, m = (int(x) for x in bulan.split("-"))
    mulai = datetime(y, m, 1, tzinfo=WIB)
    selesai = datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=WIB)
    data = next(db.transaksi.aggregate([
        {"$match": {"status": "disetujui", "tanggal": {"$gte": mulai, "$lt": selesai}}},
        {"$facet": {
            "kategori": [
                {"$group": {"_id": {"arah": "$arah", "id": "$kategori._id", "nama": "$kategori.nama"},
                            "total": {"$sum": "$jumlah"}, "n": {"$sum": 1}}},
                {"$sort": {"total": -1}}],
            "tag": [
                {"$unwind": {"path": "$tags", "preserveNullAndEmptyArrays": True}},
                {"$group": {"_id": {"kat": "$kategori._id", "tag": {"$ifNull": ["$tags.nama", "Tanpa tag"]}},
                            "total": {"$sum": "$jumlah"}, "n": {"$sum": 1}}},
                {"$sort": {"total": -1}}],
            "terbaru": [
                {"$sort": {"tanggal": -1, "dicatat_at": -1}},
                {"$group": {"_id": "$kategori._id", "list": {"$push": {
                    "ket": {"$ifNull": ["$keterangan", "$kategori.nama"]}, "tanggal": "$tanggal", "jumlah": "$jumlah",
                    "akun": "$akun_kas.nama", "tags": "$tags.nama"}}}},
                {"$project": {"list": {"$slice": ["$list", 3]}}}],
        }},
    ]))
    warna = {k["_id"]: k.get("warna") for k in db.kategori_transaksi.find({}, {"warna": 1})}

    def susun(arah: str) -> list[dict]:
        return [{
            "id": k["_id"]["id"], "nama": k["_id"]["nama"], "warna": warna.get(k["_id"]["id"]) or "#4B5D68",
            "total": angka(k["total"]), "n": k["n"],
            "tags": [{"nama": g["_id"]["tag"], "total": angka(g["total"]), "n": g["n"]}
                     for g in data["tag"] if g["_id"]["kat"] == k["_id"]["id"]],
            "terbaru": next((x["list"] for x in data["terbaru"] if x["_id"] == k["_id"]["id"]), []),
        } for k in data["kategori"] if k["_id"]["arah"] == arah]

    return {"bulan": bulan, "keluar": susun("keluar"), "masuk": susun("masuk")}


# ---------- kelola pengguna ----------
@r.get("/pengguna")
def daftar_pengguna(p: dict = Depends(admin_masuk)):
    daftar = db.pengguna.find({}, {"pin_hash": 0, "kata_sandi_hash": 0}).sort([("peran", 1), ("nama", 1)])
    return {"pengguna": [{
        **ringkas_pengguna(x), "aktif": x["aktif"], "punya_pin": False,
        "perangkat": len([d for d in x.get("perangkat") or [] if not d.get("dicabut_at")]),
        "terakhir_masuk_at": x.get("terakhir_masuk_at"),
    } for x in daftar]}


@r.post("/pengguna")
def tambah_pengguna(request: Request, body: dict = Body(default={}), p: dict = Depends(admin_masuk)):
    """Daftarkan orang baru cukup dengan nama dan nomor HP; perannya dikenali saat ia masuk."""
    nama = str(body.get("nama") or "").strip()
    no_hp = re.sub(r"^62", "0", re.sub(r"\D", "", str(body.get("no_hp") or "")))
    peran = body.get("peran")
    if not nama:
        raise Galat(400, "Nama wajib diisi")
    if not re.fullmatch(r"0\d{9,13}", no_hp):
        raise Galat(400, "Nomor HP tidak sah (contoh 081234567890)")
    boleh = ["petugas", "admin", "keuangan", "gudang"] if p["peran"] == "pemilik" else ["petugas"]
    if peran not in boleh:
        raise Galat(403, "Anda tidak boleh membuat peran ini")
    if db.pengguna.find_one({"no_hp": no_hp}):
        raise Galat(409, "Nomor HP sudah terdaftar")
    sekarang = kini()
    id_ = db.pengguna.insert_one({
        "nama": nama, "no_hp": no_hp, "email": None, "kata_sandi_hash": None, "pin_hash": None, "peran": peran,
        "gudang_id": None, "aktif": True, "perangkat": [], "dibuat_oleh": p["_id"], "dibuat_at": sekarang,
        "diperbarui_at": sekarang,
    }).inserted_id
    audit(request, p, "buat", "pengguna", id_, None, {"nama": nama, "no_hp": no_hp, "peran": peran})
    return {"ok": True, "_id": id_}


@r.post("/pengguna/{id_}/{aksi}")
def aksi_pengguna(id_: str, aksi: str, request: Request, p: dict = Depends(admin_masuk)):
    """nonaktifkan | aktifkan | reset-pin (HP hilang: semua HP dicabut, orang itu masuk lagi dengan kode WhatsApp)."""
    if aksi not in ("nonaktifkan", "aktifkan", "reset-pin"):
        raise Galat(404, "Alamat API tidak ditemukan")
    x = db.pengguna.find_one({"_id": oid(id_)})
    if not x:
        raise Galat(404, "Pengguna tidak ditemukan")
    if x["_id"] == p["_id"]:
        raise Galat(400, "Tidak bisa mengubah akun sendiri")
    if x["peran"] != "petugas" and p["peran"] != "pemilik":
        raise Galat(403, "Hanya pemilik yang bisa mengubah akun admin")
    ubah = {"pin_hash": None, "perangkat.$[].dicabut_at": kini()} if aksi == "reset-pin" else {"aktif": aksi == "aktifkan"}
    db.pengguna.update_one({"_id": x["_id"]}, {"$set": {**ubah, "diperbarui_at": kini()}})
    audit(request, p, aksi, "pengguna", x["_id"], None, None)
    return {"ok": True}
