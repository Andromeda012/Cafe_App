import os
import database
from customer import OrderCreate

SELF_SERVICE_FEE = float(os.environ.get("NOIR_SELF_SERVICE_FEE", "50"))


def create_order(order_data: OrderCreate, added_stocks: list[tuple]) -> int:
    """Siparişin genel bilgisini ve ürün satırlarını tek transaction içinde kaydeder."""

    if not added_stocks:
        raise ValueError("Boş sepet kaydedilemez.")

    conn, cursor = database.connect_database()

    try:
        cursor.execute(
            """
            INSERT INTO siparis_detaylari (
                guest_id,
                musteri_adi,
                telefon,
                masa_bilgisi,
                toplam_tutar,
                siparis_durumu,
                siparis_tarihi,
                notlar,
                servis_turu,
                servis_ucreti
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order_data.guest_id,
                order_data.name,
                order_data.phone_number,
                order_data.table,
                order_data.total,
                order_data.order_status.value,
                order_data.order_date.isoformat(timespec="seconds"),
                order_data.note,
                order_data.service_type.value,
                order_data.service_fee,
            ),
        )

        siparis_id = cursor.lastrowid

        detail_rows = []
        for added_stock in added_stocks:
            urun_adi = added_stock[0]
            birim_fiyat = float(added_stock[1])
            stok_kodu = added_stock[2]
            adet = int(added_stock[3])
            satir_toplami = birim_fiyat * adet

            detail_rows.append(
                (
                    siparis_id,
                    stok_kodu,
                    urun_adi,
                    birim_fiyat,
                    adet,
                    satir_toplami,
                )
            )

        cursor.executemany(
            """
            INSERT INTO siparis (
                siparis_id,
                stok_kodu,
                urun_adi,
                birim_fiyat,
                adet,
                satir_toplami
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            detail_rows,
        )

        conn.commit()
        return int(siparis_id)

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


def get_customer_orders(guest_id):
    conn, cursor = database.connect_database()
    try:
        cursor.execute(
            """
            SELECT
                siparis_id,
                masa_bilgisi,
                toplam_tutar,
                siparis_durumu,
                siparis_tarihi,
                servis_turu,
                servis_ucreti
            FROM siparis_detaylari
            WHERE guest_id = ?
            ORDER BY siparis_tarihi DESC
            """,
            (guest_id,),
        )
        return cursor.fetchall()
    finally:
        conn.close()


def get_customer_order_detail(guest_id, siparis_id):
    conn, cursor = database.connect_database()
    try:
        cursor.execute(
            """
            SELECT
                siparis_id,
                masa_bilgisi,
                toplam_tutar,
                siparis_durumu,
                siparis_tarihi,
                notlar,
                servis_turu,
                servis_ucreti
            FROM siparis_detaylari
            WHERE siparis_id = ? AND guest_id = ?
            """,
            (siparis_id, guest_id),
        )
        order_header = cursor.fetchone()

        if order_header is None:
            return None, []

        cursor.execute(
            """
            SELECT urun_adi, birim_fiyat, adet, satir_toplami
            FROM siparis
            WHERE siparis_id = ?
            ORDER BY detay_id ASC
            """,
            (siparis_id,),
        )
        return order_header, cursor.fetchall()
    finally:
        conn.close()



def get_customer_editable_order(guest_id, siparis_id):
    """Müşterinin yalnızca Yeni durumundaki siparişini düzenlemek için verileri getirir."""
    conn, cursor = database.connect_database()
    try:
        cursor.execute(
            """SELECT siparis_id, masa_bilgisi, toplam_tutar, siparis_durumu,
                      siparis_tarihi, notlar, servis_turu, servis_ucreti, odeme_durumu
               FROM siparis_detaylari
              WHERE siparis_id = ? AND guest_id = ?""",
            (siparis_id, guest_id),
        )
        header = cursor.fetchone()
        if header is None:
            return None, []
        cursor.execute(
            """SELECT detay_id, stok_kodu, urun_adi, birim_fiyat, adet
                 FROM siparis
                WHERE siparis_id = ?
                ORDER BY detay_id ASC""",
            (siparis_id,),
        )
        return header, cursor.fetchall()
    finally:
        conn.close()


def update_customer_order(guest_id, siparis_id, items, service_type, note=None):
    """Yeni durumundaki müşteri siparişini ürün ve servis tercihiyle günceller."""
    from customer import ServiceType

    if service_type not in (ServiceType.WAITER.value, ServiceType.SELF.value):
        raise ValueError("Geçersiz servis türü.")

    conn, cursor = database.connect_database()
    try:
        cursor.execute(
            """SELECT siparis_durumu, odeme_durumu, masa_bilgisi
                 FROM siparis_detaylari
                WHERE siparis_id = ? AND guest_id = ?""",
            (siparis_id, guest_id),
        )
        header = cursor.fetchone()
        if header is None:
            raise ValueError("Sipariş bulunamadı.")
        if header[0] != "Yeni":
            raise ValueError("Mutfak hazırlığa başladığı için bu sipariş artık düzenlenemez.")

        # Gerçek bir ödeme entegrasyonu olmadığı için bile, daha önce ödenmiş
        # siparişi sessizce yeni tutara taşımıyoruz. Demo kullanıcıya yeniden
        # ödeme gerektiren bir durum bırakıyoruz.
        was_paid = header[1] == "Ödendi"

        normalized = {}
        for code, qty in (items or {}).items():
            try:
                qty = int(qty)
            except (TypeError, ValueError):
                continue
            if qty > 0:
                normalized[str(code)] = qty
        if not normalized:
            raise ValueError("Siparişte en az bir ürün bulunmalıdır.")

        placeholders = ",".join("?" for _ in normalized)
        cursor.execute(
            f"SELECT stok_kodu, stok_adı, fiyat FROM stok_listesi WHERE stok_kodu IN ({placeholders})",
            tuple(normalized.keys()),
        )
        stock_rows = {row[0]: row for row in cursor.fetchall()}
        if len(stock_rows) != len(normalized):
            raise ValueError("Siparişte bulunmayan bir ürün seçildi.")

        cursor.execute("DELETE FROM siparis WHERE siparis_id = ?", (siparis_id,))
        subtotal = 0.0
        for code, qty in normalized.items():
            row = stock_rows[code]
            unit = float(row[2])
            line_total = unit * qty
            subtotal += line_total
            cursor.execute(
                """INSERT INTO siparis (siparis_id, stok_kodu, urun_adi, birim_fiyat, adet, satir_toplami)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (siparis_id, code, row[1], unit, qty, line_total),
            )

        service_fee = SELF_SERVICE_FEE if service_type == ServiceType.SELF.value else 0.0
        total = round(subtotal + service_fee, 2)

        cursor.execute(
            """UPDATE siparis_detaylari
                  SET toplam_tutar = ?, servis_turu = ?, servis_ucreti = ?,
                      servis_ucreti_odendi = 0, notlar = ?,
                      odeme_yontemi = ?, odeme_durumu = ?
                WHERE siparis_id = ? AND guest_id = ? AND siparis_durumu = 'Yeni'""",
            (
                total, service_type, service_fee, note,
                "Belirlenmedi" if not was_paid else "Yeniden Ödeme Gerekli",
                "Bekliyor" if not was_paid else "Yeniden Ödeme Gerekli",
                siparis_id, guest_id,
            ),
        )
        if cursor.rowcount == 0:
            raise ValueError("Sipariş artık düzenlenemiyor.")

        database.add_notification(
            cursor, guest_id, siparis_id,
            f"Sipariş #{siparis_id} güncellendi.", "Yeni"
        )
        conn.commit()
        return total
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def cancel_customer_order(guest_id, siparis_id, cancel_minutes=5):
    """Müşteri yalnızca Yeni durumundaki ve iptal süresi dolmamış siparişini iptal edebilir."""
    from datetime import datetime, timedelta

    conn, cursor = database.connect_database()
    try:
        cursor.execute(
            """
            SELECT siparis_durumu, siparis_tarihi, odeme_durumu
            FROM siparis_detaylari
            WHERE siparis_id = ? AND guest_id = ?
            """,
            (siparis_id, guest_id),
        )
        row = cursor.fetchone()
        if row is None:
            return False, "Sipariş bulunamadı."

        status, created_at, payment_status = row
        if status != "Yeni":
            return False, "Mutfak hazırlığa başladığı için bu sipariş artık iptal edilemez."

        try:
            created = datetime.fromisoformat(created_at)
        except (TypeError, ValueError):
            created = datetime.now()

        if datetime.now() > created + timedelta(minutes=int(cancel_minutes)):
            return False, f"Siparişin {cancel_minutes} dakikalık iptal süresi doldu."

        new_payment_status = "İade Bekliyor" if payment_status == "Ödendi" else "İptal"
        cursor.execute(
            """
            UPDATE siparis_detaylari
            SET siparis_durumu = 'İptal Edildi',
                odeme_durumu = ?
            WHERE siparis_id = ?
              AND guest_id = ?
              AND siparis_durumu = 'Yeni'
            """,
            (new_payment_status, siparis_id, guest_id),
        )
        updated = cursor.rowcount > 0
        if updated:
            database.add_notification(
                cursor, guest_id, siparis_id,
                f"Sipariş #{siparis_id} iptal edildi.",
                "İptal Edildi",
            )
        conn.commit()
        if updated:
            return True, "Siparişiniz iptal edildi."
        return False, "Sipariş durumu değiştiği için iptal işlemi tamamlanamadı."
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_unread_notifications(guest_id, after_id=0):
    conn, cursor = database.connect_database()
    try:
        cursor.execute(
            """
            SELECT bildirim_id, siparis_id, mesaj, siparis_durumu, olusturma_tarihi
            FROM bildirimler
            WHERE guest_id = ? AND bildirim_id > ?
            ORDER BY bildirim_id ASC
            """,
            (guest_id, int(after_id or 0)),
        )
        notifications = cursor.fetchall()
        cursor.execute(
            "SELECT COUNT(*) FROM bildirimler WHERE guest_id = ? AND okundu = 0",
            (guest_id,),
        )
        unread_count = int(cursor.fetchone()[0] or 0)
        cursor.execute(
            "SELECT COALESCE(MAX(bildirim_id), 0) FROM bildirimler WHERE guest_id = ?",
            (guest_id,),
        )
        latest_id = int(cursor.fetchone()[0] or 0)
        return notifications, unread_count, latest_id
    finally:
        conn.close()


def mark_notifications_read(guest_id, siparis_id=None):
    conn, cursor = database.connect_database()
    try:
        if siparis_id is None:
            cursor.execute(
                "UPDATE bildirimler SET okundu = 1 WHERE guest_id = ? AND okundu = 0",
                (guest_id,),
            )
        else:
            cursor.execute(
                "UPDATE bildirimler SET okundu = 1 WHERE guest_id = ? AND siparis_id = ? AND okundu = 0",
                (guest_id, siparis_id),
            )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def get_unread_notification_count(guest_id):
    conn, cursor = database.connect_database()
    try:
        cursor.execute(
            "SELECT COUNT(*) FROM bildirimler WHERE guest_id = ? AND okundu = 0",
            (guest_id,),
        )
        return int(cursor.fetchone()[0] or 0)
    finally:
        conn.close()
