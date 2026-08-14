NOIR COFFEE - YÖNETİM TERMİNALİ AŞAMASI

Bu paket guest müşteri, masa, sipariş ve admin sisteminin üzerine stok yönetimi ve operasyon ekranını ekler.

Yönetim Terminali
-----------------
/admin girişinden sonra ana ekran artık "Yönetim Terminali"dir.
Terminal menüleri:
- Stok Ayarları: aktif; stok ekleme, revize etme ve silme
- İstatistikler: şimdilik yer tutucu
- Garsonlar: şimdilik yer tutucu

Operasyonlar
------------
/admin/orders ekranında:
- Günün özeti en üstte gösterilir.
- Sipariş ID, masa, toplam, tarih ve sipariş durumu görünür.
- Hazırlanıyor = sarı
- Garsona Teslim Edildi = yeşil
- Teslim Edildi = mavi
- İptal Edildi = kırmızı
- Yeni = nötr/kahve tonu
- Teslim edilen veya iptal edilen siparişler "Listeden kaldır" ile operasyon ekranından kaldırılabilir.

Not: "Listeden kaldır" işlemi siparişi veritabanından fiziksel olarak silmez. arsivlendi alanını 1 yapar. Böylece müşteri sipariş geçmişi ve ilerideki istatistikler bozulmaz.

Stok Ayarları
-------------
/admin/stocks ekranından:
- Yeni stok eklenebilir.
- Stok kodu, ürün adı, fiyat ve adet revize edilebilir.
- Stok kaydı silinebilir.
- Stok kodu benzersizdir.
- Fiyat/adet negatif olamaz.

Guest müşteri sistemi
---------------------
- Her tarayıcı Flask session içinde kalıcı bir guest_id taşır.
- Sepet session içinde kullanıcıya özeldir.
- /my-orders yalnızca aynı guest_id siparişlerini gösterir.
- Başka guest bir sipariş ID'sini tahmin etse bile detay ekranına erişemez.

Masa sistemi
------------
- masalar tablosu kullanılır.
- Varsayılan: Salon A1-A6, Bahçe B1-B6.
- Sipariş formu yalnızca aktif masaları kabul eder.

Tablo isimleri
--------------
Kullanıcı tercihine göre:
- siparis_detaylari = siparişin genel/müşteri bilgileri
- siparis = siparişin ürün satırları

Kurulum
-------
İlk kurulum / örnek stok verisi:
    python main.py

Uygulamayı çalıştırma:
    python app.py

Admin:
    kullanıcı adı: admin
    şifre: 1

Bağımlılıklar:
    pip install Flask pydantic

Gerçek yayından önce
--------------------
- NOIR_SECRET_KEY ortam değişkeniyle güçlü secret key kullanın.
- Admin hesabını veritabanına taşıyıp şifreyi hash'leyin.
- Formlara CSRF koruması ekleyin.

GARSONLAR MENÜSÜ ENTEGRASYONU
-----------------------------
Yönetim Terminali > Garsonlar artık aktif bir personel yönetim ekranıdır.

Bu ekrandan:
- Garson Terminali yeni sekmede açılabilir.
- Yeni garson hesabı eklenebilir.
- Mevcut garsonlar aktif/pasif yapılabilir.
- Garson kullanıcı adı ve personel adı görüntülenebilir.

Garson hesabı aktif değilse /waiter/login üzerinden giriş yapamaz.
Varsayılan demo hesap: garson / 1

Servis akışı:
Admin/Mutfak -> "Garsona Teslim Edildi" -> Garson Terminali -> "Siparişi Al" -> "Masaya Teslim Edildi"

WEB YAYINI
----------
İstatistik modülü ve temel yayın ayarları eklenmiştir. Yayına alma adımları için
README_WEB.txt dosyasını okuyun.
