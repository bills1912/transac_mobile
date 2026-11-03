"""Semua pengaturan dibaca dari variabel lingkungan.

- Di laptop: dari file .env di folder backend/ (lihat .env.example), dibaca otomatis.
- Di Railway: dari menu Variables.
"""
import os
import re
from urllib.parse import unquote

from dotenv import load_dotenv

load_dotenv()  # baca backend/.env bila ada; variabel yang sudah diset (Railway) tidak ditimpa

PRODUKSI = os.getenv("NODE_ENV") == "production" or os.getenv("APP_ENV") == "production"


def _wajib(nama: str) -> str:
    nilai = os.getenv(nama)
    if not nilai:
        raise RuntimeError(f"Variabel lingkungan {nama} belum diisi. Lihat backend/.env.example")
    return nilai


MONGODB_URI = os.getenv("MONGODB_URI") or (
    _wajib("MONGODB_URI") if PRODUKSI else "mongodb://127.0.0.1:27017/?replicaSet=rs0"
)


def _db_dari_uri(uri: str) -> str:
    """Ambil nama database yang tertulis di connection string: .../garam_nias?retryWrites=..."""
    m = re.match(r"^mongodb(?:\+srv)?://[^/]+/([^?/]+)", uri)
    return unquote(m.group(1)) if m else ""


# Nama database: MONGODB_DB, atau yang tertulis di connection string, atau "garam_nias"
DB_NAME = os.getenv("MONGODB_DB") or _db_dari_uri(MONGODB_URI) or "garam_nias"

PORT = int(os.getenv("PORT", "3000"))
JWT_SECRET = os.getenv("JWT_SECRET") or (_wajib("JWT_SECRET") if PRODUKSI else "rahasia-pengembangan")

# DEV_OTP=true: kode WhatsApp ikut dikirim di respons API (HANYA untuk uji coba / demo)
DEV_OTP = os.getenv("DEV_OTP", "").lower() == "true"

# Gateway WhatsApp Fonnte (https://fonnte.com). Kosong = mode uji: pesan hanya dicetak di log.
FONNTE_TOKEN = os.getenv("FONNTE_TOKEN", "")

# Akun pemilik pertama, dibuat otomatis saat server jalan bila nomor ini belum ada
ADMIN_NO_HP = os.getenv("ADMIN_NO_HP", "")
ADMIN_NAMA = os.getenv("ADMIN_NAMA", "Pemilik")

ZONA_WAKTU = "Asia/Jakarta"
