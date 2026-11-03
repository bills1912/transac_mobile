"""Garam Nias API (Python / FastAPI).

Jalankan di laptop :  uvicorn app.main:app --reload --port 3000
Jalankan di Railway:  uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips="*"
Dokumentasi API otomatis: http://localhost:3000/docs
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from pymongo.errors import WriteError
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import config
from .db import db, kini, sambung
from .rute_admin import r as rute_admin
from .rute_auth import r as rute_auth
from .rute_transaksi import r as rute_transaksi
from .umum import Galat, ResponJson

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("garam_nias")

KOLEKSI_WAJIB = ["pengguna", "kode_otp", "akun", "akun_kas", "kategori_transaksi", "kiriman_petugas", "transaksi",
                 "periode", "jurnal", "pengaturan", "notifikasi_wa", "log_audit"]


def siapkan_database() -> None:
    sambung()
    # Skema (validator, indeks, data awal) dipasang dengan mongosh, bukan oleh server:
    #   database/garam_nias_demo_mobile.js  (data demo)  atau  database/garam_nias_mongodb.js (kosong, untuk produksi)
    ada = set(db.list_collection_names())
    kurang = [k for k in KOLEKSI_WAJIB if k not in ada]
    if kurang:
        log.warning("Koleksi belum ada: %s. Pasang skema dulu: mongosh \"<connection string>/%s\" garam_nias_mongodb.js",
                    ", ".join(kurang), config.DB_NAME)
    if config.ADMIN_NO_HP and not db.pengguna.find_one({"no_hp": config.ADMIN_NO_HP}):
        sekarang = kini()
        db.pengguna.insert_one({
            "nama": config.ADMIN_NAMA, "no_hp": config.ADMIN_NO_HP, "email": None, "kata_sandi_hash": None,
            "pin_hash": None, "peran": "pemilik", "gudang_id": None, "aktif": True, "perangkat": [],
            "dibuat_oleh": None, "dibuat_at": sekarang, "diperbarui_at": sekarang,
        })
        log.info("Akun pemilik dibuat untuk %s", config.ADMIN_NO_HP)


@asynccontextmanager
async def umur(app: FastAPI):
    siapkan_database()
    log.info("Garam Nias API siap (DEV_OTP=%s)", config.DEV_OTP)
    yield


app = FastAPI(title="Garam Nias API", version="1.0.0", default_response_class=ResponJson, lifespan=umur)


# ---------- galat → {"pesan": "..."} (format yang dibaca aplikasi HP) ----------
@app.exception_handler(Galat)
async def tangani_galat(request: Request, e: Galat):
    return ResponJson({"pesan": e.pesan, **e.tambahan}, status_code=e.status)


@app.exception_handler(WriteError)
async def tangani_validasi_db(request: Request, e: WriteError):
    if e.code == 121:  # dokumen ditolak validator $jsonSchema
        log.warning("Ditolak validator: %s", e.details)
        return ResponJson({"pesan": "Data tidak lolos validasi database", "detail": "Data tidak lolos validasi database"},
                          status_code=400)
    log.exception("Galat database")
    return ResponJson({"pesan": "Terjadi kesalahan di server"}, status_code=500)


@app.exception_handler(RequestValidationError)
async def tangani_permintaan(request: Request, e: RequestValidationError):
    return ResponJson({"pesan": "Data yang dikirim tidak lengkap"}, status_code=400)


@app.exception_handler(StarletteHTTPException)
async def tangani_http(request: Request, e: StarletteHTTPException):
    if e.status_code in (404, 405):
        return ResponJson({"pesan": "Alamat API tidak ditemukan"}, status_code=404)
    return ResponJson({"pesan": str(e.detail)}, status_code=e.status_code)


@app.exception_handler(Exception)
async def tangani_lain(request: Request, e: Exception):
    log.exception("Galat tak terduga di %s %s", request.method, request.url.path)
    return ResponJson({"pesan": "Terjadi kesalahan di server"}, status_code=500)


@app.get("/api/sehat")
def sehat():
    return {"ok": True, "waktu": kini()}


app.include_router(rute_auth)
app.include_router(rute_admin)
app.include_router(rute_transaksi)
