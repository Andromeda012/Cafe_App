import database
from werkzeug.security import check_password_hash, generate_password_hash

READY_STATUS = "Hazır"
ACTIVE_STATUS = "Garsona Teslim Edildi"
DELIVERED_STATUS = "Teslim Edildi"


def authenticate_waiter(username, password):
    conn, cursor = database.connect_database()
    try:
        cursor.execute(
            """
            SELECT garson_id, kullanici_adi, sifre_hash, ad_soyad, aktif
            FROM garsonlar
            WHERE kullanici_adi = ?
            """,
            (username,),
        )
        waiter = cursor.fetchone()
        if waiter is None or waiter[4] != 1:
            return None
        if not check_password_hash(waiter[2], password):
            return None
        return {
            "garson_id": waiter[0],
            "kullanici_adi": waiter[1],
            "ad_soyad": waiter[3],
        }
    finally:
        conn.close()


def get_ready_orders():
    conn, cursor = database.connect_database()
    try:
        cursor.execute(
            """
            SELECT siparis_id, masa_bilgisi, toplam_tutar, siparis_tarihi
            FROM siparis_detaylari
            WHERE siparis_durumu = ?
              AND garson_id IS NULL
              AND servis_turu = 'Garson Servisi'
              AND arsivlendi = 0
            ORDER BY siparis_tarihi ASC
            """,
            (READY_STATUS,),
        )
        return cursor.fetchall()
    finally:
        conn.close()


def get_waiter_active_orders(waiter_id):
    conn, cursor = database.connect_database()
    try:
        cursor.execute(
            """
            SELECT siparis_id, masa_bilgisi, toplam_tutar, siparis_tarihi
            FROM siparis_detaylari
            WHERE siparis_durumu = ?
              AND garson_id = ?
              AND arsivlendi = 0
            ORDER BY siparis_tarihi ASC
            """,
            (ACTIVE_STATUS, waiter_id),
        )
        return cursor.fetchall()
    finally:
        conn.close()


def claim_order(siparis_id, waiter_id):
    conn, cursor = database.connect_database()
    try:
        cursor.execute(
            """
            SELECT guest_id
            FROM siparis_detaylari
            WHERE siparis_id = ?
              AND garson_id IS NULL
              AND siparis_durumu = ?
              AND servis_turu = 'Garson Servisi'
              AND arsivlendi = 0
            """,
            (siparis_id, READY_STATUS),
        )
        row = cursor.fetchone()
        if row is None:
            return False
        guest_id = row[0]

        cursor.execute(
            """
            UPDATE siparis_detaylari
            SET garson_id = ?, siparis_durumu = ?
            WHERE siparis_id = ?
              AND garson_id IS NULL
              AND siparis_durumu = ?
              AND servis_turu = 'Garson Servisi'
              AND arsivlendi = 0
            """,
            (waiter_id, ACTIVE_STATUS, siparis_id, READY_STATUS),
        )
        success = cursor.rowcount == 1
        if success:
            cursor.execute("SELECT ad_soyad FROM garsonlar WHERE garson_id = ?", (waiter_id,))
            waiter = cursor.fetchone()
            waiter_name = waiter[0] if waiter else "Garsonunuz"
            database.add_notification(
                cursor, guest_id, siparis_id,
                f"Sipariş #{siparis_id} {waiter_name} tarafından teslim alındı ve masanıza getiriliyor.",
                ACTIVE_STATUS,
            )
        conn.commit()
        return success
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def deliver_order(siparis_id, waiter_id):
    conn, cursor = database.connect_database()
    try:
        cursor.execute(
            "SELECT guest_id FROM siparis_detaylari WHERE siparis_id = ? AND garson_id = ?",
            (siparis_id, waiter_id),
        )
        row = cursor.fetchone()
        if row is None:
            return False
        guest_id = row[0]

        cursor.execute(
            """
            UPDATE siparis_detaylari
            SET siparis_durumu = ?
            WHERE siparis_id = ?
              AND garson_id = ?
              AND siparis_durumu = ?
              AND arsivlendi = 0
            """,
            (DELIVERED_STATUS, siparis_id, waiter_id, ACTIVE_STATUS),
        )
        success = cursor.rowcount == 1
        if success:
            database.add_notification(
                cursor, guest_id, siparis_id,
                f"Sipariş #{siparis_id} masanıza teslim edildi. Afiyet olsun!",
                DELIVERED_STATUS,
            )
        conn.commit()
        return success
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_waiter_order(siparis_id, waiter_id):
    conn, cursor = database.connect_database()
    try:
        cursor.execute(
            """
            SELECT siparis_id, masa_bilgisi, musteri_adi, telefon,
                   toplam_tutar, siparis_durumu, siparis_tarihi,
                   notlar, garson_id
            FROM siparis_detaylari
            WHERE siparis_id = ?
              AND servis_turu = 'Garson Servisi'
              AND ((siparis_durumu = ? AND garson_id IS NULL)
                   OR (siparis_durumu = ? AND garson_id = ?))
              AND arsivlendi = 0
            """,
            (siparis_id, READY_STATUS, ACTIVE_STATUS, waiter_id),
        )
        order_info = cursor.fetchone()
        if order_info is None:
            return None, []

        cursor.execute(
            """
            SELECT urun_adi, adet, birim_fiyat, satir_toplami
            FROM siparis
            WHERE siparis_id = ?
            ORDER BY detay_id ASC
            """,
            (siparis_id,),
        )
        return order_info, cursor.fetchall()
    finally:
        conn.close()


def get_all_waiters():
    conn, cursor = database.connect_database()
    try:
        cursor.execute(
            """
            SELECT garson_id, kullanici_adi, ad_soyad, aktif
            FROM garsonlar
            ORDER BY aktif DESC, ad_soyad ASC
            """
        )
        return cursor.fetchall()
    finally:
        conn.close()


def create_waiter(username, password, full_name):
    username = (username or "").strip()
    full_name = (full_name or "").strip()
    password = password or ""

    if len(username) < 3:
        raise ValueError("Kullanıcı adı en az 3 karakter olmalıdır.")
    if len(password) < 1:
        raise ValueError("Şifre boş bırakılamaz.")
    if len(full_name) < 2:
        raise ValueError("Garson adı en az 2 karakter olmalıdır.")

    conn, cursor = database.connect_database()
    try:
        cursor.execute(
            "SELECT 1 FROM garsonlar WHERE kullanici_adi = ?",
            (username,),
        )
        if cursor.fetchone() is not None:
            raise ValueError("Bu kullanıcı adı zaten kullanılıyor.")

        cursor.execute(
            """
            INSERT INTO garsonlar (kullanici_adi, sifre_hash, ad_soyad, aktif)
            VALUES (?, ?, ?, 1)
            """,
            (username, generate_password_hash(password), full_name),
        )
        conn.commit()
        return int(cursor.lastrowid)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def toggle_waiter(waiter_id):
    conn, cursor = database.connect_database()
    try:
        cursor.execute(
            "SELECT aktif FROM garsonlar WHERE garson_id = ?",
            (waiter_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return False

        new_value = 0 if int(row[0]) == 1 else 1
        cursor.execute(
            "UPDATE garsonlar SET aktif = ? WHERE garson_id = ?",
            (new_value, waiter_id),
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
