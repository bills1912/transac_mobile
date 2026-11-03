"""Koneksi MongoDB dan fungsi bantu yang dipakai semua rute."""
import logging
import re
import sys
from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from bson import Decimal128, ObjectId
from bson.errors import InvalidId
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import ConfigurationError, OperationFailure, PyMongoError

from . import config

log = logging.getLogger("garam_nias")
WIB = ZoneInfo(config.ZONA_WAKTU)

def alamat_aman() -> str:
    """Alamat database untuk log, password diganti ****."""
    return re.sub(r"//([^:@/]+):.*@", r"//\1:****@", config.MONGODB_URI)


def _buat_client() -> MongoClient:
    try:
        # tz_aware=True: tanggal dari database selalu datetime ber-zona (UTC)
        return MongoClient(config.MONGODB_URI, appName="garam-nias-api", serverSelectionTimeoutMS=15000,
                           maxPoolSize=20, retryWrites=True, tz_aware=True)
    except ConfigurationError as e:  # mongodb+srv:// dicek saat itu juga (alamat cluster / format salah)
        print(f"Gagal tersambung ke database {alamat_aman()}\n→ {_jelaskan(e)}", file=sys.stderr)
        sys.exit(1)


def _jelaskan(e: Exception) -> str:
    t = str(e)
    if re.search(r"bad auth|Authentication failed|auth error", t, re.I):
        return ("Username atau password database salah. Cek Database User di Atlas (Database Access) "
                "dan pastikan karakter khusus di password sudah di-encode.")
    if re.search(r"must be escaped", t, re.I):
        return "Password berisi karakter khusus (@ : / ? # %). Encode dulu (mis. @ menjadi %40) atau ganti password database user."
    if re.search(r"Invalid URI|must begin with|Port must be", t, re.I):
        return "Format MONGODB_URI tidak sah. Salin ulang dari Atlas: Clusters → Connect → Drivers."
    if re.search(r"DNS|querySrv|resolution|Name or service not known|nodename", t, re.I):
        return 'Alamat cluster tidak ditemukan. Cek bagian setelah "@" di MONGODB_URI, atau koneksi internet server.'
    if re.search(r"timed out|Timeout|refused|No replica set members|ServerSelectionTimeout", t, re.I):
        return ("Server tidak bisa menjangkau database. Di Atlas, tambahkan IP server ini "
                "(atau 0.0.0.0/0 selama demo) di Network Access.")
    return t


client = _buat_client()
db = client[config.DB_NAME]


def sambung() -> None:
    """Cek koneksi saat server mulai. Gagal → pesan jelas lalu berhenti."""
    try:
        db.command("ping")
    except PyMongoError as e:
        log.error("Gagal tersambung ke database %s", alamat_aman())
        log.error("→ %s", _jelaskan(e))
        raise
    hello = db.command("hello")
    if not hello.get("setName") and hello.get("msg") != "isdbgrid":
        log.warning("PERINGATAN: MongoDB ini bukan replica set; sinkron dari HP akan gagal. "
                    "Pakai Atlas atau jalankan mongod dengan --replSet.")
    log.info('Tersambung ke database "%s" (%s)', config.DB_NAME, alamat_aman().split("?")[0])


# ---------- angka & id ----------
def D(n) -> Decimal128:
    """Uang & jumlah disimpan sebagai Decimal128."""
    return Decimal128(Decimal(str(0 if n is None else n)))


def angka(d) -> float | int:
    """Decimal128 / int → angka biasa (int bila bulat)."""
    if d is None:
        return 0
    x = d.to_decimal() if isinstance(d, Decimal128) else Decimal(str(d))
    return int(x) if x == x.to_integral_value() else float(x)


def oid(s) -> ObjectId | None:
    try:
        return ObjectId(str(s))
    except (InvalidId, TypeError):
        return None


# ---------- waktu ----------
def kini() -> datetime:
    return datetime.now(timezone.utc)


def ke_tanggal(s) -> datetime:
    """'2026-11-03' (atau ISO lengkap) → tengah malam WIB tanggal itu."""
    y, m, d = (int(x) for x in str(s)[:10].split("-"))
    return datetime(y, m, d, tzinfo=WIB)


def parse_waktu(s) -> datetime:
    """Waktu ISO dari HP ('2026-11-03T02:15:00.123456Z') → datetime UTC. Gagal → sekarang."""
    try:
        t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return kini()


def tahun_bulan(t: datetime) -> tuple[int, int]:
    w = t.astimezone(WIB)
    return w.year, w.month


# ---------- transaksi & penomoran ----------
def dalam_transaksi(fn):
    """Jalankan fn(session) di dalam satu transaction MongoDB (butuh replica set; Atlas sudah)."""
    with client.start_session() as sesi:
        return sesi.with_transaction(fn)


def nomor_berikut(prefix: str, tanggal: datetime | None = None, session=None) -> str:
    """Nomor berurutan per bulan: TRX-2611-0001, JU-2611-0001."""
    w = (tanggal or kini()).astimezone(WIB)
    kunci = f"{prefix}-{w.strftime('%y%m')}"
    r = db.penghitung.find_one_and_update(
        {"_id": kunci}, {"$inc": {"n": 1}}, upsert=True, return_document=ReturnDocument.AFTER, session=session
    )
    return f"{kunci}-{r['n']:04d}"


__all__ = ["client", "db", "sambung", "D", "angka", "oid", "kini", "ke_tanggal", "parse_waktu", "tahun_bulan",
           "dalam_transaksi", "nomor_berikut", "OperationFailure", "WIB", "alamat_aman"]
