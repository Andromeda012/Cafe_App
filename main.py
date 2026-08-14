import sqlite3
import database


def main():
    conn, cursor = database.connect_database()

    try:
        database.initialize_database()
        database.insert_data(cursor)
        conn.commit()
        print("Veritabanı oluşturuldu ve başlangıç verileri eklendi.")
    except sqlite3.Error as error:
        print(f"Veritabanı hatası: {error}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
