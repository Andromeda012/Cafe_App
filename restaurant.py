import database
from customer import OrderStatus, ServiceType


REMOVABLE_STATUSES = {OrderStatus.DELIVERED.value, OrderStatus.CANCELLED.value}


def get_all_orders():
    conn, cursor = database.connect_database()
    try:
        cursor.execute(
            """
            SELECT siparis_id, masa_bilgisi, toplam_tutar, siparis_durumu, siparis_tarihi, servis_turu, servis_ucreti
            FROM siparis_detaylari
            WHERE COALESCE(arsivlendi, 0) = 0
            ORDER BY siparis_tarihi DESC
            """
        )
        return cursor.fetchall()
    finally:
        conn.close()


def get_order_detail(siparis_id):
    conn, cursor = database.connect_database()
    try:
        cursor.execute(
            """
            SELECT
                siparis_id,
                musteri_adi,
                telefon,
                masa_bilgisi,
                toplam_tutar,
                siparis_durumu,
                siparis_tarihi,
                notlar,
                servis_turu,
                servis_ucreti
            FROM siparis_detaylari
            WHERE siparis_id = ?
            """,
            (siparis_id,),
        )
        header = cursor.fetchone()

        if header is None:
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
        return header, cursor.fetchall()
    finally:
        conn.close()


def update_order_status(siparis_id, new_status):
    """Mutfak akışı: Yeni -> Hazırlanıyor -> Hazır. Her değişiklik müşteriye bildirilir."""
    valid_status = OrderStatus(new_status)

    conn, cursor = database.connect_database()
    try:
        cursor.execute(
            """
            SELECT siparis_durumu, guest_id, servis_turu
            FROM siparis_detaylari
            WHERE siparis_id = ?
              AND COALESCE(arsivlendi, 0) = 0
            """,
            (siparis_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return False

        current, guest_id, service_type = row
        if current == OrderStatus.NEW.value and valid_status == OrderStatus.PREPARING:
            message = f"Sipariş #{siparis_id} mutfak tarafından hazırlanmaya başlandı."
        elif current == OrderStatus.PREPARING.value and valid_status == OrderStatus.READY:
            if service_type == ServiceType.SELF.value:
                message = f"Sipariş #{siparis_id} hazır. Self servis siparişinizi teslim noktasından alabilirsiniz."
            else:
                message = f"Sipariş #{siparis_id} hazırlandı. Garson servisi için bekliyor."
        else:
            raise ValueError("Bu durum değişikliği mutfak terminalinden yapılamaz.")

        cursor.execute(
            """
            UPDATE siparis_detaylari
            SET siparis_durumu = ?
            WHERE siparis_id = ?
              AND siparis_durumu = ?
              AND COALESCE(arsivlendi, 0) = 0
            """,
            (valid_status.value, siparis_id, current),
        )
        updated = cursor.rowcount > 0
        if updated:
            database.add_notification(cursor, guest_id, siparis_id, message, valid_status.value)
        conn.commit()
        return updated
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def archive_order(siparis_id):
    """Teslim edilmiş veya iptal edilmiş siparişi operasyon listesinden kaldırır."""
    conn, cursor = database.connect_database()
    try:
        cursor.execute(
            """
            SELECT siparis_durumu
            FROM siparis_detaylari
            WHERE siparis_id = ?
            """,
            (siparis_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return False
        if row[0] not in REMOVABLE_STATUSES:
            raise ValueError("Yalnızca teslim edilen veya iptal edilen siparişler kaldırılabilir.")

        cursor.execute(
            """
            UPDATE siparis_detaylari
            SET arsivlendi = 1
            WHERE siparis_id = ?
            """,
            (siparis_id,),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_dashboard_stats():
    conn, cursor = database.connect_database()
    try:
        counts = {}
        for status in (OrderStatus.NEW, OrderStatus.PREPARING, OrderStatus.READY, OrderStatus.WITH_WAITER):
            cursor.execute(
                "SELECT COUNT(*) FROM siparis_detaylari WHERE siparis_durumu = ? AND COALESCE(arsivlendi, 0) = 0",
                (status.value,),
            )
            counts[status.value] = cursor.fetchone()[0]
        cursor.execute(
            """SELECT COUNT(*), COALESCE(SUM(toplam_tutar), 0)
               FROM siparis_detaylari
               WHERE DATE(siparis_tarihi) = DATE('now', 'localtime')"""
        )
        today_count, today_total = cursor.fetchone()
        return {
            "new_count": counts[OrderStatus.NEW.value],
            "preparing_count": counts[OrderStatus.PREPARING.value],
            "ready_count": counts[OrderStatus.READY.value],
            "waiter_count": counts[OrderStatus.WITH_WAITER.value],
            "today_count": today_count,
            "today_total": today_total,
        }
    finally:
        conn.close()


def get_daily_recommendation():
    """Aktif stoklardan güne göre deterministik bir ürün seçer."""
    from datetime import date
    conn, cursor = database.connect_database()
    try:
        cursor.execute(
            """SELECT stok_kodu, stok_adı, fiyat, adet
               FROM stok_listesi
               WHERE COALESCE(adet, 0) > 0
               ORDER BY stok_kodu ASC"""
        )
        rows = cursor.fetchall()
        if not rows:
            return None
        return rows[date.today().toordinal() % len(rows)]
    finally:
        conn.close()

def get_statistics():
    """Yönetim paneli için temel satış ve operasyon istatistiklerini döndürür."""
    conn, cursor = database.connect_database()
    try:
        # Genel sipariş sayıları
        cursor.execute("SELECT COUNT(*) FROM siparis_detaylari")
        total_orders = int(cursor.fetchone()[0] or 0)

        cursor.execute(
            "SELECT COUNT(*) FROM siparis_detaylari WHERE siparis_durumu != ?",
            (OrderStatus.CANCELLED.value,),
        )
        completed_scope_count = int(cursor.fetchone()[0] or 0)

        # Ciro ve ortalama sipariş tutarı: iptal edilenler satışa dahil edilmez.
        cursor.execute(
            """
            SELECT COALESCE(SUM(toplam_tutar), 0), COALESCE(AVG(toplam_tutar), 0)
            FROM siparis_detaylari
            WHERE siparis_durumu != ?
            """,
            (OrderStatus.CANCELLED.value,),
        )
        total_revenue, average_order = cursor.fetchone()

        cursor.execute(
            """
            SELECT COUNT(*), COALESCE(SUM(toplam_tutar), 0)
            FROM siparis_detaylari
            WHERE DATE(siparis_tarihi) = DATE('now', 'localtime')
              AND siparis_durumu != ?
            """,
            (OrderStatus.CANCELLED.value,),
        )
        today_orders, today_revenue = cursor.fetchone()

        # Durum dağılımı
        cursor.execute(
            """
            SELECT siparis_durumu, COUNT(*)
            FROM siparis_detaylari
            GROUP BY siparis_durumu
            ORDER BY COUNT(*) DESC
            """
        )
        status_counts = cursor.fetchall()

        # En çok satılan ürünler. İptal edilen siparişler hesaba katılmaz.
        cursor.execute(
            """
            SELECT s.urun_adi, SUM(s.adet) AS toplam_adet,
                   COALESCE(SUM(s.satir_toplami), 0) AS toplam_tutar
            FROM siparis AS s
            JOIN siparis_detaylari AS d ON d.siparis_id = s.siparis_id
            WHERE d.siparis_durumu != ?
            GROUP BY s.stok_kodu, s.urun_adi
            ORDER BY toplam_adet DESC, toplam_tutar DESC
            LIMIT 5
            """,
            (OrderStatus.CANCELLED.value,),
        )
        top_products = cursor.fetchall()

        # En yoğun masalar
        cursor.execute(
            """
            SELECT masa_bilgisi, COUNT(*) AS siparis_sayisi,
                   COALESCE(SUM(toplam_tutar), 0) AS toplam_tutar
            FROM siparis_detaylari
            WHERE siparis_durumu != ?
            GROUP BY masa_bilgisi
            ORDER BY siparis_sayisi DESC, toplam_tutar DESC
            LIMIT 5
            """,
            (OrderStatus.CANCELLED.value,),
        )
        top_tables = cursor.fetchall()

        # Son 7 günlük sipariş/ciro özeti. Eksik günler frontend'de 0 olarak tamamlanır.
        cursor.execute(
            """
            SELECT DATE(siparis_tarihi) AS gun, COUNT(*) AS siparis_sayisi,
                   COALESCE(SUM(toplam_tutar), 0) AS toplam_tutar
            FROM siparis_detaylari
            WHERE DATE(siparis_tarihi) >= DATE('now', 'localtime', '-6 day')
              AND siparis_durumu != ?
            GROUP BY DATE(siparis_tarihi)
            ORDER BY gun ASC
            """,
            (OrderStatus.CANCELLED.value,),
        )
        last_7_days = cursor.fetchall()

        return {
            "total_orders": total_orders,
            "counted_orders": completed_scope_count,
            "total_revenue": round(float(total_revenue or 0), 2),
            "average_order": round(float(average_order or 0), 2),
            "today_orders": int(today_orders or 0),
            "today_revenue": round(float(today_revenue or 0), 2),
            "status_counts": status_counts,
            "top_products": top_products,
            "top_tables": top_tables,
            "last_7_days": last_7_days,
        }
    finally:
        conn.close()


# --- Stok yönetimi ---

def get_all_stocks():
    conn, cursor = database.connect_database()
    try:
        cursor.execute(
            """
            SELECT stok_kodu, stok_adı, fiyat, adet
            FROM stok_listesi
            ORDER BY stok_adı COLLATE NOCASE ASC
            """
        )
        return cursor.fetchall()
    finally:
        conn.close()


def add_stock(stok_kodu, stok_adi, fiyat, adet):
    stok_kodu = (stok_kodu or "").strip().upper()
    stok_adi = (stok_adi or "").strip()
    if not stok_kodu or not stok_adi:
        raise ValueError("Stok kodu ve stok adı boş bırakılamaz.")

    try:
        fiyat = float(fiyat)
        adet = int(adet)
    except (TypeError, ValueError):
        raise ValueError("Fiyat sayı, adet ise tam sayı olmalıdır.")

    if fiyat < 0 or adet < 0:
        raise ValueError("Fiyat ve adet negatif olamaz.")

    conn, cursor = database.connect_database()
    try:
        cursor.execute(
            """
            INSERT INTO stok_listesi (stok_kodu, stok_adı, fiyat, adet)
            VALUES (?, ?, ?, ?)
            """,
            (stok_kodu, stok_adi, fiyat, adet),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_stock(original_code, stok_kodu, stok_adi, fiyat, adet):
    original_code = (original_code or "").strip().upper()
    stok_kodu = (stok_kodu or "").strip().upper()
    stok_adi = (stok_adi or "").strip()
    if not original_code or not stok_kodu or not stok_adi:
        raise ValueError("Stok kodu ve stok adı boş bırakılamaz.")

    try:
        fiyat = float(fiyat)
        adet = int(adet)
    except (TypeError, ValueError):
        raise ValueError("Fiyat sayı, adet ise tam sayı olmalıdır.")

    if fiyat < 0 or adet < 0:
        raise ValueError("Fiyat ve adet negatif olamaz.")

    conn, cursor = database.connect_database()
    try:
        cursor.execute(
            """
            UPDATE stok_listesi
            SET stok_kodu = ?, stok_adı = ?, fiyat = ?, adet = ?
            WHERE stok_kodu = ?
            """,
            (stok_kodu, stok_adi, fiyat, adet, original_code),
        )
        conn.commit()
        return cursor.rowcount > 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def delete_stock(stok_kodu):
    conn, cursor = database.connect_database()
    try:
        cursor.execute("DELETE FROM stok_listesi WHERE stok_kodu = ?", (stok_kodu,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


# --- Ödeme yönetimi ---

def update_payment_status(siparis_id, payment_method, payment_status):
    conn, cursor = database.connect_database()
    try:
        cursor.execute(
            """
            UPDATE siparis_detaylari
            SET odeme_yontemi = ?, odeme_durumu = ?
            WHERE siparis_id = ?
            """,
            (payment_method, payment_status, siparis_id),
        )
        updated = cursor.rowcount > 0

        # Müşteri tarafında ödeme tamamen onaylandığında ürün satırlarını da
        # ödenmiş say. Böylece kasiyer terminaline yanlışlıkla düşmez.
        if updated and payment_status == "Ödendi":
            cursor.execute(
                "UPDATE siparis SET odenmis_adet = adet WHERE siparis_id = ?",
                (siparis_id,),
            )
            cursor.execute(
                "UPDATE siparis_detaylari SET servis_ucreti_odendi = 1 WHERE siparis_id = ?",
                (siparis_id,),
            )

        conn.commit()
        return updated
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_payment_info(siparis_id, guest_id=None):
    conn, cursor = database.connect_database()
    try:
        query = """
            SELECT siparis_id, masa_bilgisi, toplam_tutar, odeme_yontemi, odeme_durumu, servis_turu, servis_ucreti
            FROM siparis_detaylari
            WHERE siparis_id = ?
        """
        params = [siparis_id]
        if guest_id is not None:
            query += " AND guest_id = ?"
            params.append(guest_id)
        cursor.execute(query, tuple(params))
        return cursor.fetchone()
    finally:
        conn.close()


# --- Kasiyer terminali ---

def get_unpaid_orders():
    """Tamamı ödenmemiş, iptal edilmemiş siparişleri kalan tutarıyla getirir."""
    conn, cursor = database.connect_database()
    try:
        cursor.execute(
            """
            SELECT
                d.siparis_id,
                d.masa_bilgisi,
                d.toplam_tutar,
                d.odeme_yontemi,
                d.odeme_durumu,
                d.siparis_tarihi,
                COALESCE(SUM((s.adet - COALESCE(s.odenmis_adet, 0)) * s.birim_fiyat), 0)
                + CASE WHEN COALESCE(d.servis_ucreti_odendi, 0) = 0 THEN COALESCE(d.servis_ucreti, 0) ELSE 0 END
                AS kalan_tutar
            FROM siparis_detaylari AS d
            JOIN siparis AS s ON s.siparis_id = d.siparis_id
            WHERE d.odeme_durumu != 'Ödendi'
              AND d.siparis_durumu = ?
            GROUP BY d.siparis_id
            HAVING kalan_tutar > 0
            ORDER BY d.siparis_tarihi ASC
            """,
            (OrderStatus.DELIVERED.value,),
        )
        return cursor.fetchall()
    finally:
        conn.close()


def get_cashier_order_detail(siparis_id):
    conn, cursor = database.connect_database()
    try:
        cursor.execute(
            """
            SELECT
                siparis_id, masa_bilgisi, musteri_adi, telefon,
                toplam_tutar, odeme_yontemi, odeme_durumu,
                siparis_durumu, siparis_tarihi, notlar,
                servis_turu, servis_ucreti, servis_ucreti_odendi
            FROM siparis_detaylari
            WHERE siparis_id = ?
            """,
            (siparis_id,),
        )
        header = cursor.fetchone()
        if header is None:
            return None, [], [], 0
        if header[7] != OrderStatus.DELIVERED.value:
            return None, [], [], 0

        cursor.execute(
            """
            SELECT
                detay_id, urun_adi, birim_fiyat, adet,
                COALESCE(odenmis_adet, 0) AS odenmis_adet,
                MAX(adet - COALESCE(odenmis_adet, 0), 0) AS kalan_adet,
                MAX(adet - COALESCE(odenmis_adet, 0), 0) * birim_fiyat AS kalan_tutar
            FROM siparis
            WHERE siparis_id = ?
            ORDER BY detay_id ASC
            """,
            (siparis_id,),
        )
        items = cursor.fetchall()

        cursor.execute(
            """
            SELECT odeme_id, odeme_yontemi, tutar, odeme_tarihi, aciklama
            FROM odeme_hareketleri
            WHERE siparis_id = ?
            ORDER BY odeme_id DESC
            """,
            (siparis_id,),
        )
        payments = cursor.fetchall()
        remaining = sum(float(item[6] or 0) for item in items)
        service_fee_remaining = float(header[11] or 0) if int(header[12] or 0) == 0 else 0.0
        remaining += service_fee_remaining
        return header, items, payments, round(remaining, 2)
    finally:
        conn.close()


def transfer_order_table(siparis_id, new_table):
    new_table = (new_table or '').strip().upper()
    if not database.is_active_table(new_table):
        raise ValueError('Seçilen masa aktif değil.')

    conn, cursor = database.connect_database()
    try:
        cursor.execute(
            """
            UPDATE siparis_detaylari
            SET masa_bilgisi = ?
            WHERE siparis_id = ?
              AND odeme_durumu != 'Ödendi'
              AND siparis_durumu = ?
            """,
            (new_table, siparis_id, OrderStatus.DELIVERED.value),
        )
        conn.commit()
        return cursor.rowcount > 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def cashier_take_payment(siparis_id, payment_method, selections=None):
    """
    Kasiyer ödemesi alır.
    selections: {detay_id: adet}. None ise kalan fişin tamamını kapatır.
    """
    if payment_method not in {'Nakit', 'POS'}:
        raise ValueError('Geçersiz ödeme yöntemi.')

    conn, cursor = database.connect_database()
    try:
        cursor.execute(
            """
            SELECT odeme_yontemi, odeme_durumu, servis_ucreti, servis_ucreti_odendi, siparis_durumu
            FROM siparis_detaylari
            WHERE siparis_id = ?
            """,
            (siparis_id,),
        )
        header = cursor.fetchone()
        if header is None:
            raise ValueError('Sipariş bulunamadı.')
        if header[1] == 'Ödendi':
            raise ValueError('Bu sipariş zaten tamamen ödenmiş.')
        if header[4] != OrderStatus.DELIVERED.value:
            raise ValueError('Sipariş müşteriye teslim edilmeden ödeme alınamaz.')

        cursor.execute(
            """
            SELECT detay_id, urun_adi, birim_fiyat, adet, COALESCE(odenmis_adet, 0)
            FROM siparis
            WHERE siparis_id = ?
            ORDER BY detay_id ASC
            """,
            (siparis_id,),
        )
        rows = cursor.fetchall()
        by_id = {int(row[0]): row for row in rows}

        if selections is None:
            selections = {
                int(row[0]): int(row[3]) - int(row[4])
                for row in rows
                if int(row[3]) - int(row[4]) > 0
            }

        normalized = {}
        for detail_id, qty in selections.items():
            detail_id = int(detail_id)
            qty = int(qty)
            if qty <= 0:
                continue
            row = by_id.get(detail_id)
            if row is None:
                raise ValueError('Fişte bulunmayan bir ürün seçildi.')
            remaining_qty = int(row[3]) - int(row[4])
            if qty > remaining_qty:
                raise ValueError(f'{row[1]} için kalan adetten fazla seçim yapıldı.')
            normalized[detail_id] = qty

        if not normalized:
            raise ValueError('Ödeme için en az bir ürün seçin.')

        amount = 0.0
        description_parts = []
        for detail_id, qty in normalized.items():
            row = by_id[detail_id]
            unit_price = float(row[2])
            amount += unit_price * qty
            description_parts.append(f'{row[1]} x{qty}')
            cursor.execute(
                """
                UPDATE siparis
                SET odenmis_adet = COALESCE(odenmis_adet, 0) + ?
                WHERE detay_id = ? AND siparis_id = ?
                """,
                (qty, detail_id, siparis_id),
            )

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM siparis
            WHERE siparis_id = ?
              AND COALESCE(odenmis_adet, 0) < adet
            """,
            (siparis_id,),
        )
        remaining_lines = int(cursor.fetchone()[0] or 0)

        # Self servis ücreti ürünlerden ayrı tutulur. Son ürün ödenirken
        # kalan servis ücreti aynı ödeme hareketine eklenir.
        service_fee = float(header[2] or 0)
        service_fee_paid = int(header[3] or 0)
        if remaining_lines == 0 and service_fee > 0 and service_fee_paid == 0:
            amount += service_fee
            description_parts.append(f'Servis ücreti {service_fee:g} TL')
            cursor.execute(
                "UPDATE siparis_detaylari SET servis_ucreti_odendi = 1 WHERE siparis_id = ?",
                (siparis_id,),
            )
            service_fee_paid = 1

        cursor.execute(
            """
            INSERT INTO odeme_hareketleri (
                siparis_id, odeme_yontemi, tutar, aciklama
            ) VALUES (?, ?, ?, ?)
            """,
            (siparis_id, payment_method, round(amount, 2), ', '.join(description_parts)),
        )

        previous_method = header[0]
        if previous_method in ('Belirlenmedi', 'Kasada Ödeme', payment_method):
            final_method = payment_method
        else:
            final_method = 'Karma'

        final_status = 'Ödendi' if remaining_lines == 0 and (service_fee <= 0 or service_fee_paid == 1) else 'Kısmi Ödendi'
        cursor.execute(
            """
            UPDATE siparis_detaylari
            SET odeme_yontemi = ?, odeme_durumu = ?
            WHERE siparis_id = ?
            """,
            (final_method, final_status, siparis_id),
        )
        conn.commit()
        return round(amount, 2), final_status
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
