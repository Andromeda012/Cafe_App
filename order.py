import database


def get_stok():
    conn = None

    try:
        conn, cursor = database.connect_database()

        cursor.execute(
            """
            SELECT stok_adı, fiyat, stok_kodu, adet
            FROM stok_listesi
            """
        )

        return cursor.fetchall()

    except Exception as e:
        print("Stokları getirme hatası:", e)
        return []

    finally:
        if conn is not None:
            conn.close()


def get_basket_products(basket):
    conn = None
    added_stoks = []

    try:
        conn, cursor = database.connect_database()

        for stok_kodu, sepet_adedi in basket.items():
            cursor.execute(
                """
                SELECT stok_adı, fiyat, stok_kodu
                FROM stok_listesi
                WHERE stok_kodu = ?
                """,
                (stok_kodu,)
            )

            bulunan_stok = cursor.fetchone()

            if bulunan_stok is not None:
                stok_adi = bulunan_stok[0]
                fiyat = bulunan_stok[1]
                stok_kodu = bulunan_stok[2]

                added_stoks.append(
                    (
                        stok_adi,
                        fiyat,
                        stok_kodu,
                        sepet_adedi
                    )
                )

        return added_stoks

    except Exception as e:
        print("Sepet ürünlerini getirme hatası:", e)
        return []

    finally:
        if conn is not None:
            conn.close()