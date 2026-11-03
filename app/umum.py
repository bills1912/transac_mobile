"""Galat API dan pengubah data MongoDB → JSON untuk aplikasi HP."""
from datetime import datetime, timezone

from bson import Decimal128, ObjectId
from fastapi.encoders import ENCODERS_BY_TYPE
from fastapi.responses import JSONResponse

from .db import angka


class Galat(Exception):
    """Galat yang dikirim ke aplikasi sebagai {"pesan": "..."} dengan kode HTTP tertentu."""

    def __init__(self, status: int, pesan: str, **tambahan):
        super().__init__(pesan)
        self.status = status
        self.pesan = pesan
        self.tambahan = tambahan


def ke_json(v):
    """ObjectId → teks, Decimal128 → angka, tanggal → '2026-11-03T09:07:03.869Z' (sama seperti server Node)."""
    if isinstance(v, dict):
        return {k: ke_json(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [ke_json(x) for x in v]
    if isinstance(v, ObjectId):
        return str(v)
    if isinstance(v, Decimal128):
        return angka(v)
    if isinstance(v, datetime):
        u = (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
        return u.strftime("%Y-%m-%dT%H:%M:%S.") + f"{u.microsecond // 1000:03d}Z"
    return v


class ResponJson(JSONResponse):
    """Respons bawaan semua rute: otomatis mengubah tipe MongoDB menjadi JSON biasa."""

    def render(self, content) -> bytes:
        return super().render(ke_json(content))


# Daftarkan juga ke encoder bawaan FastAPI (dipakai sebelum ResponJson saat rute mengembalikan dict)
ENCODERS_BY_TYPE[ObjectId] = str
ENCODERS_BY_TYPE[Decimal128] = angka
ENCODERS_BY_TYPE[datetime] = ke_json
