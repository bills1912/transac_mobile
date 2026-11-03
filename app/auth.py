"""Token login (JWT) dan pengecekan pengguna yang sedang masuk."""
from datetime import timedelta

import jwt
from fastapi import Request

from . import config
from .db import db, kini, oid
from .umum import Galat

PERAN_ADMIN = ("pemilik", "admin", "keuangan")


def buat_token(pengguna: dict, device_id: str, jenis: str = "akses", masa: timedelta = timedelta(days=30)) -> str:
    sekarang = kini()
    isi = {"sub": str(pengguna["_id"]), "peran": pengguna["peran"], "dev": device_id, "jenis": jenis,
           "iat": int(sekarang.timestamp()), "exp": int((sekarang + masa).timestamp())}
    return jwt.encode(isi, config.JWT_SECRET, algorithm="HS256")


def ringkas_pengguna(p: dict) -> dict:
    return {"_id": p["_id"], "nama": p["nama"], "no_hp": p["no_hp"], "peran": p["peran"]}


def _periksa_token(request: Request, jenis: str) -> dict:
    h = request.headers.get("authorization", "")
    token = h[7:] if h.startswith("Bearer ") else request.query_params.get("t")  # ?t= untuk membuka foto nota
    if not token:
        raise Galat(401, "Silakan masuk dulu")
    try:
        isi = jwt.decode(token, config.JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise Galat(401, "Sesi berakhir, silakan masuk lagi")
    if isi.get("jenis") != jenis:
        raise Galat(401, "Token tidak berlaku untuk tindakan ini")
    p = db.pengguna.find_one({"_id": oid(isi.get("sub"))})
    if not p or not p.get("aktif"):
        raise Galat(401, "Akun tidak aktif")
    hp = next((d for d in p.get("perangkat") or [] if d.get("device_id") == isi.get("dev")), None)
    if not hp or hp.get("dicabut_at"):
        raise Galat(401, "HP ini sudah tidak diizinkan. Hubungi admin.")
    request.state.device_id = isi["dev"]
    return p


# Dipakai sebagai Depends(...) di rute
def pengguna_masuk(request: Request) -> dict:
    """Wajib token akses yang sah, pengguna aktif, dan HP belum dicabut."""
    return _periksa_token(request, "akses")


def pengguna_buat_pin(request: Request) -> dict:
    """Token sementara (15 menit) khusus untuk membuat PIN pertama kali."""
    return _periksa_token(request, "buat_pin")


def admin_masuk(request: Request) -> dict:
    p = _periksa_token(request, "akses")
    if p["peran"] not in PERAN_ADMIN:
        raise Galat(403, "Hanya untuk admin")
    return p
