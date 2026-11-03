"""Kirim pesan WhatsApp lewat Fonnte. Tanpa FONNTE_TOKEN pesan hanya dicetak di log (mode uji)."""
import logging

import httpx

from . import config
from .db import db, kini

log = logging.getLogger("garam_nias")

TEMPLATE = {
    "kode_otp": lambda d: f"Kode masuk Garam Nias: *{d['kode']}*\nBerlaku 5 menit. Jangan berikan kode ini kepada siapa pun.",
    "transaksi_ditolak": lambda d: f"Catatan {d['kategori']} Rp {d['jumlah']} perlu diperbaiki: {d['alasan']}",
}


def kirim_wa(no_tujuan: str, template: str, data: dict, terkait: dict | None = None) -> bool:
    """Catat di antrean notifikasi_wa, lalu coba kirim. Mengembalikan True bila terkirim."""
    teks = TEMPLATE[template](data)
    id_ = db.notifikasi_wa.insert_one({
        "no_tujuan": no_tujuan, "template": template,
        "data": {} if template == "kode_otp" else data,  # kode OTP tidak disimpan
        "status": "antre", "terkait": terkait or {}, "percobaan": 0, "dibuat_at": kini(),
    }).inserted_id
    status, galat = "terkirim", None
    try:
        if config.FONNTE_TOKEN:
            r = httpx.post("https://api.fonnte.com/send", headers={"Authorization": config.FONNTE_TOKEN},
                           data={"target": no_tujuan, "message": teks, "countryCode": "62"}, timeout=20)
            j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            if r.status_code >= 400 or j.get("status") is False:
                raise RuntimeError(j.get("reason") or f"HTTP {r.status_code}")
        else:
            log.info("[WA uji] ke %s: %s", no_tujuan, teks.replace("\n", " | "))
    except Exception as e:  # noqa: BLE001 - kegagalan WA tidak boleh menggagalkan permintaan
        status, galat = "gagal", str(e)
        log.error("[WA gagal] %s", galat)
    db.notifikasi_wa.update_one({"_id": id_}, {
        "$set": {"status": status, "galat": galat, "dikirim_at": kini() if status == "terkirim" else None},
        "$inc": {"percobaan": 1},
    })
    return status == "terkirim"
