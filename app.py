import os
import uuid
import json
from datetime import datetime, timedelta
from functools import wraps

import flask
import pydantic

import basket_page
import database
import order
import order_service
import restaurant
import waiter_service
from customer import OrderCreate, OrderStatus, ServiceType


app = flask.Flask(__name__)

APP_ENV = os.environ.get("NOIR_ENV", "development").lower()
IS_PRODUCTION = APP_ENV == "production"

# Yayında NOIR_SECRET_KEY, NOIR_ADMIN_USERNAME ve NOIR_ADMIN_PASSWORD
# ortam değişkenlerini mutlaka değiştirin. Geliştirme varsayılanları yalnızca lokaldir.
app.secret_key = os.environ.get("NOIR_SECRET_KEY", "dev-noir-secret-change-me")
app.permanent_session_lifetime = timedelta(days=365)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=IS_PRODUCTION,
    MAX_CONTENT_LENGTH=2 * 1024 * 1024,
)

ADMIN_USERNAME = os.environ.get("NOIR_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("NOIR_ADMIN_PASSWORD", "1")
CUSTOMER_CANCEL_MINUTES = int(os.environ.get("NOIR_CANCEL_MINUTES", "5"))
SELF_SERVICE_FEE = float(os.environ.get("NOIR_SELF_SERVICE_FEE", "50"))


TURKISH_MONTHS = [
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"
]


def format_datetime_tr(value):
    """Tarihleri kullanıcı arayüzünde 11 Ağustos 2026 16.09 biçiminde gösterir."""
    if value is None:
        return "-"
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return "-"
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
                try:
                    dt = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    dt = None
            if dt is None:
                return text
    return f"{dt.day} {TURKISH_MONTHS[dt.month - 1]} {dt.year} {dt.hour:02d}.{dt.minute:02d}"


app.jinja_env.filters["datetime_tr"] = format_datetime_tr

database.initialize_database()


def get_basket():
    return dict(flask.session.get("basket", {}))


def save_basket(basket):
    flask.session["basket"] = basket
    flask.session.modified = True


def get_guest_id():
    guest_id = flask.session.get("guest_id")
    if not guest_id:
        guest_id = uuid.uuid4().hex
        flask.session["guest_id"] = guest_id
        flask.session.modified = True
    return guest_id


def waiter_required(view_function):
    @wraps(view_function)
    def wrapped(*args, **kwargs):
        if not flask.session.get("waiter_id"):
            return flask.redirect(
                flask.url_for("waiter_login", next=flask.request.path)
            )
        return view_function(*args, **kwargs)

    return wrapped


def admin_required(view_function):
    @wraps(view_function)
    def wrapped(*args, **kwargs):
        if not flask.session.get("admin_logged_in"):
            return flask.redirect(
                flask.url_for("admin_login", next=flask.request.path)
            )
        return view_function(*args, **kwargs)

    return wrapped


@app.before_request
def prepare_session():
    # Guest kimliği tarayıcı kapatılıp yeniden açılsa da cookie süresi boyunca korunur.
    flask.session.permanent = True
    get_guest_id()


@app.context_processor
def inject_global_ui_data():
    basket = get_basket()
    guest_id = get_guest_id()
    return {
        "basket_count": sum(int(value) for value in basket.values()),
        "admin_logged_in": bool(flask.session.get("admin_logged_in")),
        "unread_notification_count": order_service.get_unread_notification_count(guest_id),
    }


@app.route("/")
def main_menu():
    return flask.render_template(
        "index.html",
        daily_recommendation=restaurant.get_daily_recommendation(),
        cafe_address=os.environ.get("NOIR_CAFE_ADDRESS", "Kadıköy, İstanbul"),
    )


@app.route("/order", methods=["GET", "POST"])
def order_app():
    basket = get_basket()

    if flask.request.method == "POST":
        stok_kodu = flask.request.form.get("stok_kodu")
        basket_page.add_product(basket, stok_kodu)
        save_basket(basket)

        return flask.jsonify(
            {
                "success": True,
                "message": "Ürün sepete eklendi",
                "basket_count": sum(basket.values()),
            }
        )

    stocks = order.get_stok()
    return flask.render_template("order.html", stocks=stocks)


@app.route("/basket")
def basket_app():
    basket = get_basket()
    added_stoks = order.get_basket_products(basket)
    total = basket_page.calculate_total(added_stoks, basket)

    return flask.render_template(
        "basket.html",
        added_stoks=added_stoks,
        total=total,
    )


@app.route("/basket/data")
def basket_data():
    """Mini sepet ve menü içi adet kontrolleri için hafif JSON görünümü."""
    basket = get_basket()
    added_stoks = order.get_basket_products(basket)
    total = basket_page.calculate_total(added_stoks, basket)

    items = []
    for urun_adi, birim_fiyat, stok_kodu, adet in added_stoks:
        items.append({
            "urun_adi": urun_adi,
            "birim_fiyat": float(birim_fiyat),
            "stok_kodu": stok_kodu,
            "adet": int(adet),
            "satir_toplami": float(birim_fiyat) * int(adet),
        })

    return flask.jsonify({
        "success": True,
        "items": items,
        "total": total,
        "basket_count": sum(int(v) for v in basket.values()),
    })


@app.route("/basket/increase", methods=["POST"])
def increase_basket_product():
    basket = get_basket()
    stok_kodu = flask.request.form.get("stok_kodu")
    basket_page.add_product(basket, stok_kodu)
    save_basket(basket)

    return flask.jsonify(
        {
            "success": True,
            "stok_kodu": stok_kodu,
            "adet": basket.get(stok_kodu, 0),
            "basket_count": sum(basket.values()),
        }
    )


@app.route("/basket/decrease", methods=["POST"])
def decrease_basket_product():
    basket = get_basket()
    stok_kodu = flask.request.form.get("stok_kodu")
    basket_page.decrease_product(basket, stok_kodu)
    save_basket(basket)

    return flask.jsonify(
        {
            "success": True,
            "stok_kodu": stok_kodu,
            "adet": basket.get(stok_kodu, 0),
            "basket_count": sum(basket.values()),
        }
    )


@app.route("/basket/remove", methods=["POST"])
def remove_basket_product():
    basket = get_basket()
    stok_kodu = flask.request.form.get("stok_kodu")
    basket_page.remove_product(basket, stok_kodu)
    save_basket(basket)
    return flask.redirect(flask.url_for("basket_app"))


@app.route("/payment", methods=["GET", "POST"])
def payment():
    basket = get_basket()
    added_stoks = order.get_basket_products(basket)
    subtotal = float(basket_page.calculate_total(added_stoks, basket))

    if not added_stoks:
        return flask.redirect(flask.url_for("basket_app"))

    tables = database.get_active_tables()
    form_data = {
        "name": "",
        "phone_number": "",
        "table": "",
        "note": "",
        "service_type": ServiceType.WAITER.value,
    }
    errors = {}
    service_fee = 0.0
    total = subtotal

    if flask.request.method == "POST":
        form_data = {
            "name": flask.request.form.get("name", ""),
            "phone_number": flask.request.form.get("phone_number", ""),
            "table": flask.request.form.get("table", ""),
            "note": flask.request.form.get("note", ""),
            "service_type": flask.request.form.get("service_type", ServiceType.WAITER.value),
        }

        if not database.is_active_table(form_data["table"]):
            errors["table"] = "Lütfen listede bulunan aktif masalardan birini seçin."

        try:
            selected_service = ServiceType(form_data["service_type"])
        except ValueError:
            errors["service_type"] = "Lütfen geçerli bir servis türü seçin."
            selected_service = ServiceType.WAITER

        service_fee = SELF_SERVICE_FEE if selected_service == ServiceType.SELF else 0.0
        total = subtotal + service_fee

        if not errors:
            try:
                order_data = OrderCreate(
                    guest_id=get_guest_id(),
                    name=form_data["name"],
                    phone_number=form_data["phone_number"],
                    table=form_data["table"],
                    total=total,
                    service_type=selected_service,
                    service_fee=service_fee,
                    note=form_data["note"] or None,
                )

                siparis_id = order_service.create_order(order_data, added_stoks)
                save_basket({})

                return flask.redirect(
                    flask.url_for("checkout", siparis_id=siparis_id)
                )

            except pydantic.ValidationError as error:
                for item in error.errors():
                    field_name = str(item["loc"][0])
                    errors[field_name] = item["msg"].replace("Value error, ", "")

            except Exception as error:
                app.logger.exception("Sipariş kaydedilemedi")
                errors["general"] = f"Sipariş kaydedilemedi: {error}"

    return flask.render_template(
        "payment.html",
        added_stoks=added_stoks,
        subtotal=subtotal,
        service_fee=service_fee,
        total=total,
        self_service_fee=SELF_SERVICE_FEE,
        form_data=form_data,
        errors=errors,
        tables=tables,
    )


@app.route("/checkout/<int:siparis_id>", methods=["GET", "POST"])
def checkout(siparis_id):
    order_header, _ = order_service.get_customer_order_detail(get_guest_id(), siparis_id)
    if order_header is None:
        flask.abort(404)

    payment_info = restaurant.get_payment_info(siparis_id, get_guest_id())
    if payment_info is None:
        flask.abort(404)

    error = None
    if flask.request.method == "POST":
        payment_method = flask.request.form.get("payment_method", "")

        if payment_method == "cash":
            restaurant.update_payment_status(siparis_id, "Kasada Ödeme", "Kasada Bekliyor")
            return flask.redirect(flask.url_for("payment_success", siparis_id=siparis_id))

        if payment_method == "card":
            card_number = flask.request.form.get("card_number", "").strip()
            expiry = flask.request.form.get("expiry", "").strip()
            cvv = flask.request.form.get("cvv", "").strip()
            if card_number == "1" and expiry == "1" and cvv == "1":
                restaurant.update_payment_status(siparis_id, "Kart", "Ödendi")
                return flask.redirect(flask.url_for("payment_success", siparis_id=siparis_id))
            error = "Demo ödeme için kart numarası, son kullanma tarihi ve CVV alanlarına 1 girin."
        else:
            error = "Lütfen bir ödeme yöntemi seçin."

    return flask.render_template(
        "checkout.html",
        siparis_id=siparis_id,
        payment_info=payment_info,
        total=payment_info[2],
        error=error,
    )


@app.route("/payment/success/<int:siparis_id>")
def payment_success(siparis_id):
    # Başarı sayfası yalnızca aynı guest'e ait sipariş için açılır.
    header, _ = order_service.get_customer_order_detail(get_guest_id(), siparis_id)
    if header is None:
        flask.abort(404)

    payment_info = restaurant.get_payment_info(siparis_id, get_guest_id())
    return flask.render_template(
        "payment_success.html",
        siparis_id=siparis_id,
        payment_info=payment_info,
    )


@app.route("/my-orders")
def my_orders():
    guest_id = get_guest_id()
    raw_orders = order_service.get_customer_orders(guest_id)
    order_service.mark_notifications_read(guest_id)
    now = datetime.now()
    customer_orders = []
    for item in raw_orders:
        can_cancel = False
        remaining_seconds = 0
        if item[3] == OrderStatus.NEW.value:
            try:
                created = datetime.fromisoformat(item[4])
                remaining_seconds = max(
                    0,
                    int((created + timedelta(minutes=CUSTOMER_CANCEL_MINUTES) - now).total_seconds()),
                )
                can_cancel = remaining_seconds > 0
            except (TypeError, ValueError):
                pass
        can_edit = item[3] == OrderStatus.NEW.value
        customer_orders.append({
            "siparis_id": item[0],
            "masa_bilgisi": item[1],
            "toplam_tutar": item[2],
            "siparis_durumu": item[3],
            "siparis_tarihi": item[4],
            "can_cancel": can_cancel,
            "can_edit": can_edit,
            "cancel_remaining_seconds": remaining_seconds,
            "servis_turu": item[5],
            "servis_ucreti": item[6],
        })
    return flask.render_template(
        "my_orders.html",
        customer_orders=customer_orders,
        cancel_minutes=CUSTOMER_CANCEL_MINUTES,
    )


@app.route("/my-orders/<int:siparis_id>/edit", methods=["GET", "POST"])
def edit_my_order(siparis_id):
    guest_id = get_guest_id()
    header, items = order_service.get_customer_editable_order(guest_id, siparis_id)
    if header is None:
        flask.abort(404)
    if header[3] != OrderStatus.NEW.value:
        flask.flash("Mutfak hazırlığa başladıktan sonra sipariş düzenlenemez.", "error")
        return flask.redirect(flask.url_for("my_order_detail", siparis_id=siparis_id))

    current = {row[1]: int(row[4]) for row in items}
    service_type = header[6]
    note = header[5] or ""
    errors = {}

    if flask.request.method == "POST":
        current = {}
        for code, value in flask.request.form.items():
            if code.startswith("qty_"):
                try:
                    qty = int(value)
                except ValueError:
                    qty = 0
                if qty > 0:
                    current[code[4:]] = qty
        service_type = flask.request.form.get("service_type", service_type)
        note = flask.request.form.get("note", "").strip()
        try:
            order_service.update_customer_order(guest_id, siparis_id, current, service_type, note or None)
            flask.flash("Siparişiniz güncellendi.", "success")
            return flask.redirect(flask.url_for("my_order_detail", siparis_id=siparis_id))
        except (ValueError, pydantic.ValidationError) as error:
            errors["general"] = str(error)

    stocks = order.get_stok()
    return flask.render_template(
        "my_order_edit.html",
        siparis_id=siparis_id,
        order_header=header,
        current=current,
        stocks=stocks,
        service_type=service_type,
        note=note,
        errors=errors,
    )


@app.route("/my-orders/<int:siparis_id>/cancel", methods=["POST"])
def cancel_my_order(siparis_id):
    success, message = order_service.cancel_customer_order(
        get_guest_id(),
        siparis_id,
        CUSTOMER_CANCEL_MINUTES,
    )
    flask.flash(message, "success" if success else "error")
    return flask.redirect(flask.url_for("my_orders"))


@app.route("/my-orders/<int:siparis_id>")
def my_order_detail(siparis_id):
    guest_id = get_guest_id()
    order_service.mark_notifications_read(guest_id, siparis_id)
    order_header, order_items = order_service.get_customer_order_detail(
        guest_id,
        siparis_id,
    )

    if order_header is None:
        flask.abort(404)

    can_cancel = False
    cancel_remaining_seconds = 0
    if order_header[3] == OrderStatus.NEW.value:
        try:
            created = datetime.fromisoformat(order_header[4])
            cancel_remaining_seconds = max(
                0,
                int((created + timedelta(minutes=CUSTOMER_CANCEL_MINUTES) - datetime.now()).total_seconds()),
            )
            can_cancel = cancel_remaining_seconds > 0
        except (TypeError, ValueError):
            pass

    can_edit = order_header[3] == OrderStatus.NEW.value

    return flask.render_template(
        "my_order_detail.html",
        order_header=order_header,
        order_items=order_items,
        can_cancel=can_cancel,
        can_edit=can_edit,
        cancel_remaining_seconds=cancel_remaining_seconds,
    )


@app.route("/notifications/poll")
def notification_poll():
    try:
        after_id = int(flask.request.args.get("after", "0") or 0)
    except ValueError:
        after_id = 0
    notifications, unread_count, latest_id = order_service.get_unread_notifications(
        get_guest_id(), after_id
    )
    return flask.jsonify({
        "success": True,
        "unread_count": unread_count,
        "latest_id": latest_id,
        "notifications": [
            {
                "id": row[0],
                "siparis_id": row[1],
                "message": row[2],
                "status": row[3],
                "created_at": row[4],
            }
            for row in notifications
        ],
    })


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if flask.session.get("admin_logged_in"):
        return flask.redirect(flask.url_for("admin_dashboard"))

    error = None

    if flask.request.method == "POST":
        username = flask.request.form.get("username", "")
        password = flask.request.form.get("password", "")

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            flask.session["admin_logged_in"] = True
            flask.session.modified = True

            next_url = flask.request.args.get("next")
            if next_url and next_url.startswith("/admin"):
                return flask.redirect(next_url)

            return flask.redirect(flask.url_for("admin_dashboard"))

        error = "Kullanıcı adı veya şifre hatalı."

    return flask.render_template("admin/login.html", error=error)


@app.route("/admin/logout")
@admin_required
def admin_logout():
    flask.session.pop("admin_logged_in", None)
    return flask.redirect(flask.url_for("main_menu"))


@app.route("/admin")
@admin_required
def admin_dashboard():
    return flask.render_template("admin/dashboard.html")


@app.route("/admin/settings")
@admin_required
def admin_settings():
    return flask.render_template("admin/settings.html")


@app.route("/admin/settings/reset-test-data", methods=["POST"])
@admin_required
def admin_reset_test_data():
    database.reset_test_order_data()
    flask.flash("Test siparişleri, ödeme hareketleri ve müşteri bildirimleri temizlendi.", "success")
    return flask.redirect(flask.url_for("admin_settings"))


@app.route("/admin/orders")
@admin_required
def admin_orders():
    orders = restaurant.get_all_orders()
    stats = restaurant.get_dashboard_stats()
    return flask.render_template("admin/orders.html", orders=orders, stats=stats)


@app.route("/admin/orders/<int:siparis_id>")
@admin_required
def admin_order_detail(siparis_id):
    order_header, order_items = restaurant.get_order_detail(siparis_id)

    if order_header is None:
        flask.abort(404)

    return flask.render_template(
        "admin/order_detail.html",
        order_header=order_header,
        order_items=order_items,
        statuses=[OrderStatus.PREPARING.value, OrderStatus.READY.value],
    )


@app.route("/admin/orders/<int:siparis_id>/status", methods=["POST"])
@admin_required
def admin_order_status(siparis_id):
    new_status = flask.request.form.get("siparis_durumu", "")

    try:
        updated = restaurant.update_order_status(siparis_id, new_status)
    except ValueError:
        flask.abort(400)

    if not updated:
        flask.abort(404)

    # Kart üzerinden yapılan mutfak işlemlerinde kullanıcıyı aynı ekranda tut.
    if flask.request.referrer and "/admin/orders" in flask.request.referrer:
        return flask.redirect(flask.request.referrer)
    return flask.redirect(flask.url_for("admin_order_detail", siparis_id=siparis_id))


@app.route("/admin/orders/<int:siparis_id>/archive", methods=["POST"])
@admin_required
def admin_order_archive(siparis_id):
    try:
        removed = restaurant.archive_order(siparis_id)
    except ValueError as error:
        flask.flash(str(error), "error")
        return flask.redirect(flask.url_for("admin_orders"))

    if not removed:
        flask.abort(404)

    flask.flash(f"Sipariş #{siparis_id} operasyon listesinden kaldırıldı.", "success")
    return flask.redirect(flask.url_for("admin_orders"))


@app.route("/admin/stocks", methods=["GET", "POST"])
@admin_required
def admin_stocks():
    error = None

    if flask.request.method == "POST":
        try:
            restaurant.add_stock(
                flask.request.form.get("stok_kodu"),
                flask.request.form.get("stok_adi"),
                flask.request.form.get("fiyat"),
                flask.request.form.get("adet"),
            )
            flask.flash("Yeni stok başarıyla eklendi.", "success")
            return flask.redirect(flask.url_for("admin_stocks"))
        except Exception as exc:
            if "UNIQUE constraint failed" in str(exc):
                error = "Bu stok kodu zaten kullanılıyor."
            else:
                error = str(exc)

    stocks = restaurant.get_all_stocks()
    return flask.render_template("admin/stocks.html", stocks=stocks, error=error)


@app.route("/admin/stocks/<stok_kodu>/update", methods=["POST"])
@admin_required
def admin_stock_update(stok_kodu):
    try:
        updated = restaurant.update_stock(
            stok_kodu,
            flask.request.form.get("stok_kodu"),
            flask.request.form.get("stok_adi"),
            flask.request.form.get("fiyat"),
            flask.request.form.get("adet"),
        )
        if not updated:
            flask.abort(404)
        flask.flash("Stok bilgileri güncellendi.", "success")
    except Exception as exc:
        if "UNIQUE constraint failed" in str(exc):
            flask.flash("Yeni stok kodu başka bir üründe kullanılıyor.", "error")
        else:
            flask.flash(str(exc), "error")
    return flask.redirect(flask.url_for("admin_stocks"))


@app.route("/admin/stocks/<stok_kodu>/delete", methods=["POST"])
@admin_required
def admin_stock_delete(stok_kodu):
    if restaurant.delete_stock(stok_kodu):
        flask.flash(f"{stok_kodu} stok kaydı silindi.", "success")
    else:
        flask.flash("Stok kaydı bulunamadı.", "error")
    return flask.redirect(flask.url_for("admin_stocks"))


@app.route("/admin/statistics")
@admin_required
def admin_statistics():
    stats = restaurant.get_statistics()
    return flask.render_template("admin/statistics.html", stats=stats)


@app.route("/admin/cashier")
@admin_required
def cashier_terminal():
    orders = restaurant.get_unpaid_orders()
    return flask.render_template(
        "admin/cashier.html",
        orders=orders,
    )


@app.route("/admin/cashier/<int:siparis_id>")
@admin_required
def cashier_order_detail(siparis_id):
    order_header, order_items, payments, remaining = restaurant.get_cashier_order_detail(siparis_id)
    if order_header is None:
        flask.abort(404)
    return flask.render_template(
        "admin/cashier_detail.html",
        order_header=order_header,
        order_items=order_items,
        payments=payments,
        remaining=remaining,
        tables=database.get_active_tables(),
    )


@app.route("/admin/cashier/<int:siparis_id>/transfer", methods=["POST"])
@admin_required
def cashier_transfer_table(siparis_id):
    try:
        if not restaurant.transfer_order_table(siparis_id, flask.request.form.get("table")):
            flask.abort(404)
        flask.flash("Masa aktarımı tamamlandı.", "success")
    except ValueError as error:
        flask.flash(str(error), "error")
    return flask.redirect(flask.url_for("cashier_order_detail", siparis_id=siparis_id))


@app.route("/admin/cashier/<int:siparis_id>/pay", methods=["POST"])
@admin_required
def cashier_pay_order(siparis_id):
    method = flask.request.form.get("payment_method", "")
    selection_json = flask.request.form.get("payment_items", "").strip()
    selections = None

    if selection_json:
        try:
            raw = json.loads(selection_json)
            selections = {int(key): int(value) for key, value in raw.items()}
        except (ValueError, TypeError, json.JSONDecodeError):
            flask.flash("Fiş bölme seçimi okunamadı.", "error")
            return flask.redirect(flask.url_for("cashier_order_detail", siparis_id=siparis_id))

    try:
        amount, status = restaurant.cashier_take_payment(siparis_id, method, selections)
        flask.flash(f"{amount:g} TL {method} ödeme alındı.", "success")
        if status == "Ödendi":
            return flask.redirect(flask.url_for("cashier_terminal"))
    except ValueError as error:
        flask.flash(str(error), "error")

    return flask.redirect(flask.url_for("cashier_order_detail", siparis_id=siparis_id))


@app.route("/admin/waiters")
@admin_required
def admin_waiters():
    return flask.render_template(
        "admin/waiters.html",
        waiters=waiter_service.get_all_waiters(),
    )


@app.route("/admin/waiters/add", methods=["POST"])
@admin_required
def admin_waiter_add():
    try:
        waiter_service.create_waiter(
            flask.request.form.get("username"),
            flask.request.form.get("password"),
            flask.request.form.get("full_name"),
        )
        flask.flash("Garson hesabı oluşturuldu.", "success")
    except ValueError as error:
        flask.flash(str(error), "error")
    except Exception:
        app.logger.exception("Garson hesabı oluşturulamadı")
        flask.flash("Garson hesabı oluşturulamadı.", "error")

    return flask.redirect(flask.url_for("admin_waiters"))


@app.route("/admin/waiters/<int:waiter_id>/toggle", methods=["POST"])
@admin_required
def admin_waiter_toggle(waiter_id):
    if waiter_service.toggle_waiter(waiter_id):
        flask.flash("Garson hesabının durumu güncellendi.", "success")
    else:
        flask.flash("Garson hesabı bulunamadı.", "error")

    return flask.redirect(flask.url_for("admin_waiters"))


@app.route("/waiter/login", methods=["GET", "POST"])
def waiter_login():
    if flask.session.get("waiter_id"):
        return flask.redirect(flask.url_for("waiter_dashboard"))

    error = None
    if flask.request.method == "POST":
        username = flask.request.form.get("username", "").strip()
        password = flask.request.form.get("password", "")
        waiter = waiter_service.authenticate_waiter(username, password)

        if waiter is None:
            error = "Kullanıcı adı veya şifre hatalı."
        else:
            flask.session["waiter_id"] = waiter["garson_id"]
            flask.session["waiter_name"] = waiter["ad_soyad"]
            flask.session.modified = True
            return flask.redirect(flask.url_for("waiter_dashboard"))

    return flask.render_template("waiter/login.html", error=error)


@app.route("/waiter/logout")
@waiter_required
def waiter_logout():
    flask.session.pop("waiter_id", None)
    flask.session.pop("waiter_name", None)
    return flask.redirect(flask.url_for("waiter_login"))


@app.route("/waiter")
@waiter_required
def waiter_dashboard():
    waiter_id = flask.session["waiter_id"]
    return flask.render_template(
        "waiter/dashboard.html",
        ready_orders=waiter_service.get_ready_orders(),
        active_orders=waiter_service.get_waiter_active_orders(waiter_id),
        waiter_name=flask.session.get("waiter_name"),
    )


@app.route("/waiter/order/<int:siparis_id>")
@waiter_required
def waiter_order_detail(siparis_id):
    order_info, items = waiter_service.get_waiter_order(
        siparis_id, flask.session["waiter_id"]
    )
    if order_info is None:
        flask.abort(404)
    return flask.render_template(
        "waiter/order_detail.html", order=order_info, items=items
    )


@app.route("/waiter/order/<int:siparis_id>/claim", methods=["POST"])
@waiter_required
def waiter_claim_order(siparis_id):
    success = waiter_service.claim_order(
        siparis_id, flask.session["waiter_id"]
    )
    if not success:
        flask.flash(
            "Bu sipariş başka bir garson tarafından alınmış olabilir.", "error"
        )
    return flask.redirect(flask.url_for("waiter_dashboard"))


@app.route("/waiter/order/<int:siparis_id>/deliver", methods=["POST"])
@waiter_required
def waiter_deliver_order(siparis_id):
    success = waiter_service.deliver_order(
        siparis_id, flask.session["waiter_id"]
    )
    if not success:
        flask.flash("Sipariş teslim edilemedi veya artık size ait değil.", "error")
    return flask.redirect(flask.url_for("waiter_dashboard"))


@app.after_request
def add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    return response


@app.route("/health")
def health_check():
    return flask.jsonify({"status": "ok"})


@app.errorhandler(404)
def not_found(_error):
    return flask.render_template(
        "error.html",
        code=404,
        title="Sayfa bulunamadı",
        message="Aradığınız sayfa taşınmış veya mevcut olmayabilir.",
    ), 404


@app.errorhandler(500)
def server_error(_error):
    return flask.render_template(
        "error.html",
        code=500,
        title="Bir şeyler ters gitti",
        message="İşlem tamamlanamadı. Lütfen kısa süre sonra tekrar deneyin.",
    ), 500


# Eski adreslerle açılmış bookmark/link'ler bozulmasın.
@app.route("/admin/order_detail/<int:siparis_id>")
@admin_required
def legacy_admin_order_detail(siparis_id):
    return flask.redirect(
        flask.url_for("admin_order_detail", siparis_id=siparis_id)
    )


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
