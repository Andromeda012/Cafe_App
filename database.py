import os
import sqlite3

from werkzeug.security import generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_PATH = os.environ.get("NOIR_DATABASE_PATH", os.path.join(BASE_DIR, "stok_listesi.db"))

DEFAULT_TABLES = [
    ("A1", "Salon"), ("A2", "Salon"), ("A3", "Salon"),
    ("A4", "Salon"), ("A5", "Salon"), ("A6", "Salon"),
    ("B1", "Bahçe"), ("B2", "Bahçe"), ("B3", "Bahçe"),
    ("B4", "Bahçe"), ("B5", "Bahçe"), ("B6", "Bahçe"),
]


def connect_database():
    conn = sqlite3.connect(DATABASE_PATH, timeout=15)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn, conn.cursor()


def _table_exists(cursor, table_name):
    cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    )
    return cursor.fetchone() is not None


def _column_names(cursor, table_name):
    cursor.execute(f'PRAGMA table_info("{table_name}")')
    return [row[1] for row in cursor.fetchall()]


def create_stock_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS stok_listesi (
            stok_kodu TEXT PRIMARY KEY,
            stok_adı TEXT NOT NULL,
            fiyat INTEGER NOT NULL,
            adet INTEGER DEFAULT 0
        )
        """
    )


def create_tables_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS masalar (
            masa_kodu TEXT PRIMARY KEY,
            bolge TEXT NOT NULL,
            aktif INTEGER NOT NULL DEFAULT 1
                CHECK (aktif IN (0, 1))
        )
        """
    )


def _create_new_order_tables(cursor):
    # Kullanıcının tercih ettiği isimlendirme:
    # siparis_detaylari = siparişin genel/müşteri bilgileri
    # siparis = siparişin ürün satırları
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS siparis_detaylari (
            siparis_id INTEGER PRIMARY KEY AUTOINCREMENT,
            guest_id TEXT NOT NULL,
            musteri_adi TEXT NOT NULL,
            telefon TEXT NOT NULL,
            masa_bilgisi TEXT NOT NULL,
            toplam_tutar REAL NOT NULL,
            siparis_durumu TEXT NOT NULL,
            siparis_tarihi TEXT NOT NULL,
            notlar TEXT,
            servis_turu TEXT NOT NULL DEFAULT 'Garson Servisi',
            servis_ucreti REAL NOT NULL DEFAULT 0,
            servis_ucreti_odendi INTEGER NOT NULL DEFAULT 0 CHECK (servis_ucreti_odendi IN (0, 1)),
            odeme_yontemi TEXT NOT NULL DEFAULT 'Belirlenmedi',
            odeme_durumu TEXT NOT NULL DEFAULT 'Bekliyor',
            arsivlendi INTEGER NOT NULL DEFAULT 0 CHECK (arsivlendi IN (0, 1)),
            FOREIGN KEY (masa_bilgisi)
                REFERENCES masalar(masa_kodu)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS siparis (
            detay_id INTEGER PRIMARY KEY AUTOINCREMENT,
            siparis_id INTEGER NOT NULL,
            stok_kodu TEXT NOT NULL,
            urun_adi TEXT NOT NULL,
            birim_fiyat REAL NOT NULL,
            adet INTEGER NOT NULL,
            satir_toplami REAL NOT NULL,
            FOREIGN KEY (siparis_id)
                REFERENCES siparis_detaylari(siparis_id)
                ON DELETE CASCADE
        )
        """
    )

    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_siparis_detaylari_guest
        ON siparis_detaylari(guest_id)
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_siparis_siparis_id
        ON siparis(siparis_id)
        """
    )



def ensure_order_archive_column(cursor):
    if _table_exists(cursor, "siparis_detaylari"):
        cols = set(_column_names(cursor, "siparis_detaylari"))
        if "arsivlendi" not in cols:
            cursor.execute(
                "ALTER TABLE siparis_detaylari ADD COLUMN arsivlendi INTEGER NOT NULL DEFAULT 0"
            )

def migrate_legacy_order_tables(conn, cursor):
    """
    Eski şemayı veri kaybetmeden yeni isimlendirmeye taşır.

    Eski:
      siparisler         -> genel sipariş
      siparis_detaylari  -> ürün satırları

    Yeni:
      siparis_detaylari  -> genel sipariş
      siparis            -> ürün satırları

    Eski siparişlerin guest_id bilgisi olmadığı için '__legacy__' atanır;
    bu siparişler müşteri 'Siparişlerim' ekranında görünmez, admin panelinde görünür.
    """
    has_old_header = _table_exists(cursor, "siparisler")
    has_details_name = _table_exists(cursor, "siparis_detaylari")
    has_new_items = _table_exists(cursor, "siparis")

    if not has_old_header:
        # siparis_detaylari zaten yeni header tablosu olabilir.
        return

    details_is_old_items = False
    if has_details_name:
        cols = set(_column_names(cursor, "siparis_detaylari"))
        details_is_old_items = {"detay_id", "stok_kodu", "urun_adi", "birim_fiyat", "adet"}.issubset(cols)

    if details_is_old_items:
        cursor.execute("ALTER TABLE siparis_detaylari RENAME TO legacy_siparis_satirlari")

    cursor.execute("ALTER TABLE siparisler RENAME TO legacy_siparis_detaylari")
    _create_new_order_tables(cursor)

    legacy_header_cols = set(_column_names(cursor, "legacy_siparis_detaylari"))
    required = {
        "siparis_id", "musteri_adi", "telefon", "masa_bilgisi",
        "toplam_tutar", "siparis_durumu", "siparis_tarihi", "notlar"
    }
    if required.issubset(legacy_header_cols):
        # Eski kayıtlarda A1/B1 dışında masa isimleri bulunabilir. FK hatası
        # oluşturmamak ve geçmiş veriyi kaybetmemek için bunları da pasif
        # olmayan "Eski" bölgesi masası olarak tanımlıyoruz.
        cursor.execute(
            """
            INSERT OR IGNORE INTO masalar (masa_kodu, bolge, aktif)
            SELECT DISTINCT masa_bilgisi, 'Eski', 1
            FROM legacy_siparis_detaylari
            WHERE masa_bilgisi IS NOT NULL AND TRIM(masa_bilgisi) <> ''
            """
        )

        cursor.execute(
            """
            INSERT OR IGNORE INTO siparis_detaylari (
                siparis_id, guest_id, musteri_adi, telefon, masa_bilgisi,
                toplam_tutar, siparis_durumu, siparis_tarihi, notlar
            )
            SELECT
                siparis_id, '__legacy__', musteri_adi, telefon, masa_bilgisi,
                toplam_tutar, siparis_durumu, siparis_tarihi, notlar
            FROM legacy_siparis_detaylari
            """
        )

    if _table_exists(cursor, "legacy_siparis_satirlari"):
        item_cols = set(_column_names(cursor, "legacy_siparis_satirlari"))
        required_items = {
            "detay_id", "siparis_id", "stok_kodu", "urun_adi",
            "birim_fiyat", "adet", "satir_toplami"
        }
        if required_items.issubset(item_cols):
            cursor.execute(
                """
                INSERT OR IGNORE INTO siparis (
                    detay_id, siparis_id, stok_kodu, urun_adi,
                    birim_fiyat, adet, satir_toplami
                )
                SELECT
                    detay_id, siparis_id, stok_kodu, urun_adi,
                    birim_fiyat, adet, satir_toplami
                FROM legacy_siparis_satirlari
                """
            )

    conn.commit()



def ensure_payment_columns(cursor):
    """Eski veritabanlarına ödeme alanlarını güvenli biçimde ekler."""
    if not _table_exists(cursor, "siparis_detaylari"):
        return
    cols = set(_column_names(cursor, "siparis_detaylari"))
    if "odeme_yontemi" not in cols:
        cursor.execute(
            "ALTER TABLE siparis_detaylari ADD COLUMN odeme_yontemi TEXT NOT NULL DEFAULT 'Belirlenmedi'"
        )
    if "odeme_durumu" not in cols:
        cursor.execute(
            "ALTER TABLE siparis_detaylari ADD COLUMN odeme_durumu TEXT NOT NULL DEFAULT 'Bekliyor'"
        )


def normalize_order_statuses(cursor):
    """Eski sürümdeki durumları yeni mutfak/garson akışına taşır."""
    if _table_exists(cursor, "siparis_detaylari"):
        cols = set(_column_names(cursor, "siparis_detaylari"))
        if "siparis_durumu" in cols:
            if "garson_id" in cols:
                cursor.execute(
                    """UPDATE siparis_detaylari
                       SET siparis_durumu = 'Hazır'
                       WHERE siparis_durumu = 'Garsona Teslim Edildi'
                         AND garson_id IS NULL"""
                )

def seed_tables(cursor):
    cursor.executemany(
        """
        INSERT OR IGNORE INTO masalar (masa_kodu, bolge, aktif)
        VALUES (?, ?, 1)
        """,
        DEFAULT_TABLES,
    )



def create_waiter_tables(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS garsonlar (
            garson_id INTEGER PRIMARY KEY AUTOINCREMENT,
            kullanici_adi TEXT UNIQUE NOT NULL,
            sifre_hash TEXT NOT NULL,
            ad_soyad TEXT NOT NULL,
            aktif INTEGER NOT NULL DEFAULT 1 CHECK (aktif IN (0, 1))
        )
        """
    )

    if _table_exists(cursor, "siparis_detaylari"):
        columns = set(_column_names(cursor, "siparis_detaylari"))
        if "garson_id" not in columns:
            cursor.execute(
                "ALTER TABLE siparis_detaylari ADD COLUMN garson_id INTEGER"
            )


def create_demo_waiter(cursor):
    cursor.execute(
        "SELECT garson_id FROM garsonlar WHERE kullanici_adi = ?",
        ("garson",),
    )
    if cursor.fetchone() is None:
        cursor.execute(
            """
            INSERT INTO garsonlar (kullanici_adi, sifre_hash, ad_soyad, aktif)
            VALUES (?, ?, ?, 1)
            """,
            ("garson", generate_password_hash("1"), "Demo Garson"),
        )




def ensure_cashier_tables(cursor):
    """Kasiyer terminali için kısmi ödeme/split-fiş altyapısını hazırlar."""
    if _table_exists(cursor, "siparis"):
        cols = set(_column_names(cursor, "siparis"))
        if "odenmis_adet" not in cols:
            cursor.execute(
                "ALTER TABLE siparis ADD COLUMN odenmis_adet INTEGER NOT NULL DEFAULT 0"
            )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS odeme_hareketleri (
            odeme_id INTEGER PRIMARY KEY AUTOINCREMENT,
            siparis_id INTEGER NOT NULL,
            odeme_yontemi TEXT NOT NULL,
            tutar REAL NOT NULL,
            aciklama TEXT,
            odeme_tarihi TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (siparis_id)
                REFERENCES siparis_detaylari(siparis_id)
                ON DELETE CASCADE
        )
        """
    )

    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_odeme_hareketleri_siparis
        ON odeme_hareketleri(siparis_id)
        """
    )


def ensure_service_columns(cursor):
    """Eski veritabanlarına servis tipi ve servis ücreti alanlarını ekler."""
    if not _table_exists(cursor, "siparis_detaylari"):
        return
    cols = set(_column_names(cursor, "siparis_detaylari"))
    if "servis_turu" not in cols:
        cursor.execute(
            "ALTER TABLE siparis_detaylari ADD COLUMN servis_turu TEXT NOT NULL DEFAULT 'Garson Servisi'"
        )
    if "servis_ucreti" not in cols:
        cursor.execute(
            "ALTER TABLE siparis_detaylari ADD COLUMN servis_ucreti REAL NOT NULL DEFAULT 0"
        )
    if "servis_ucreti_odendi" not in cols:
        cursor.execute(
            "ALTER TABLE siparis_detaylari ADD COLUMN servis_ucreti_odendi INTEGER NOT NULL DEFAULT 0"
        )


def create_notification_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS bildirimler (
            bildirim_id INTEGER PRIMARY KEY AUTOINCREMENT,
            guest_id TEXT NOT NULL,
            siparis_id INTEGER NOT NULL,
            mesaj TEXT NOT NULL,
            siparis_durumu TEXT,
            okundu INTEGER NOT NULL DEFAULT 0 CHECK (okundu IN (0, 1)),
            olusturma_tarihi TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (siparis_id)
                REFERENCES siparis_detaylari(siparis_id)
                ON DELETE CASCADE
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_bildirimler_guest ON bildirimler(guest_id, okundu, bildirim_id)"
    )


def add_notification(cursor, guest_id, siparis_id, message, status=None):
    if not guest_id or guest_id == "__legacy__":
        return
    cursor.execute(
        """
        INSERT INTO bildirimler (guest_id, siparis_id, mesaj, siparis_durumu)
        VALUES (?, ?, ?, ?)
        """,
        (guest_id, siparis_id, message, status),
    )


def reset_test_order_data():
    """Sipariş/ödeme/bildirim test verilerini temizler; stok, masa ve personel kalır."""
    conn, cursor = connect_database()
    try:
        if _table_exists(cursor, "bildirimler"):
            cursor.execute("DELETE FROM bildirimler")
        if _table_exists(cursor, "odeme_hareketleri"):
            cursor.execute("DELETE FROM odeme_hareketleri")
        if _table_exists(cursor, "siparis"):
            cursor.execute("DELETE FROM siparis")
        if _table_exists(cursor, "siparis_detaylari"):
            cursor.execute("DELETE FROM siparis_detaylari")

        if _table_exists(cursor, "sqlite_sequence"):
            cursor.execute(
                "DELETE FROM sqlite_sequence WHERE name IN ('bildirimler','odeme_hareketleri','siparis','siparis_detaylari')"
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize_database():
    conn, cursor = connect_database()
    try:
        create_stock_table(cursor)
        create_tables_table(cursor)
        seed_tables(cursor)
        conn.commit()

        migrate_legacy_order_tables(conn, cursor)
        _create_new_order_tables(cursor)
        ensure_order_archive_column(cursor)
        ensure_payment_columns(cursor)
        ensure_service_columns(cursor)
        create_notification_table(cursor)
        normalize_order_statuses(cursor)
        create_waiter_tables(cursor)
        create_demo_waiter(cursor)
        ensure_cashier_tables(cursor)
        conn.commit()
    finally:
        conn.close()


def get_active_tables():
    conn, cursor = connect_database()
    try:
        cursor.execute(
            """
            SELECT masa_kodu
            FROM masalar
            WHERE aktif = 1
            ORDER BY bolge, masa_kodu
            """
        )
        return [row[0] for row in cursor.fetchall()]
    finally:
        conn.close()


def is_active_table(masa_kodu):
    if not masa_kodu:
        return False

    conn, cursor = connect_database()
    try:
        cursor.execute(
            """
            SELECT 1
            FROM masalar
            WHERE masa_kodu = ? AND aktif = 1
            """,
            (masa_kodu,),
        )
        return cursor.fetchone() is not None
    finally:
        conn.close()


def insert_data(cursor):
    stoklar = [
        ("ST00001", "Latte", 100, 0),
        ("ST00002", "Americano", 120, 0),
        ("ST00003", "Caramel Latte", 120, 0),
        ("ST00004", "Vanilla Latte", 150, 0),
        ("ST00005", "White Mocha", 130, 0),
        ("ST00006", "Mocha", 120, 0),
        ("ST00007", "Espresso", 160, 0),
        ("ST00008", "Cappuccino", 160, 0),
        ("ST00009", "Filtre Kahve", 100, 0),
        ("ST00010", "Türk Kahvesi", 100, 0),
    ]

    cursor.executemany(
        """
        INSERT OR IGNORE INTO stok_listesi
            (stok_kodu, stok_adı, fiyat, adet)
        VALUES (?, ?, ?, ?)
        """,
        stoklar,
    )
