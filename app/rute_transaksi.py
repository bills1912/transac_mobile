"""Rute untuk HP (petugas & admin): data master, unggah foto, sinkron catatan, status catatan sendiri."""
from datetime import timedelta

from fastapi import APIRouter, Body, Depends, File, Form, Request, UploadFile
from fastapi.responses import Response
from gridfs import GridFSBucket
from pymongo.errors import DuplicateKeyError

from .auth import PERAN_ADMIN, pengguna_masuk
from .db import D, dalam_transaksi, db, ke_tanggal, kini, nomor_berikut, oid, parse_waktu
from .jurnal import jurnal_transaksi
from .umum import Galat

r = APIRouter(prefix="/api")
MAKS_FILE = 8 * 1024 * 1024


def ember() -> GridFSBucket:
    """Foto nota & rekaman suara disimpan di GridFS (koleksi lampiran.files + lampiran.chunks)."""
    return GridFSBucket(db, bucket_name="lampiran")


@r.get("/master")
def master(p: dict = Depends(pengguna_masuk)):
    """Data untuk dipakai offline di HP: kategori + tag, akun kas, pengaturan."""
    return {
        "kategori": list(db.kategori_transaksi.find({"aktif": True}).sort([("arah", -1), ("urutan", 1)])),
        "akun_kas": list(db.akun_kas.find({"aktif": True})),
        "pengaturan": {x["_id"]: x["nilai"] for x in db.pengaturan.find()},
        "waktu_server": kini(),
    }


@r.post("/lampiran")
def unggah_lampiran(file: UploadFile = File(None), client_uuid: str = Form(None), jenis: str = Form("foto_nota"),
                    durasi_detik: str = Form(None), p: dict = Depends(pengguna_masuk)):
    """Unggah foto nota / rekaman suara. Aman diulang: client_uuid yang sama mengembalikan file yang sama."""
    if not file or not client_uuid:
        raise Galat(400, "File dan client_uuid wajib")
    mime = file.content_type or ""
    if not (mime.startswith("image/") or mime.startswith("audio/")):
        raise Galat(400, "Hanya foto atau rekaman suara")
    lama = db["lampiran.files"].find_one({"metadata.client_uuid": client_uuid})
    if lama:
        return {"id": lama["_id"], "ukuran_byte": lama["length"], "mime": lama["metadata"]["mime"]}
    isi = file.file.read(MAKS_FILE + 1)
    if len(isi) > MAKS_FILE:
        raise Galat(413, "File terlalu besar (maks. 8 MB)")
    id_ = ember().upload_from_stream(client_uuid, isi, metadata={
        "client_uuid": client_uuid, "jenis": jenis, "mime": mime,
        "durasi_detik": int(durasi_detik) if durasi_detik else None, "diunggah_oleh": p["_id"],
    })
    return {"id": id_, "ukuran_byte": len(isi), "mime": mime}


@r.get("/lampiran/{id_}")
def lihat_lampiran(id_: str, p: dict = Depends(pengguna_masuk)):
    """Admin boleh melihat semua lampiran; petugas hanya lampiran miliknya."""
    f = db["lampiran.files"].find_one({"_id": oid(id_)})
    if not f:
        return Response(status_code=404)
    if p["peran"] not in PERAN_ADMIN and f["metadata"]["diunggah_oleh"] != p["_id"]:
        return Response(status_code=403)
    isi = ember().open_download_stream(f["_id"]).read()
    return Response(isi, media_type=f["metadata"]["mime"], headers={"Cache-Control": "private, max-age=86400"})


def _lampiran_milik(lampiran_ids, p, session) -> list[dict]:
    """Ubah daftar id lampiran yang sudah diunggah menjadi data lampiran untuk disimpan di transaksi."""
    hasil = []
    for lid in lampiran_ids or []:
        f = db["lampiran.files"].find_one({"_id": oid(lid), "metadata.diunggah_oleh": p["_id"]}, session=session)
        if not f:
            continue
        m = f["metadata"]
        item = {"jenis": m["jenis"], "url": f"/api/lampiran/{f['_id']}", "mime": m["mime"], "ukuran_byte": f["length"]}
        if m.get("durasi_detik"):
            item["durasi_detik"] = m["durasi_detik"]
        item.update({"client_uuid": m["client_uuid"], "diunggah_oleh": p["_id"], "dibuat_at": f["uploadDate"]})
        hasil.append(item)
    return hasil


@r.post("/sync")
def sinkron(request: Request, body: dict = Body(default={}), p: dict = Depends(pengguna_masuk)):
    """Sinkron dari HP: satu atau beberapa transaksi (+ kiriman "Lebih dari Satu Transaksi").
    Idempoten lewat client_uuid: kiriman ulang tidak membuat data dobel."""
    kiriman = body.get("kiriman")
    transaksi = body.get("transaksi") or []
    if not isinstance(transaksi, list) or not 1 <= len(transaksi) <= 50:
        raise Galat(400, "Kirim 1 sampai 50 transaksi")
    is_admin = p["peran"] in PERAN_ADMIN

    # Yang sudah pernah diterima cukup dilaporkan kembali
    hasil, baru = [], []
    for t in transaksi:
        lama = db.transaksi.find_one({"client_uuid": t.get("client_uuid")})
        if lama:
            hasil.append({"client_uuid": t["client_uuid"], "_id": lama["_id"], "nomor": lama["nomor"],
                          "status": lama["status"], "sudah_ada": True})
        else:
            baru.append(t)

    def simpan(session):
        hasil_baru = []  # dibuat ulang setiap kali MongoDB mengulang transaction
        kiriman_id = None
        if kiriman and baru:
            k = db.kiriman_petugas.find_one({"client_uuid": kiriman["client_uuid"]}, session=session)
            kiriman_id = k["_id"] if k else db.kiriman_petugas.insert_one({
                "petugas": {"_id": p["_id"], "nama": p["nama"]}, "arah": kiriman["arah"],
                "jumlah_transaksi": int(kiriman["jumlah_transaksi"]), "total": D(kiriman["total"]),
                "dikirim_at": parse_waktu(kiriman["dikirim_at"]), "diterima_at": kini(),
                "client_uuid": kiriman["client_uuid"],
            }, session=session).inserted_id

        for t in baru:
            kat = db.kategori_transaksi.find_one({"_id": oid(t.get("kategori_id")), "aktif": True}, session=session)
            if not kat or kat["arah"] != t.get("arah"):
                raise Galat(400, "Kategori tidak dikenal")
            if not is_admin and not kat["tampil_petugas"]:
                raise Galat(403, "Kategori ini hanya untuk admin")
            akun_kas = (db.akun_kas.find_one({"_id": oid(t["akun_kas_id"])}, session=session) if t.get("akun_kas_id")
                        else db.akun_kas.find_one({"nama": "Kas"}, session=session))  # petugas: otomatis Kas
            if not akun_kas:
                raise Galat(400, "Akun kas tidak dikenal")
            try:
                jumlah = float(t.get("jumlah"))
            except (TypeError, ValueError):
                jumlah = 0
            if not 0 < jumlah <= 1e12:
                raise Galat(400, "Jumlah tidak sah")

            lampiran = _lampiran_milik(t.get("lampiran_ids"), p, session)
            # Tag hanya diisi bila yang mencatat admin; untuk petugas, admin memilih tag saat memeriksa
            tags = [{"_id": g["_id"], "nama": g["nama"]} for g in kat["tags"] if str(g["_id"]) in (t.get("tag_ids") or [])] \
                if is_admin else []
            sekarang = kini()
            tanggal = ke_tanggal(t.get("tanggal") or t.get("dicatat_at"))
            doc = {
                "nomor": nomor_berikut("TRX", tanggal, session),
                "tanggal": tanggal, "arah": t["arah"],
                "kategori": {"_id": kat["_id"], "nama": kat["nama"], "label_petugas": kat.get("label_petugas"),
                             "akun_kode": kat["akun_kode"], "aktivitas": kat["aktivitas"]},
                "akun_kas": {"_id": akun_kas["_id"], "nama": akun_kas["nama"], "akun_kode": akun_kas["akun_kode"]},
                "jumlah": D(t["jumlah"]),
                "keterangan": str(t["keterangan"])[:300] if t.get("keterangan") else None,
                "status": "disetujui" if is_admin else "menunggu_periksa",
                "sumber": "hp_admin" if is_admin else "hp_petugas",
                "tanpa_nota": all(l["jenis"] != "foto_nota" for l in lampiran),
                "tags": tags, "lampiran": lampiran, "terkait": {}, "kiriman_id": kiriman_id,
                "dicatat_oleh": {"_id": p["_id"], "nama": p["nama"], "peran": p["peran"]},
                "dicatat_at": parse_waktu(t["dicatat_at"]) if t.get("dicatat_at") else sekarang,
                "jurnal_id": None, "client_uuid": t["client_uuid"], "dibuat_at": sekarang, "diperbarui_at": sekarang,
            }
            if is_admin:  # catatan admin langsung disetujui dan dibuatkan jurnal
                doc["pemeriksaan"] = {"oleh": {"_id": p["_id"], "nama": p["nama"]}, "at": sekarang, "alasan_tolak": None}
            doc["_id"] = db.transaksi.insert_one(doc, session=session).inserted_id
            if is_admin:
                jid = jurnal_transaksi(doc, session)
                db.transaksi.update_one({"_id": doc["_id"]}, {"$set": {"jurnal_id": jid}}, session=session)
            hasil_baru.append({"client_uuid": t["client_uuid"], "_id": doc["_id"], "nomor": doc["nomor"], "status": doc["status"]})
        return hasil_baru

    if baru:
        try:
            hasil += dalam_transaksi(simpan)
        except DuplicateKeyError:
            raise Galat(409, "Data sudah pernah dikirim, coba sinkron lagi")

    db.pengguna.update_one({"_id": p["_id"]}, {"$set": {"perangkat.$[d].terakhir_sinkron_at": kini()}},
                           array_filters=[{"d.device_id": request.state.device_id}])
    return {"hasil": hasil}


@r.get("/transaksi/saya")
def transaksi_saya(sejak: str | None = None, p: dict = Depends(pengguna_masuk)):
    """Catatan milik sendiri yang berubah sejak waktu tertentu (menunggu / disetujui / ditolak + alasan)."""
    batas = parse_waktu(sejak) if sejak else kini() - timedelta(days=14)
    proyeksi = {"nomor": 1, "tanggal": 1, "arah": 1, "kategori.nama": 1, "kategori.label_petugas": 1, "jumlah": 1,
                "status": 1, "pemeriksaan.alasan_tolak": 1, "client_uuid": 1, "dicatat_at": 1, "diperbarui_at": 1}
    daftar = list(db.transaksi.find({"dicatat_oleh._id": p["_id"], "diperbarui_at": {"$gte": batas}}, proyeksi)
                  .sort("dicatat_at", -1).limit(300))
    return {"transaksi": daftar, "waktu_server": kini()}
