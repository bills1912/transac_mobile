"""Masuk dengan nomor HP: kode WhatsApp → (buat PIN) → PIN harian. Peran dikenali dari nomor."""
import re
import secrets
from datetime import timedelta

import bcrypt
from fastapi import APIRouter, Body, Depends, Request

from . import config
from .auth import buat_token, pengguna_buat_pin, pengguna_masuk, ringkas_pengguna
from .db import db, kini
from .umum import Galat
from .wa import kirim_wa

r = APIRouter(prefix="/api/auth")
MAKS_PERCOBAAN = 5


def rapikan_hp(s) -> str:
    """'+62 812-0000-0001' → '081200000001'"""
    return re.sub(r"^62", "0", re.sub(r"\D", "", str(s or "")))


def _hash(teks: str, putaran: int) -> str:
    return bcrypt.hashpw(teks.encode(), bcrypt.gensalt(putaran)).decode()


def _cocok(teks: str, hash_: str | None) -> bool:
    return bool(hash_) and bcrypt.checkpw(teks.encode(), hash_.encode())


@r.post("/minta-kode")
def minta_kode(body: dict = Body(default={})):
    """1. Ketik nomor HP → kode 4 angka dikirim lewat WhatsApp."""
    no_hp = rapikan_hp(body.get("no_hp"))
    p = db.pengguna.find_one({"no_hp": no_hp, "aktif": True})
    if not p:
        raise Galat(404, "Nomor belum terdaftar. Hubungi pemilik usaha.")

    if db.kode_otp.count_documents({"no_hp": no_hp, "dibuat_at": {"$gte": kini() - timedelta(hours=1)}}) >= 5:
        raise Galat(429, "Terlalu sering meminta kode. Coba lagi 1 jam lagi.")

    kode = f"{secrets.randbelow(10000):04d}"
    db.kode_otp.insert_one({
        "pengguna_id": p["_id"], "no_hp": no_hp, "kode_hash": _hash(kode, 8), "tujuan": "masuk",
        "kedaluwarsa_at": kini() + timedelta(minutes=5), "dipakai_at": None, "percobaan": 0, "dibuat_at": kini(),
    })
    kirim_wa(no_hp, "kode_otp", {"kode": kode}, {"koleksi": "pengguna", "id": p["_id"]})
    return {"ok": True, **({"kode_uji": kode} if config.DEV_OTP else {})}


@r.post("/verifikasi")
def verifikasi(body: dict = Body(default={})):
    """2. Kode WhatsApp benar → HP didaftarkan. Belum punya PIN → buat PIN; sudah → token masuk."""
    no_hp = rapikan_hp(body.get("no_hp"))
    kode, device_id = str(body.get("kode") or ""), body.get("device_id")
    if not device_id:
        raise Galat(400, "device_id wajib")

    otp = db.kode_otp.find_one({"no_hp": no_hp, "dipakai_at": None, "kedaluwarsa_at": {"$gt": kini()}},
                               sort=[("dibuat_at", -1)])
    if not otp:
        raise Galat(400, "Kode sudah tidak berlaku. Minta kode baru.")
    if otp["percobaan"] >= MAKS_PERCOBAAN:
        raise Galat(400, "Terlalu banyak salah. Minta kode baru.")
    if not _cocok(kode, otp["kode_hash"]):
        db.kode_otp.update_one({"_id": otp["_id"]}, {"$inc": {"percobaan": 1}})
        raise Galat(400, "Kode salah. Periksa lagi pesan WhatsApp.")
    db.kode_otp.update_one({"_id": otp["_id"]}, {"$set": {"dipakai_at": kini()}})

    p = db.pengguna.find_one({"_id": otp["pengguna_id"]})
    sekarang = kini()
    if any(d.get("device_id") == device_id for d in p.get("perangkat") or []):
        # HP lama: aktifkan lagi bila sebelumnya dicabut
        db.pengguna.update_one({"_id": p["_id"]},
                               {"$set": {"perangkat.$[d].dicabut_at": None, "diperbarui_at": sekarang}, "$unset": {"gagal_pin": ""}},
                               array_filters=[{"d.device_id": device_id}])
    else:
        db.pengguna.update_one({"_id": p["_id"]}, {
            "$push": {"perangkat": {"device_id": device_id, "nama_perangkat": body.get("nama_perangkat") or "HP",
                                    "biometrik_aktif": False, "versi_aplikasi": "1.0", "terakhir_sinkron_at": None,
                                    "dicabut_at": None, "didaftarkan_at": sekarang}},
            "$set": {"diperbarui_at": sekarang}, "$unset": {"gagal_pin": ""}})

    if not p.get("pin_hash"):
        return {"langkah": "buat_pin", "token_pin": buat_token(p, device_id, "buat_pin", timedelta(minutes=15)),
                "pengguna": ringkas_pengguna(p)}
    db.pengguna.update_one({"_id": p["_id"]}, {"$set": {"terakhir_masuk_at": sekarang}})
    return {"langkah": "masuk", "token": buat_token(p, device_id), "pengguna": ringkas_pengguna(p)}


@r.post("/buat-pin")
def buat_pin(request: Request, body: dict = Body(default={}), p: dict = Depends(pengguna_buat_pin)):
    """3. Buat PIN 4 angka (pertama kali)."""
    pin = str(body.get("pin") or "")
    if not re.fullmatch(r"\d{4}", pin):
        raise Galat(400, "PIN harus 4 angka")
    db.pengguna.update_one({"_id": p["_id"]}, {"$set": {"pin_hash": _hash(pin, 10), "terakhir_masuk_at": kini(),
                                                          "diperbarui_at": kini()}})
    return {"token": buat_token(p, request.state.device_id), "pengguna": ringkas_pengguna(p)}


@r.post("/masuk-pin")
def masuk_pin(body: dict = Body(default={})):
    """4. Masuk harian dengan PIN (aplikasi juga menyimpan PIN di HP untuk masuk tanpa sinyal)."""
    no_hp = rapikan_hp(body.get("no_hp"))
    pin, device_id = str(body.get("pin") or ""), body.get("device_id")
    p = db.pengguna.find_one({"no_hp": no_hp, "aktif": True})
    hp = p and next((d for d in p.get("perangkat") or [] if d.get("device_id") == device_id and not d.get("dicabut_at")), None)
    if not p or not hp or not p.get("pin_hash"):
        raise Galat(401, "HP ini belum terdaftar. Masuk dengan nomor HP lagi.", ulang=True)
    if (p.get("gagal_pin") or 0) >= MAKS_PERCOBAAN:
        raise Galat(401, "PIN terkunci. Masuk lagi dengan kode WhatsApp.", ulang=True)
    if not _cocok(pin, p["pin_hash"]):
        db.pengguna.update_one({"_id": p["_id"]}, {"$inc": {"gagal_pin": 1}})
        raise Galat(401, "PIN salah", sisa=MAKS_PERCOBAAN - (p.get("gagal_pin") or 0) - 1)
    db.pengguna.update_one({"_id": p["_id"]}, {"$set": {"terakhir_masuk_at": kini()}, "$unset": {"gagal_pin": ""}})
    return {"token": buat_token(p, device_id), "pengguna": ringkas_pengguna(p)}


@r.get("/saya")
def saya(p: dict = Depends(pengguna_masuk)):
    return {"pengguna": ringkas_pengguna(p)}
