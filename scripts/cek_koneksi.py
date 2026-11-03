"""Cek koneksi ke database sebelum menjalankan server.

    python scripts/cek_koneksi.py
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pymongo.errors import PyMongoError  # noqa: E402

from app import config  # noqa: E402
from app.db import client, db, sambung  # noqa: E402


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        sambung()
    except PyMongoError:
        return 1
    koleksi = [n for n in db.list_collection_names() if not n.startswith("system.")]
    print(f"Koleksi: {len(koleksi)}")
    if "transaksi" not in koleksi:
        print(f'Database masih kosong. Pasang data demo: mongosh "<connection string>/{config.DB_NAME}" '
              "database/garam_nias_demo_mobile.js")
    else:
        demo = db.pengaturan.find_one({"_id": "data_demo"})
        print(f"Pengguna: {db.pengguna.count_documents({})} · Transaksi: {db.transaksi.count_documents({})} "
              f"({db.transaksi.count_documents({'status': 'menunggu_periksa'})} menunggu diperiksa)"
              f"{' · berisi data DEMO' if demo else ''}")
    print("Koneksi OK. Jalankan server: uvicorn app.main:app --reload --port 3000")
    client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
