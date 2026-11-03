// =====================================================================
//  Garam Nias – Skema MongoDB terpadu (MongoDB 6.0+ / replica set)
//  Dipakai bersama oleh: website publik, back-office web,
//  aplikasi HP Admin, dan aplikasi HP Petugas pencatat.
//
//  Cara pakai:
//    mongosh "mongodb+srv://<user>:<sandi>@<host>/garam_nias" garam_nias_mongodb.js
//  Skrip aman dijalankan ulang: koleksi yang sudah ada hanya diperbarui
//  validatornya, indeks dibuat bila belum ada, data awal tidak digandakan.
//
//  Isi:
//   1. Pengguna dan login       5. Keuangan
//   2. Data master              6. Akuntansi dan laporan
//   3. Pesanan dan pengiriman   7. Sistem
//   4. Produksi dan stok        8. View laporan   9. Data awal
// =====================================================================

// ---------------------------------------------------------------------
// Bantuan
// ---------------------------------------------------------------------
const oid   = { bsonType: 'objectId' };
const str   = { bsonType: 'string' };
const tgl   = { bsonType: 'date' };
const bool  = { bsonType: 'bool' };
const int   = { bsonType: ['int', 'long'] };
const angka = { bsonType: ['decimal', 'int', 'long', 'double'] };          // uang & jumlah: simpan sebagai Decimal128
const opt   = (t) => (t.enum ? { enum: t.enum.concat([null]) }                 // boleh null
                                : Object.assign({}, t, { bsonType: [].concat(t.bsonType, 'null') }));
const en    = (...v) => ({ enum: v });
const arr   = (items, extra = {}) => Object.assign({ bsonType: 'array', items }, extra);
const obj   = (properties, required = []) => Object.assign({ bsonType: 'object', properties }, required.length ? { required } : {});
const ref   = (extra = {}) => obj(Object.assign({ _id: oid, nama: str }, extra), ['_id']); // rujukan + salinan nama
const titik = obj({ type: en('Point'), coordinates: arr(angka, { minItems: 2, maxItems: 2 }) }, ['type', 'coordinates']);
const jejak = { dibuat_at: tgl, diperbarui_at: tgl };

function koleksi(nama, schema, ekstra = {}, opsi = {}) {
  const validator = Object.keys(ekstra).length ? { $and: [{ $jsonSchema: schema }, ekstra] } : { $jsonSchema: schema };
  if (db.getCollectionNames().includes(nama)) {
    db.runCommand({ collMod: nama, validator, validationLevel: 'strict', validationAction: 'error' });
  } else {
    db.createCollection(nama, Object.assign({ validator, validationLevel: 'strict', validationAction: 'error' }, opsi));
  }
  print('koleksi: ' + nama);
}
const idx = (nama, kunci, opsi = {}) => db.getCollection(nama).createIndex(kunci, opsi);
const unikJikaAda = (field) => ({ unique: true, partialFilterExpression: { [field]: { $type: 'string' } } });

// Enum yang dipakai bersama
const PERAN        = en('pemilik', 'admin', 'gudang', 'keuangan', 'petugas');
const KAT_PLG      = en('eceran', 'warung', 'reseller', 'distributor', 'institusi');
const STATUS_BAYAR = en('belum', 'sebagian', 'lunas');
const ARAH         = en('masuk', 'keluar');
const AKTIVITAS    = en('operasi', 'investasi', 'pendanaan');
const LAMPIRAN = obj({
  jenis: en('foto_nota', 'rekaman_suara', 'bukti_terima', 'tanda_tangan', 'foto_uji', 'lainnya'),
  url: str, mime: str, ukuran_byte: int, durasi_detik: int, client_uuid: str, diunggah_oleh: oid, dibuat_at: tgl
}, ['jenis', 'url', 'mime']);
const PEMBAYARAN = obj({ transaksi_id: oid, jumlah: angka, tanggal: tgl }, ['transaksi_id', 'jumlah', 'tanggal']);

// =====================================================================
// 1. PENGGUNA DAN LOGIN
// =====================================================================
koleksi('pengguna', obj(Object.assign({
  nama: str,
  no_hp: { bsonType: 'string', pattern: '^0[0-9]{9,13}$' },   // kunci masuk HP; menentukan peran
  email: opt(str),                                             // opsional, untuk web
  kata_sandi_hash: opt(str),                                   // hanya web
  pin_hash: opt(str),                                          // PIN 4 angka di HP
  peran: PERAN,
  gudang_id: opt(oid),
  foto_url: opt(str),
  aktif: bool,
  perangkat: arr(obj({                                         // HP yang pernah dipakai
    device_id: str, nama_perangkat: str, biometrik_aktif: bool, versi_aplikasi: str,
    terakhir_sinkron_at: opt(tgl), dicabut_at: opt(tgl), didaftarkan_at: tgl
  }, ['device_id', 'biometrik_aktif'])),
  terakhir_masuk_at: opt(tgl),
  dibuat_oleh: opt(oid)
}, jejak), ['nama', 'no_hp', 'peran', 'aktif']));
idx('pengguna', { no_hp: 1 }, { unique: true });
idx('pengguna', { email: 1 }, unikJikaAda('email'));
idx('pengguna', { 'perangkat.device_id': 1 });

koleksi('kode_otp', obj({
  pengguna_id: oid, no_hp: str, kode_hash: str,
  tujuan: en('masuk', 'reset_pin', 'masuk_web'),
  kedaluwarsa_at: tgl, dipakai_at: opt(tgl), percobaan: int, dibuat_at: tgl
}, ['pengguna_id', 'no_hp', 'kode_hash', 'tujuan', 'kedaluwarsa_at', 'percobaan']));
idx('kode_otp', { kedaluwarsa_at: 1 }, { expireAfterSeconds: 0 });   // terhapus otomatis setelah kedaluwarsa
idx('kode_otp', { no_hp: 1, dibuat_at: -1 });

koleksi('sesi', obj({
  pengguna_id: oid, device_id: opt(str), kanal: en('web', 'hp'),
  refresh_token_hash: str, kedaluwarsa_at: tgl, dicabut_at: opt(tgl), ip: opt(str), dibuat_at: tgl
}, ['pengguna_id', 'kanal', 'refresh_token_hash', 'kedaluwarsa_at']));
idx('sesi', { refresh_token_hash: 1 }, { unique: true });
idx('sesi', { kedaluwarsa_at: 1 }, { expireAfterSeconds: 0 });
idx('sesi', { pengguna_id: 1 });

// =====================================================================
// 2. DATA MASTER
// =====================================================================
koleksi('gudang', obj(Object.assign({
  nama: str, alamat: opt(str), kabupaten: opt(str), lokasi: titik, aktif: bool
}, jejak), ['nama', 'aktif']));

koleksi('wilayah', obj({
  nama: str, kabupaten: str, cara_kirim: en('darat', 'kapal'),
  jadwal_kirim: opt(str), ongkir_dasar: angka, aktif: bool
}, ['nama', 'kabupaten', 'cara_kirim', 'aktif']));
idx('wilayah', { nama: 1 }, { unique: true });

koleksi('barang', obj(Object.assign({
  kode: str, nama: str,
  jenis: en('produk_jadi', 'bahan_baku', 'kemasan'),
  satuan: str, berat_gram: opt(int), stok_minimum: angka,
  harga_eceran: opt(angka), deskripsi: opt(str), foto_url: opt(str),
  tampil_di_web: bool, aktif: bool,
  harga: arr(obj({                                             // harga bertingkat (disematkan)
    kategori: KAT_PLG, qty_minimal: angka, harga: angka, berlaku_mulai: tgl, berlaku_sampai: opt(tgl)
  }, ['kategori', 'qty_minimal', 'harga', 'berlaku_mulai']))
}, jejak), ['kode', 'nama', 'jenis', 'satuan', 'stok_minimum', 'tampil_di_web', 'aktif']));
idx('barang', { kode: 1 }, { unique: true });
idx('barang', { jenis: 1, aktif: 1 });

koleksi('pelanggan', obj(Object.assign({
  nama: str, kategori: KAT_PLG, no_wa: opt(str), alamat: opt(str),
  wilayah: ref(), lokasi: titik,
  tempo_hari: int, limit_piutang: opt(angka), catatan: opt(str), aktif: bool
}, jejak), ['nama', 'kategori', 'tempo_hari', 'aktif']));
idx('pelanggan', { no_wa: 1 }, unikJikaAda('no_wa'));        // pesanan web/WA tidak membuat pelanggan ganda
idx('pelanggan', { 'wilayah._id': 1 });
idx('pelanggan', { lokasi: '2dsphere' });                     // peta sebaran pelanggan

koleksi('mitra_tambak', obj({
  nama: str, no_hp: opt(str), desa: opt(str), kabupaten: opt(str),
  lokasi: titik, luas_ha: opt(angka), aktif: bool, dibuat_at: tgl
}, ['nama', 'aktif']));
idx('mitra_tambak', { lokasi: '2dsphere' });

// =====================================================================
// 3. PESANAN DAN PENGIRIMAN
// =====================================================================
const STATUS_PESANAN = en('baru', 'dikonfirmasi', 'dikemas', 'dikirim', 'selesai', 'batal');
koleksi('pesanan', obj(Object.assign({
  nomor: str,                                                  // GN-0142
  pelanggan: ref({ kategori: KAT_PLG, no_wa: opt(str) }),      // salinan saat pesan dibuat
  sumber: en('website', 'whatsapp', 'admin', 'portal', 'hp'),
  status: STATUS_PESANAN,
  tanggal: tgl,
  gudang_id: opt(oid),
  wilayah: ref(),
  alamat_kirim: opt(str),
  items: arr(obj({
    barang_id: oid, kode: str, nama: str, qty: angka, harga_satuan: angka, subtotal: angka, batch_kode: opt(str)
  }, ['barang_id', 'kode', 'nama', 'qty', 'harga_satuan', 'subtotal']), { minItems: 1 }),
  subtotal: angka, potongan: angka, ongkir: angka, total: angka,
  metode_bayar: en('tunai', 'transfer', 'qris', 'tempo'),
  jatuh_tempo: opt(tgl),
  status_bayar: STATUS_BAYAR,
  dibayar: angka,
  pembayaran: arr(PEMBAYARAN),                                 // cicilan / pelunasan
  riwayat: arr(obj({ dari: opt(STATUS_PESANAN), ke: STATUS_PESANAN, oleh: opt(oid), waktu: tgl, catatan: opt(str) }, ['ke', 'waktu'])),
  catatan: opt(str),
  client_uuid: opt(str),                                       // cegah dobel saat kirim ulang dari HP
  dibuat_oleh: opt(oid)
}, jejak), ['nomor', 'pelanggan', 'sumber', 'status', 'tanggal', 'items', 'subtotal', 'potongan', 'ongkir', 'total', 'metode_bayar', 'status_bayar', 'dibayar']),
{
  $expr: { $eq: ['$total', { $add: [{ $subtract: ['$subtotal', '$potongan'] }, '$ongkir'] }] },   // total selalu konsisten
  $or: [{ metode_bayar: { $ne: 'tempo' } }, { jatuh_tempo: { $type: 'date' } }]                    // tempo wajib jatuh tempo
});
idx('pesanan', { nomor: 1 }, { unique: true });
idx('pesanan', { client_uuid: 1 }, unikJikaAda('client_uuid'));
idx('pesanan', { status: 1, tanggal: -1 });
idx('pesanan', { 'pelanggan._id': 1, tanggal: -1 });
idx('pesanan', { status_bayar: 1, jatuh_tempo: 1 }, { partialFilterExpression: { status_bayar: { $in: ['belum', 'sebagian'] } } });
idx('pesanan', { diperbarui_at: 1 });

koleksi('pengiriman', obj({
  kode: str, tanggal: tgl, wilayah: ref(),
  moda: en('pikap', 'truk', 'kapal', 'ambil_sendiri'), nama_kapal: opt(str),
  kurir: ref(), status: en('dijadwalkan', 'berangkat', 'selesai', 'batal'),
  antaran: arr(obj({
    pesanan_id: oid, nomor: str, pelanggan_nama: str, urutan: int,
    diterima_at: opt(tgl), nama_penerima: opt(str), tunai_diterima: angka, bukti: arr(LAMPIRAN)
  }, ['pesanan_id', 'nomor', 'tunai_diterima'])),
  setoran: obj({                                               // setoran tunai kurir
    tagihan_tunai: angka, disetor: angka, selisih: angka, tanggal: tgl,
    transaksi_id: opt(oid), diverifikasi_oleh: opt(oid), diverifikasi_at: opt(tgl)
  }, ['tagihan_tunai', 'disetor', 'selisih']),
  catatan: opt(str), dibuat_at: tgl
}, ['kode', 'tanggal', 'moda', 'status', 'antaran']));
idx('pengiriman', { kode: 1 }, { unique: true });
idx('pengiriman', { tanggal: -1 });
idx('pengiriman', { 'kurir._id': 1, tanggal: -1 });
idx('pengiriman', { 'antaran.pesanan_id': 1 });

// =====================================================================
// 4. PRODUKSI DAN STOK
// =====================================================================
koleksi('panen', obj({
  mitra: ref(), gudang_id: oid, tanggal: tgl,
  berat_kg: angka, kualitas: opt(str), harga_per_kg: angka, total: angka,
  status_bayar: STATUS_BAYAR, dibayar: angka, pembayaran: arr(PEMBAYARAN),
  dibuat_oleh: opt(oid), dibuat_at: tgl
}, ['mitra', 'gudang_id', 'tanggal', 'berat_kg', 'harga_per_kg', 'total', 'status_bayar', 'dibayar']),
{ $expr: { $eq: ['$total', { $multiply: ['$berat_kg', '$harga_per_kg'] }] } });
idx('panen', { 'mitra._id': 1, tanggal: -1 });
idx('panen', { status_bayar: 1 }, { partialFilterExpression: { status_bayar: { $in: ['belum', 'sebagian'] } } });

const BARIS_BARANG = obj({ barang_id: oid, kode: str, qty: angka }, ['barang_id', 'kode', 'qty']);
koleksi('batch_produksi', obj({
  kode_batch: str,                                             // dicetak di kemasan: B2610-07
  gudang_id: oid, tanggal_mulai: tgl, tanggal_selesai: opt(tgl),
  status: en('proses', 'selesai', 'ditolak'),
  bahan: arr(BARIS_BARANG), hasil: arr(BARIS_BARANG),
  uji_yodium: arr(obj({ tanggal: tgl, kadar_ppm: angka, lulus: bool, penguji: opt(str), foto: opt(LAMPIRAN) }, ['tanggal', 'kadar_ppm', 'lulus'])),
  catatan: opt(str), dibuat_oleh: opt(oid), dibuat_at: tgl
}, ['kode_batch', 'gudang_id', 'tanggal_mulai', 'status']));
idx('batch_produksi', { kode_batch: 1 }, { unique: true });
idx('batch_produksi', { status: 1, tanggal_mulai: -1 });

// Buku besar stok: setiap keluar/masuk = satu dokumen (qty bertanda)
koleksi('mutasi_stok', obj({
  gudang_id: oid, barang_id: oid, barang_kode: str, batch_kode: opt(str),
  tanggal: tgl, qty: angka, nilai: opt(angka),
  sumber: en('pesanan', 'produksi_bahan', 'produksi_hasil', 'pembelian', 'panen', 'penyesuaian', 'pindah_gudang'),
  sumber_id: opt(oid), catatan: opt(str), dibuat_oleh: opt(oid)
}, ['gudang_id', 'barang_id', 'barang_kode', 'tanggal', 'qty', 'sumber']),
{ qty: { $ne: 0 } });
idx('mutasi_stok', { gudang_id: 1, barang_id: 1, tanggal: -1 });
idx('mutasi_stok', { sumber: 1, sumber_id: 1 });

// Saldo stok terkini (diperbarui dengan $inc dalam transaksi yang sama dengan mutasi_stok)
koleksi('stok', obj({
  gudang_id: oid, barang_id: oid, barang_kode: str, barang_nama: str, satuan: str,
  jumlah: angka, nilai: angka, stok_minimum: angka, diperbarui_at: tgl
}, ['gudang_id', 'barang_id', 'barang_kode', 'jumlah', 'stok_minimum']));
idx('stok', { gudang_id: 1, barang_id: 1 }, { unique: true });

// =====================================================================
// 5. KEUANGAN
// =====================================================================
koleksi('akun_kas', obj({
  nama: str, jenis: en('kas', 'bank', 'dompet_digital'), no_rekening: opt(str), akun_kode: str, aktif: bool
}, ['nama', 'jenis', 'akun_kode', 'aktif']));
idx('akun_kas', { nama: 1 }, { unique: true });

// Satu daftar kategori; sebagian tampil di HP petugas dengan label sederhana. Tag disematkan.
koleksi('kategori_transaksi', obj({
  arah: ARAH, nama: str, label_petugas: opt(str), ikon: opt(str), warna: opt(str),
  tampil_petugas: bool, akun_kode: str, aktivitas: AKTIVITAS, urutan: int, aktif: bool,
  tags: arr(obj({ _id: oid, nama: str, aktif: bool }, ['_id', 'nama', 'aktif']))
}, ['arah', 'nama', 'tampil_petugas', 'akun_kode', 'aktivitas', 'aktif', 'tags']));
idx('kategori_transaksi', { arah: 1, nama: 1 }, { unique: true });

// "Lebih dari Satu Transaksi": satu kiriman dari HP petugas
koleksi('kiriman_petugas', obj({
  petugas: ref(), arah: ARAH, jumlah_transaksi: int, total: angka,
  dikirim_at: tgl, diterima_at: tgl, client_uuid: str
}, ['petugas', 'arah', 'jumlah_transaksi', 'total', 'dikirim_at', 'client_uuid']));
idx('kiriman_petugas', { client_uuid: 1 }, { unique: true });
idx('kiriman_petugas', { 'petugas._id': 1, dikirim_at: -1 });

const STATUS_TRX = en('draf', 'menunggu_periksa', 'disetujui', 'ditolak');
koleksi('transaksi', obj(Object.assign({
  nomor: str,                                                  // TRX-2610-0548
  tanggal: tgl,
  arah: ARAH,
  kategori: ref({ label_petugas: opt(str), akun_kode: str, aktivitas: AKTIVITAS }),
  akun_kas: ref({ akun_kode: str }),
  jumlah: angka,
  keterangan: opt(str),
  status: STATUS_TRX,
  sumber: en('hp_petugas', 'hp_admin', 'web', 'pesanan', 'setoran_kurir', 'panen', 'sistem'),
  tanpa_nota: bool,
  tags: arr(obj({ _id: oid, nama: str }, ['_id', 'nama'])),   // diisi admin saat memeriksa
  lampiran: arr(LAMPIRAN),                                     // foto nota, rekaman suara (file di object storage)
  terkait: obj({ pesanan_id: opt(oid), pelanggan_id: opt(oid), panen_id: opt(oid), pengiriman_id: opt(oid) }),
  kiriman_id: opt(oid),
  dicatat_oleh: ref({ peran: PERAN }),
  dicatat_at: tgl,                                             // waktu di HP (bisa offline)
  pemeriksaan: obj({ oleh: ref(), at: tgl, alasan_tolak: opt(str) }, ['oleh', 'at']),
  jurnal_id: opt(oid),
  client_uuid: opt(str)
}, jejak), ['nomor', 'tanggal', 'arah', 'kategori', 'akun_kas', 'jumlah', 'status', 'sumber', 'tanpa_nota', 'tags', 'lampiran', 'dicatat_oleh', 'dicatat_at']),
{
  jumlah: { $gt: 0 },
  $or: [{ status: { $ne: 'ditolak' } }, { 'pemeriksaan.alasan_tolak': { $type: 'string' } }]    // tolak wajib beralasan
});
idx('transaksi', { nomor: 1 }, { unique: true });
idx('transaksi', { client_uuid: 1 }, unikJikaAda('client_uuid'));
idx('transaksi', { status: 1, dibuat_at: -1 }, { partialFilterExpression: { status: 'menunggu_periksa' } });
idx('transaksi', { tanggal: 1 });
idx('transaksi', { 'kategori._id': 1, tanggal: 1 });
idx('transaksi', { 'tags._id': 1 });
idx('transaksi', { 'dicatat_oleh._id': 1, dicatat_at: -1 });
idx('transaksi', { kiriman_id: 1 });
idx('transaksi', { diperbarui_at: 1 });                        // sinkron HP

// =====================================================================
// 6. AKUNTANSI DAN LAPORAN
// =====================================================================
const TIPE_AKUN = en('aset', 'kewajiban', 'ekuitas', 'pendapatan', 'hpp', 'beban', 'pendapatan_lain', 'beban_lain');
koleksi('akun', obj({
  kode: str, nama: str, tipe: TIPE_AKUN, kelompok: str,
  saldo_normal: en('D', 'K'), is_kas: bool, aktif: bool, urutan: int
}, ['kode', 'nama', 'tipe', 'kelompok', 'saldo_normal', 'is_kas', 'aktif']));
idx('akun', { kode: 1 }, { unique: true });

koleksi('periode', obj({
  tahun: int, bulan: { bsonType: 'int', minimum: 1, maximum: 12 }, mulai: tgl, selesai: tgl,
  status: en('terbuka', 'ditutup'), ditutup_oleh: opt(oid), ditutup_at: opt(tgl)
}, ['tahun', 'bulan', 'mulai', 'selesai', 'status']));
idx('periode', { tahun: 1, bulan: 1 }, { unique: true });

// Jurnal dibuat OTOMATIS oleh backend; baris disematkan dan WAJIB seimbang (dicek validator)
koleksi('jurnal', obj({
  nomor: str, tanggal: tgl,
  periode: obj({ tahun: int, bulan: int }, ['tahun', 'bulan']),
  keterangan: str,
  sumber: obj({ koleksi: str, id: opt(oid) }, ['koleksi']),    // transaksi | pesanan | panen | batch_produksi | aset_tetap | manual
  otomatis: bool,
  baris: arr(obj({
    akun_kode: str, akun_nama: str, akun_tipe: TIPE_AKUN, is_kas: bool,
    debit: angka, kredit: angka, aktivitas: opt(AKTIVITAS), keterangan: opt(str)
  }, ['akun_kode', 'akun_tipe', 'is_kas', 'debit', 'kredit']), { minItems: 2 }),
  dibuat_oleh: opt(oid), dibuat_at: tgl
}, ['nomor', 'tanggal', 'periode', 'keterangan', 'sumber', 'otomatis', 'baris']),
{ $expr: { $eq: [{ $sum: '$baris.debit' }, { $sum: '$baris.kredit' }] } });
idx('jurnal', { nomor: 1 }, { unique: true });
idx('jurnal', { 'sumber.koleksi': 1, 'sumber.id': 1 }, { unique: true, partialFilterExpression: { otomatis: true, 'sumber.id': { $type: 'objectId' } } });
idx('jurnal', { 'periode.tahun': 1, 'periode.bulan': 1 });
idx('jurnal', { tanggal: 1 });
idx('jurnal', { 'baris.akun_kode': 1 });

koleksi('aset_tetap', obj({
  nama: str, akun_kode: str, tanggal_beli: tgl, harga_perolehan: angka,
  umur_bulan: int, nilai_sisa: angka, transaksi_id: opt(oid), aktif: bool
}, ['nama', 'akun_kode', 'tanggal_beli', 'harga_perolehan', 'umur_bulan', 'nilai_sisa', 'aktif']));

koleksi('arsip_laporan', obj({
  jenis: en('laba_rugi', 'neraca', 'arus_kas', 'paket_bulanan', 'ringkasan_mingguan'),
  mulai: tgl, selesai: tgl, status: en('draf', 'final'),
  ringkasan: { bsonType: 'object' }, file_pdf_url: opt(str), file_xlsx_url: opt(str),
  dibuat_at: tgl, difinalkan_oleh: opt(oid), dikirim_at: opt(tgl)
}, ['jenis', 'mulai', 'selesai', 'status', 'dibuat_at']));
idx('arsip_laporan', { jenis: 1, mulai: -1 });

koleksi('jadwal_laporan', obj({
  jenis: en('laba_rugi', 'neraca', 'arus_kas', 'paket_bulanan', 'ringkasan_mingguan'),
  cron: str,                                                   // '0 7 1 * *' = tanggal 1 pukul 07.00
  kanal: arr(en('wa', 'email'), { minItems: 1 }),
  penerima: ref(), aktif: bool
}, ['jenis', 'cron', 'kanal', 'penerima', 'aktif']));

// =====================================================================
// 7. SISTEM
// =====================================================================
koleksi('notifikasi_wa', obj({
  no_tujuan: str,
  template: str,                                               // kode_otp | status_pesanan | pengingat_tagihan | laporan_bulanan
  data: { bsonType: 'object' },
  status: en('antre', 'terkirim', 'gagal'),
  terkait: obj({ koleksi: str, id: opt(oid) }),
  percobaan: int, galat: opt(str), dibuat_at: tgl, dikirim_at: opt(tgl)
}, ['no_tujuan', 'template', 'status', 'percobaan', 'dibuat_at']));
idx('notifikasi_wa', { status: 1, dibuat_at: 1 }, { partialFilterExpression: { status: 'antre' } });

koleksi('log_audit', obj({
  pengguna_id: opt(oid), aksi: str, koleksi: str, dok_id: opt(oid),
  sebelum: { bsonType: ['object', 'null'] }, sesudah: { bsonType: ['object', 'null'] },
  ip: opt(str), waktu: tgl
}, ['aksi', 'koleksi', 'waktu']));
idx('log_audit', { koleksi: 1, dok_id: 1, waktu: -1 });
idx('log_audit', { pengguna_id: 1, waktu: -1 });

koleksi('pengaturan', obj({ _id: str, nilai: {}, diperbarui_oleh: opt(oid), diperbarui_at: tgl }, ['_id', 'nilai']));

// =====================================================================
// 8. VIEW LAPORAN (dibaca langsung oleh back-office & HP Admin)
// =====================================================================
function view(nama, sumber, pipeline) {
  if (db.getCollectionNames().includes(nama)) db.getCollection(nama).drop();
  db.createView(nama, sumber, pipeline);
  print('view: ' + nama);
}

// Piutang pelanggan
view('v_piutang', 'pesanan', [
  { $match: { status: { $ne: 'batal' }, status_bayar: { $in: ['belum', 'sebagian'] } } },
  { $project: {
      nomor: 1, pelanggan: 1, total: 1, dibayar: 1, jatuh_tempo: 1,
      sisa: { $subtract: ['$total', '$dibayar'] },
      hari_terlambat: { $max: [0, { $dateDiff: { startDate: '$jatuh_tempo', endDate: '$$NOW', unit: 'day' } }] } } },
  { $sort: { hari_terlambat: -1 } }
]);

// Stok di bawah minimum
view('v_stok_menipis', 'stok', [
  { $match: { $expr: { $lt: ['$jumlah', '$stok_minimum'] } } }
]);

// Laba rugi per bulan per akun (nilai = kredit − debit: pendapatan positif, biaya negatif)
view('v_laba_rugi_bulanan', 'jurnal', [
  { $unwind: '$baris' },
  { $match: { 'baris.akun_tipe': { $in: ['pendapatan', 'hpp', 'beban', 'pendapatan_lain', 'beban_lain'] } } },
  { $group: {
      _id: { tahun: '$periode.tahun', bulan: '$periode.bulan', akun_kode: '$baris.akun_kode', akun_nama: '$baris.akun_nama', tipe: '$baris.akun_tipe' },
      nilai: { $sum: { $subtract: ['$baris.kredit', '$baris.debit'] } } } },
  { $sort: { '_id.tahun': 1, '_id.bulan': 1, '_id.akun_kode': 1 } }
]);

// Arus kas per bulan per aktivitas (metode langsung: semua baris pada akun kas/bank)
view('v_arus_kas_bulanan', 'jurnal', [
  { $unwind: '$baris' },
  { $match: { 'baris.is_kas': true } },
  { $group: {
      _id: { tahun: '$periode.tahun', bulan: '$periode.bulan', aktivitas: '$baris.aktivitas' },
      arus: { $sum: { $subtract: ['$baris.debit', '$baris.kredit'] } } } },
  { $sort: { '_id.tahun': 1, '_id.bulan': 1 } }
]);

// Rincian transaksi per kategori dan tag (layar HP Admin "Transaksi per kategori")
view('v_transaksi_per_tag', 'transaksi', [
  { $match: { status: 'disetujui' } },
  { $unwind: { path: '$tags', preserveNullAndEmptyArrays: true } },
  { $group: {
      _id: { bulan: { $dateTrunc: { date: '$tanggal', unit: 'month', timezone: 'Asia/Jakarta' } }, arah: '$arah', kategori: '$kategori.nama', tag: '$tags.nama' },
      jumlah_transaksi: { $sum: 1 }, total: { $sum: '$jumlah' } } },
  { $sort: { '_id.bulan': -1, total: -1 } }
]);

// Neraca butuh saldo kumulatif sampai tanggal tertentu, jadi dijalankan sebagai aggregation berparameter:
//   db.jurnal.aggregate(pipelineNeraca(ISODate('2026-10-31T23:59:59+07:00')))
globalThis.pipelineNeraca = (sampai) => [
  { $match: { tanggal: { $lte: sampai } } },
  { $unwind: '$baris' },
  { $group: { _id: { akun_kode: '$baris.akun_kode', akun_nama: '$baris.akun_nama', tipe: '$baris.akun_tipe' },
              debit: { $sum: '$baris.debit' }, kredit: { $sum: '$baris.kredit' } } },
  { $lookup: { from: 'akun', localField: '_id.akun_kode', foreignField: 'kode', as: 'akun' } },
  { $set: { akun: { $first: '$akun' } } },
  { $project: { _id: 0, kode: '$_id.akun_kode', nama: '$_id.akun_nama', tipe: '$_id.tipe', kelompok: '$akun.kelompok',
      saldo: { $cond: [{ $eq: ['$akun.saldo_normal', 'D'] }, { $subtract: ['$debit', '$kredit'] }, { $subtract: ['$kredit', '$debit'] }] } } },
  { $sort: { kode: 1 } }
  // Akun pendapatan & biaya ikut terhitung; jumlahkan sebagai "Laba berjalan" di bagian ekuitas.
];

// =====================================================================
// 9. DATA AWAL (hanya diisi bila koleksi masih kosong)
// =====================================================================
const D = (v) => NumberDecimal(String(v));
const kini = new Date();
function isiSekali(nama, docs) {
  if (db.getCollection(nama).countDocuments() === 0) {
    db.getCollection(nama).insertMany(docs);
    print('data awal: ' + nama + ' (' + docs.length + ')');
  }
}

isiSekali('akun', [
  ['1-1100', 'Kas', 'aset', 'aset_lancar', 'D', true],
  ['1-1200', 'Bank BRI', 'aset', 'aset_lancar', 'D', true],
  ['1-1300', 'Saldo QRIS', 'aset', 'aset_lancar', 'D', true],
  ['1-1400', 'Piutang usaha', 'aset', 'aset_lancar', 'D', false],
  ['1-1500', 'Persediaan garam jadi', 'aset', 'aset_lancar', 'D', false],
  ['1-1600', 'Persediaan bahan baku dan kemasan', 'aset', 'aset_lancar', 'D', false],
  ['1-2100', 'Kendaraan', 'aset', 'aset_tetap', 'D', false],
  ['1-2200', 'Peralatan produksi', 'aset', 'aset_tetap', 'D', false],
  ['1-2300', 'Gudang dan bangunan', 'aset', 'aset_tetap', 'D', false],
  ['1-2900', 'Akumulasi penyusutan', 'aset', 'aset_tetap', 'K', false],
  ['2-1100', 'Utang ke mitra tambak', 'kewajiban', 'kewajiban_pendek', 'K', false],
  ['2-1200', 'Utang pemasok', 'kewajiban', 'kewajiban_pendek', 'K', false],
  ['2-1300', 'Utang pajak', 'kewajiban', 'kewajiban_pendek', 'K', false],
  ['2-2100', 'Pinjaman KUR', 'kewajiban', 'kewajiban_panjang', 'K', false],
  ['3-1000', 'Modal pemilik', 'ekuitas', 'ekuitas', 'K', false],
  ['3-2000', 'Laba ditahan', 'ekuitas', 'ekuitas', 'K', false],
  ['3-3000', 'Prive pemilik', 'ekuitas', 'ekuitas', 'D', false],
  ['4-1000', 'Penjualan garam', 'pendapatan', 'pendapatan', 'K', false],
  ['4-1900', 'Retur dan potongan penjualan', 'pendapatan', 'pendapatan', 'D', false],
  ['5-1000', 'HPP garam', 'hpp', 'hpp', 'D', false],
  ['6-1000', 'Transportasi dan ongkos kapal', 'beban', 'beban_operasional', 'D', false],
  ['6-2000', 'Gaji dan upah', 'beban', 'beban_operasional', 'D', false],
  ['6-3000', 'Listrik, air, dan telepon', 'beban', 'beban_operasional', 'D', false],
  ['6-4000', 'Perawatan tambak', 'beban', 'beban_operasional', 'D', false],
  ['6-5000', 'Operasional lain', 'beban', 'beban_operasional', 'D', false],
  ['6-6000', 'Penyusutan', 'beban', 'beban_operasional', 'D', false],
  ['7-1000', 'Pendapatan lain', 'pendapatan_lain', 'lain', 'K', false],
  ['7-2000', 'Beban lain dan administrasi bank', 'beban_lain', 'lain', 'D', false],
  ['7-3000', 'PPh final UMKM', 'beban_lain', 'lain', 'D', false]
].map((a, i) => ({ kode: a[0], nama: a[1], tipe: a[2], kelompok: a[3], saldo_normal: a[4], is_kas: a[5], aktif: true, urutan: NumberInt(i + 1) })));

isiSekali('akun_kas', [
  { nama: 'Kas', jenis: 'kas', akun_kode: '1-1100', aktif: true },
  { nama: 'BRI', jenis: 'bank', akun_kode: '1-1200', aktif: true },
  { nama: 'QRIS', jenis: 'dompet_digital', akun_kode: '1-1300', aktif: true }
]);

const kat = (arah, nama, label, ikon, warna, akun, aktivitas, urutan, tags) => ({
  arah, nama, label_petugas: label, ikon, warna, tampil_petugas: label !== null, akun_kode: akun,
  aktivitas, urutan: NumberInt(urutan), aktif: true,
  tags: tags.map((t) => ({ _id: new ObjectId(), nama: t, aktif: true }))
});
isiSekali('kategori_transaksi', [
  kat('keluar', 'Bahan baku', 'Beli garam', 'garam', '#0F766E', '1-1600', 'operasi', 1, ['Garam krosok', 'Kalium iodat (KIO₃)']),
  kat('keluar', 'Kemasan', 'Plastik & karung', 'kemasan', '#1D4ED8', '1-1600', 'operasi', 2, ['Plastik 250 g', 'Plastik 500 g', 'Karung 50 kg', 'Label']),
  kat('keluar', 'Gaji & upah', 'Gaji & upah', 'orang', '#B45309', '6-2000', 'operasi', 3, ['Upah harian pengemas', 'Upah panen petambak', 'Gaji bulanan', 'Lembur']),
  kat('keluar', 'Transportasi & kapal', 'Bensin & kapal', 'kapal', '#7C3AED', '6-1000', 'operasi', 4, ['BBM', 'Ongkos kapal', 'Sewa truk', 'Bongkar muat']),
  kat('keluar', 'Perawatan tambak', 'Obat tambak', 'tetes', '#BE185D', '6-4000', 'operasi', 5, ['Pestisida & obat', 'Terpal', 'Perbaikan pematang']),
  kat('keluar', 'Operasional', 'Lainnya', 'titik', '#4B5D68', '6-5000', 'operasi', 6, ['Listrik & air', 'Pulsa & internet', 'Lain-lain']),
  kat('keluar', 'Peralatan & aset', null, 'alat', '#0E2A3B', '1-2200', 'investasi', 7, []),
  kat('keluar', 'Angsuran pinjaman', null, 'bank', '#0E2A3B', '2-2100', 'pendanaan', 8, []),
  kat('keluar', 'Prive pemilik', null, 'orang', '#0E2A3B', '3-3000', 'pendanaan', 9, []),
  kat('masuk', 'Penjualan', 'Jual garam', 'garam', '#0F766E', '4-1000', 'operasi', 1, ['Garam halus', 'Garam kasar', 'Garam karung']),
  kat('masuk', 'Pelunasan piutang', 'Bayar utang pelanggan', 'uang', '#1D4ED8', '1-1400', 'operasi', 2, ['Warung', 'Reseller', 'Distributor']),
  kat('masuk', 'Modal masuk', null, 'bank', '#7C3AED', '3-1000', 'pendanaan', 3, []),
  kat('masuk', 'Pemasukan lain', 'Lainnya', 'titik', '#4B5D68', '7-1000', 'operasi', 4, ['Bunga bank', 'Jual karung bekas'])
]);

isiSekali('wilayah', [
  ['Kota Gunungsitoli', 'Kota Gunungsitoli', 'darat', 'Antar langsung setiap hari'],
  ['Kabupaten Nias', 'Nias', 'darat', 'Rute mingguan'],
  ['Nias Utara', 'Nias Utara', 'darat', 'Rute mingguan'],
  ['Nias Barat', 'Nias Barat', 'darat', 'Rute mingguan'],
  ['Nias Selatan', 'Nias Selatan', 'darat', 'Rute mingguan'],
  ['Kepulauan Batu', 'Nias Selatan', 'kapal', 'Kapal dari Teluk Dalam, jadwal [hari]']
].map((w) => ({ nama: w[0], kabupaten: w[1], cara_kirim: w[2], jadwal_kirim: w[3], ongkir_dasar: D(0), aktif: true })));

isiSekali('gudang', [{ nama: 'Gudang Gunungsitoli', kabupaten: 'Kota Gunungsitoli', aktif: true, dibuat_at: kini, diperbarui_at: kini }]);

isiSekali('barang', [
  ['GH-250', 'Garam halus beryodium 250 g', 'produk_jadi', 'pak', 250, 800, true],
  ['GH-500', 'Garam halus beryodium 500 g', 'produk_jadi', 'pak', 500, 700, true],
  ['GK-1K', 'Garam kasar 1 kg', 'produk_jadi', 'pak', 1000, 400, true],
  ['GR-50K', 'Garam karung 50 kg', 'produk_jadi', 'karung', 50000, 30, true],
  ['KRS', 'Garam krosok', 'bahan_baku', 'kg', null, 3000, false],
  ['KIO3', 'Kalium iodat (KIO₃)', 'bahan_baku', 'kg', null, 2.5, false],
  ['PLS-250', 'Plastik kemasan 250 g', 'kemasan', 'lembar', null, 1000, false],
  ['PLS-500', 'Plastik kemasan 500 g', 'kemasan', 'lembar', null, 1000, false],
  ['KRG-50', 'Karung 50 kg', 'kemasan', 'lembar', null, 100, false]
].map((b) => ({
  kode: b[0], nama: b[1], jenis: b[2], satuan: b[3], berat_gram: b[4] === null ? null : NumberInt(b[4]),
  stok_minimum: D(b[5]), tampil_di_web: b[6], aktif: true, harga: [], dibuat_at: kini, diperbarui_at: kini
})));

isiSekali('pengaturan', [
  { _id: 'nama_usaha', nilai: '[Nama Usaha]', diperbarui_at: kini },
  { _id: 'no_wa_usaha', nilai: '[nomor WA]', diperbarui_at: kini },
  { _id: 'pph_umkm_persen', nilai: D('0.5'), diperbarui_at: kini },
  { _id: 'format_nomor_pesanan', nilai: 'GN-{0000}', diperbarui_at: kini },
  { _id: 'zona_waktu', nilai: 'Asia/Jakarta', diperbarui_at: kini }
]);

print('Selesai: ' + db.getCollectionNames().length + ' koleksi dan view.');
