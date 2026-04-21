import json
import logging
import os
import queue

# scanner ロガーを INFO レベルで出力する
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("scanner").setLevel(logging.INFO)
# werkzeug ログは WARNING 以上のみ表示（ブロックログで埋もれを防ぐ）
logging.getLogger("werkzeug").setLevel(logging.WARNING)

from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, redirect, render_template, request, send_from_directory, session, stream_with_context, url_for
from flask_babel import Babel, gettext as _, lazy_gettext as _l
from sqlalchemy import text

from models import ActivityLog, Category, Equipment, Loan, Place, Shelf, db
from tepra import generate_tepra_csv, print_tepra_label
from scanner_threads import broadcaster, start_all

load_dotenv()

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
LABELS_DIR = os.path.join(BASE_DIR, "labels")

# テプラ SPC10 設定
TEPRA_SPC10_PATH = os.environ.get(
    "TEPRA_SPC10_PATH",
    r"C:\Program Files (x86)\KING JIM\TEPRA Label Editor SPC10\SPC10.exe",
)
TEPRA_LW1_PATH = os.environ.get("TEPRA_LW1_PATH", "")
TEPRA_TEMP_DIR = os.environ.get("TEPRA_TEMP_DIR", os.path.join(BASE_DIR, "labels", "temp"))
TEPRA_COPIES   = int(os.environ.get("TEPRA_COPIES", "1"))

# スキャナー設定
SCANNER_SERIAL_PORT     = os.environ.get("SCANNER_SERIAL_PORT", "COM5")
SCANNER_SERIAL_BAUDRATE = int(os.environ.get("SCANNER_SERIAL_BAUDRATE", "9600"))
SCANNER_NFC_ENABLED     = os.environ.get("SCANNER_NFC_ENABLED", "true").lower() == "true"

# i18n 設定
SUPPORTED_LOCALES = ["ja", "en"]


def get_locale():
    """セッション優先 → Accept-Language → デフォルト(ja) の順でロケールを決定する"""
    lang = session.get("lang")
    if lang in SUPPORTED_LOCALES:
        return lang
    return request.accept_languages.best_match(SUPPORTED_LOCALES) or "ja"


def build_shelf_grid(shelves):
    row_labels_set = {}
    col_nums_set   = set()
    for shelf in shelves:
        label = chr(64 + shelf.row_num)
        row_labels_set[shelf.row_num] = label
        col_nums_set.add(shelf.col_num)

    row_labels = [row_labels_set[k] for k in sorted(row_labels_set)]
    col_nums   = sorted(col_nums_set)

    grid = {lbl: {} for lbl in row_labels}
    for shelf in shelves:
        lbl = chr(64 + shelf.row_num)
        grid[lbl][shelf.col_num] = shelf

    return row_labels, col_nums, grid


def create_app():
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{os.path.join(BASE_DIR, 'stock.db')}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["BABEL_DEFAULT_LOCALE"] = "ja"
    app.config["BABEL_SUPPORTED_LOCALES"] = SUPPORTED_LOCALES
    app.config["BABEL_DEFAULT_TIMEZONE"] = "Asia/Tokyo"
    app.config["BABEL_TRANSLATION_DIRECTORIES"] = os.path.join(BASE_DIR, "translations")
    app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")

    db.init_app(app)
    Babel(app, locale_selector=get_locale)

    # テンプレート内で現在のロケールを参照できるようにする
    app.jinja_env.globals["get_locale"] = get_locale

    with app.app_context():
        db.create_all()
        _migrate(db)
        _seed_shelves()

    return app


def _migrate(db):
    """既存DBへのカラム追加など後方互換マイグレーション"""
    with db.engine.connect() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(equipment)"))}
        for col, ddl in [
            ("supply_year", "ALTER TABLE equipment ADD COLUMN supply_year VARCHAR(10)"),
            ("supply_code", "ALTER TABLE equipment ADD COLUMN supply_code VARCHAR(50)"),
        ]:
            if col not in cols:
                conn.execute(text(ddl))
        conn.commit()


def _seed_shelves():
    """棚マスタを自動初期化する（A〜F 行 × 1〜6 列 = 36マス）"""
    rows = 6  # A〜F
    cols = 6  # 1〜6
    for row in range(1, rows + 1):
        for col in range(1, cols + 1):
            label = f"{chr(64 + row)}-{col}"
            if not Shelf.query.filter_by(row_num=row, col_num=col).first():
                db.session.add(Shelf(row_num=row, col_num=col, label=label))
    db.session.commit()


app = create_app()


@app.template_filter("jst")
def to_jst(dt, fmt="%Y/%m/%d %H:%M"):
    """UTC naive/aware datetime を JST に変換してフォーマットする"""
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(JST).strftime(fmt)


# ─── ホーム ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ─── 言語切替 ────────────────────────────────────────────────────────────────

@app.route("/i18n/<lang>")
def set_language(lang):
    if lang in SUPPORTED_LOCALES:
        session["lang"] = lang
    return redirect(request.referrer or url_for("index"))


# ─── 使用（貸出）───────────────────────────────────────────────────────────────

@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    if request.method == "POST":
        student_id    = request.form.get("student_id",    "").strip()
        management_id = request.form.get("management_id", "").strip()
        student_name  = request.form.get("student_name",  "").strip()

        if not student_id or not management_id:
            return render_template("checkout.html", error=_("学生IDと管理IDを入力してください。"))

        equipment = Equipment.query.filter_by(management_id=management_id).first()
        if not equipment:
            return render_template(
                "checkout.html",
                error=_("管理ID「%(mid)s」の機材が見つかりません。", mid=management_id),
            )

        if equipment.status == "使用中":
            existing_loan = equipment.current_loan
            borrower = existing_loan.student_id if existing_loan else _("不明")
            return render_template(
                "checkout.html",
                error=_("この機材は現在「%(borrower)s」が使用中です。", borrower=borrower),
            )

        loan = Loan(
            equipment_id=equipment.id,
            student_id=student_id,
            student_name=student_name or None,
            checked_out_at=datetime.now(timezone.utc),
        )
        equipment.status      = "使用中"
        equipment.storage_row = None
        equipment.storage_col = None
        equipment.updated_at  = datetime.now(timezone.utc)

        db.session.add(loan)
        db.session.add(ActivityLog(
            action="checkout",
            management_id=equipment.management_id,
            item_name=equipment.item_name,
            student_id=student_id,
            student_name=student_name or None,
        ))
        db.session.commit()

        return render_template(
            "checkout.html",
            success=True,
            equipment=equipment,
            student_id=student_id,
            student_name=student_name,
        )

    return render_template("checkout.html")


# ─── 保管・返却 ────────────────────────────────────────────────────────────────

@app.route("/return", methods=["GET", "POST"])
def return_item():
    shelves = Shelf.query.order_by(Shelf.row_num, Shelf.col_num).all()
    places  = Place.query.order_by(Place.name).all()
    row_labels, col_nums, shelf_grid = build_shelf_grid(shelves)

    def _render(extra=None):
        kwargs = dict(
            row_labels=row_labels, col_nums=col_nums, shelf_grid=shelf_grid,
            places=places,
        )
        if extra:
            kwargs.update(extra)
        return render_template("return.html", **kwargs)

    if request.method == "POST":
        management_id = request.form.get("management_id", "").strip()
        shelf_id      = request.form.get("shelf_id",      "").strip()
        place_id      = request.form.get("place_id",      "").strip()

        if not management_id or (not shelf_id and not place_id):
            return _render({"error": _("管理IDと保管場所（棚または場所）を選択してください。")})

        equipment = Equipment.query.filter_by(management_id=management_id).first()
        if not equipment:
            return _render({"error": _("管理ID「%(mid)s」の機材が見つかりません。", mid=management_id)})

        location_label = None

        if shelf_id:
            shelf = Shelf.query.get(shelf_id)
            if not shelf:
                return _render({"error": _("指定した棚が見つかりません。")})
            equipment.storage_row = shelf.row_num
            equipment.storage_col = shelf.col_num
            equipment.place_id    = None
            location_label        = shelf.label
        else:
            place = Place.query.get(place_id)
            if not place:
                return _render({"error": _("指定した場所が見つかりません。")})
            equipment.storage_row = None
            equipment.storage_col = None
            equipment.place_id    = place.id
            location_label        = place.name

        returning_student_id   = None
        returning_student_name = None
        if equipment.status == "使用中":
            loan = equipment.current_loan
            if loan:
                returning_student_id   = loan.student_id
                returning_student_name = loan.student_name
                loan.returned_at       = datetime.now(timezone.utc)
                loan.return_location   = location_label

        equipment.status     = "保管中"
        equipment.updated_at = datetime.now(timezone.utc)
        db.session.add(ActivityLog(
            action="return",
            management_id=equipment.management_id,
            item_name=equipment.item_name,
            student_id=returning_student_id,
            student_name=returning_student_name,
            details=_("返却先: %(loc)s", loc=location_label),
        ))
        db.session.commit()

        return _render({"success": True, "equipment": equipment, "location_label": location_label})

    return _render()


# ─── 新規ラベル発行 ─────────────────────────────────────────────────────────────

@app.route("/new-label", methods=["GET", "POST"])
def new_label():
    categories = Category.query.order_by(Category.name).all()
    shelves    = Shelf.query.order_by(Shelf.row_num, Shelf.col_num).all()
    places     = Place.query.order_by(Place.name).all()
    row_labels, col_nums, shelf_grid = build_shelf_grid(shelves)

    def _render(extra=None):
        kwargs = dict(
            categories=categories,
            row_labels=row_labels, col_nums=col_nums, shelf_grid=shelf_grid,
            places=places,
        )
        if extra:
            kwargs.update(extra)
        return render_template("new_label.html", **kwargs)

    if request.method == "POST":
        category_id  = request.form.get("category_id",  "").strip()
        item_name    = request.form.get("item_name",     "").strip()
        status       = request.form.get("status",        "保管中").strip()
        shelf_id     = request.form.get("shelf_id",      "").strip()
        place_id     = request.form.get("place_id",      "").strip()
        student_id   = request.form.get("student_id",    "").strip()
        student_name = request.form.get("student_name",  "").strip()
        supply_year  = request.form.get("supply_year",   "").strip() or None
        supply_code  = request.form.get("supply_code",   "").strip() or None

        if not category_id or not item_name:
            return _render({"error": _("カテゴリと物品名を入力してください。")})

        category = Category.query.get(category_id)
        if not category:
            return _render({"error": _("カテゴリが見つかりません。")})

        management_id = f"{category.prefix}{category.next_number:03d}"
        category.next_number += 1

        storage_row = storage_col = eq_place_id = None

        if status == "保管中":
            if shelf_id:
                shelf = Shelf.query.get(shelf_id)
                if shelf:
                    storage_row = shelf.row_num
                    storage_col = shelf.col_num
            elif place_id:
                eq_place_id = int(place_id)

        equipment = Equipment(
            management_id=management_id,
            category_id=category.id,
            item_name=item_name,
            status=status,
            storage_row=storage_row,
            storage_col=storage_col,
            place_id=eq_place_id,
            supply_year=supply_year,
            supply_code=supply_code,
        )
        db.session.add(equipment)
        db.session.flush()

        if status == "使用中" and student_id:
            loan = Loan(
                equipment_id=equipment.id,
                student_id=student_id,
                student_name=student_name or None,
                checked_out_at=datetime.now(timezone.utc),
            )
            db.session.add(loan)

        reg_details_parts = [_("カテゴリ: %(name)s", name=category.name)]
        if supply_year or supply_code:
            reg_details_parts.append(_("用品ラベル: %(label)s", label=equipment.supply_label))
        db.session.add(ActivityLog(
            action="register",
            management_id=management_id,
            item_name=item_name,
            student_id=student_id or None,
            student_name=student_name or None,
            details="　".join(reg_details_parts),
        ))
        db.session.commit()

        purchase_date = equipment.created_at.strftime("%Y/%m/%d")
        csv_filename  = generate_tepra_csv(
            management_id=management_id,
            labels_dir=LABELS_DIR,
            purchase_date=purchase_date,
        )
        csv_filepath = os.path.join(LABELS_DIR, csv_filename)

        print_ok, print_error = print_tepra_label(
            csv_filepath=csv_filepath,
            lw1_path=TEPRA_LW1_PATH,
            spc10_path=TEPRA_SPC10_PATH,
            temp_dir=TEPRA_TEMP_DIR,
            copies=TEPRA_COPIES,
        )

        return _render({
            "success":     True,
            "equipment":   equipment,
            "csv_file":    csv_filename,
            "print_ok":    print_ok,
            "print_error": print_error,
        })

    return _render()


# ─── SSE: スキャナーイベント配信 ──────────────────────────────────────────────

@app.route("/api/scan-events")
def scan_events():
    """SSE エンドポイント: NFC / シリアルスキャナーのリアルタイムイベントを配信する。"""
    def generate():
        q = broadcaster.subscribe()
        # 接続直後に現在のリーダー状態を送信
        yield (
            f"event: reader_status\n"
            f"data: {json.dumps(broadcaster.status(), ensure_ascii=False)}\n\n"
        )
        try:
            while True:
                try:
                    msg = q.get(timeout=25)
                    yield msg
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            broadcaster.unsubscribe(q)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control":     "no-cache",
            "X-Accel-Buffering": "no",
            "Connection":        "keep-alive",
        },
    )


@app.route("/api/scanner/status")
def api_scanner_status():
    return jsonify(broadcaster.status())


# ─── API ──────────────────────────────────────────────────────────────────────

@app.route("/api/checkout", methods=["POST"])
def api_checkout():
    data          = request.get_json()
    student_id    = (data or {}).get("student_id",    "").strip()
    management_id = (data or {}).get("management_id", "").strip()
    student_name  = (data or {}).get("student_name",  "").strip()

    if not student_id or not management_id:
        return jsonify({"error": _("学生IDと管理IDを入力してください。")}), 400

    equipment = Equipment.query.filter_by(management_id=management_id).first()
    if not equipment:
        return jsonify({"error": _("管理ID「%(mid)s」の機材が見つかりません。", mid=management_id)}), 404

    if equipment.status == "使用中":
        existing = equipment.current_loan
        borrower = existing.student_id if existing else _("不明")
        return jsonify({
            "error":         "already_in_use",
            "message":       _("この機材は現在「%(borrower)s」が使用中です。", borrower=borrower),
            "borrower_id":   existing.student_id   if existing else None,
            "borrower_name": existing.student_name if existing else None,
        }), 409

    now  = datetime.now(timezone.utc)
    loan = Loan(
        equipment_id=equipment.id,
        student_id=student_id,
        student_name=student_name or None,
        checked_out_at=now,
    )
    equipment.status      = "使用中"
    equipment.storage_row = None
    equipment.storage_col = None
    equipment.updated_at  = now
    db.session.add(loan)
    db.session.add(ActivityLog(
        action="checkout",
        management_id=equipment.management_id,
        item_name=equipment.item_name,
        student_id=student_id,
        student_name=student_name or None,
    ))
    db.session.commit()
    return jsonify({
        "success":      True,
        "management_id": equipment.management_id,
        "item_name":    equipment.item_name,
        "student_id":   student_id,
        "student_name": student_name or None,
    })


@app.route("/api/checkout/force", methods=["POST"])
def api_checkout_force():
    """使用中の機材を強制的に別の使用者に切り替える"""
    data          = request.get_json()
    student_id    = (data or {}).get("student_id",    "").strip()
    management_id = (data or {}).get("management_id", "").strip()
    student_name  = (data or {}).get("student_name",  "").strip()

    if not student_id or not management_id:
        return jsonify({"error": _("学生IDと管理IDを入力してください。")}), 400

    equipment = Equipment.query.filter_by(management_id=management_id).first()
    if not equipment:
        return jsonify({"error": _("管理ID「%(mid)s」の機材が見つかりません。", mid=management_id)}), 404

    now = datetime.now(timezone.utc)

    if equipment.status == "使用中":
        existing = equipment.current_loan
        if existing:
            existing.returned_at     = now
            existing.return_location = _("強制変更")
            db.session.add(ActivityLog(
                action="force_return",
                management_id=equipment.management_id,
                item_name=equipment.item_name,
                student_id=existing.student_id,
                student_name=existing.student_name,
                details=_("使用者変更により強制返却 → %(sid)s", sid=student_id),
            ))

    loan = Loan(
        equipment_id=equipment.id,
        student_id=student_id,
        student_name=student_name or None,
        checked_out_at=now,
    )
    equipment.status      = "使用中"
    equipment.storage_row = None
    equipment.storage_col = None
    equipment.updated_at  = now
    db.session.add(loan)
    db.session.add(ActivityLog(
        action="checkout",
        management_id=equipment.management_id,
        item_name=equipment.item_name,
        student_id=student_id,
        student_name=student_name or None,
        details=_("使用者変更（強制チェックアウト）"),
    ))
    db.session.commit()
    return jsonify({
        "success":       True,
        "management_id": equipment.management_id,
        "item_name":     equipment.item_name,
        "student_id":    student_id,
        "student_name":  student_name or None,
    })


@app.route("/api/equipment/lookup", methods=["POST"])
def api_equipment_lookup():
    data          = request.get_json()
    management_id = (data or {}).get("management_id", "").strip()
    if not management_id:
        return jsonify({"error": _("管理IDが必要です。")}), 400

    equipment = Equipment.query.filter_by(management_id=management_id).first()
    if not equipment:
        return jsonify({"error": _("管理ID「%(mid)s」が見つかりません。", mid=management_id)}), 404

    return jsonify(equipment.to_dict())


@app.route("/api/next-number/<int:category_id>")
def api_next_number(category_id):
    category   = Category.query.get_or_404(category_id)
    preview_id = f"{category.prefix}{category.next_number:03d}"
    return jsonify({"management_id": preview_id, "next_number": category.next_number})


@app.route("/api/categories", methods=["GET", "POST"])
def api_categories():
    if request.method == "POST":
        data   = request.get_json()
        name   = (data or {}).get("name",   "").strip()
        prefix = (data or {}).get("prefix", "").strip().upper()
        if not name or not prefix:
            return jsonify({"error": _("名前とプレフィックスが必要です。")}), 400
        if Category.query.filter_by(prefix=prefix).first():
            return jsonify({"error": _("プレフィックス「%(prefix)s」は既に使用されています。", prefix=prefix)}), 409
        category = Category(name=name, prefix=prefix)
        db.session.add(category)
        db.session.commit()
        return jsonify({"id": category.id, "name": category.name, "prefix": category.prefix}), 201

    categories = Category.query.order_by(Category.name).all()
    return jsonify([{"id": c.id, "name": c.name, "prefix": c.prefix, "next_number": c.next_number} for c in categories])


@app.route("/api/categories/<int:category_id>", methods=["DELETE"])
def api_category_delete(category_id):
    category = Category.query.get_or_404(category_id)
    in_use   = Equipment.query.filter_by(category_id=category_id).count()
    if in_use:
        return jsonify({"error": _("このカテゴリには %(n)d 件の機材が登録されているため削除できません。", n=in_use)}), 409
    db.session.delete(category)
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/shelves", methods=["GET", "POST"])
def api_shelves():
    if request.method == "POST":
        data    = request.get_json()
        row_num = (data or {}).get("row_num")
        col_num = (data or {}).get("col_num")
        label   = (data or {}).get("label", "").strip()
        if row_num is None or col_num is None or not label:
            return jsonify({"error": _("行番号・列番号・ラベルが必要です。")}), 400
        shelf = Shelf(row_num=row_num, col_num=col_num, label=label)
        db.session.add(shelf)
        db.session.commit()
        return jsonify({"id": shelf.id, "row_num": shelf.row_num, "col_num": shelf.col_num, "label": shelf.label}), 201

    shelves = Shelf.query.order_by(Shelf.row_num, Shelf.col_num).all()
    return jsonify([{"id": s.id, "row_num": s.row_num, "col_num": s.col_num, "label": s.label} for s in shelves])


@app.route("/api/shelves/<int:shelf_id>", methods=["DELETE"])
def api_shelf_delete(shelf_id):
    shelf  = Shelf.query.get_or_404(shelf_id)
    in_use = Equipment.query.filter_by(storage_row=shelf.row_num, storage_col=shelf.col_num).count()
    if in_use:
        return jsonify({"error": _("この棚には %(n)d 件の機材が保管されているため削除できません。", n=in_use)}), 409
    db.session.delete(shelf)
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/places", methods=["GET", "POST"])
def api_places():
    if request.method == "POST":
        data = request.get_json()
        name = (data or {}).get("name", "").strip()
        if not name:
            return jsonify({"error": _("場所名が必要です。")}), 400
        if Place.query.filter_by(name=name).first():
            return jsonify({"error": _("「%(name)s」は既に登録されています。", name=name)}), 409
        place = Place(name=name)
        db.session.add(place)
        db.session.commit()
        return jsonify({"id": place.id, "name": place.name}), 201

    places = Place.query.order_by(Place.name).all()
    return jsonify([{"id": p.id, "name": p.name} for p in places])


@app.route("/api/places/<int:place_id>", methods=["DELETE"])
def api_place_delete(place_id):
    place = Place.query.get_or_404(place_id)
    db.session.delete(place)
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/equipment")
def api_equipment_list():
    keyword = request.args.get("q", "").strip()
    query   = Equipment.query
    if keyword:
        like  = f"%{keyword}%"
        query = query.filter(
            db.or_(
                Equipment.management_id.ilike(like),
                Equipment.item_name.ilike(like),
                Equipment.supply_code.ilike(like),
                Equipment.supply_year.ilike(like),
            )
        )
    items = query.order_by(Equipment.management_id).limit(300).all()
    return jsonify([e.to_dict() for e in items])


@app.route("/api/loans")
def api_loans():
    active_only = request.args.get("active") == "1"
    query       = Loan.query
    if active_only:
        query = query.filter_by(returned_at=None)
    loans = query.order_by(Loan.checked_out_at.desc()).limit(100).all()
    return jsonify([l.to_dict() for l in loans])


@app.route("/api/activity-logs")
def api_activity_logs():
    action_filter = request.args.get("action", "").strip()
    keyword       = request.args.get("q", "").strip()
    limit         = min(int(request.args.get("limit", 200)), 500)
    offset        = int(request.args.get("offset", 0))

    query = ActivityLog.query
    if action_filter:
        query = query.filter_by(action=action_filter)
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            db.or_(
                ActivityLog.management_id.ilike(like),
                ActivityLog.item_name.ilike(like),
                ActivityLog.student_id.ilike(like),
                ActivityLog.student_name.ilike(like),
            )
        )
    total  = query.count()
    logs   = query.order_by(ActivityLog.timestamp.desc()).offset(offset).limit(limit).all()
    return jsonify({"total": total, "logs": [l.to_dict() for l in logs]})


# ─── 静的ファイル配信 ──────────────────────────────────────────────────────────

@app.route("/labels/<path:filename>")
def serve_label(filename):
    return send_from_directory(LABELS_DIR, filename)


# ─── 管理画面 ─────────────────────────────────────────────────────────────────

@app.route("/admin")
def admin():
    categories     = Category.query.order_by(Category.name).all()
    shelves        = Shelf.query.order_by(Shelf.row_num, Shelf.col_num).all()
    places         = Place.query.order_by(Place.name).all()
    active_loans   = Loan.query.filter_by(returned_at=None).order_by(Loan.checked_out_at.desc()).all()
    equipment_list = Equipment.query.order_by(Equipment.management_id).all()
    activity_logs  = ActivityLog.query.order_by(ActivityLog.timestamp.desc()).limit(200).all()
    log_total      = ActivityLog.query.count()
    return render_template(
        "admin.html",
        categories=categories,
        shelves=shelves,
        places=places,
        active_loans=active_loans,
        equipment_list=equipment_list,
        activity_logs=activity_logs,
        log_total=log_total,
    )


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5001)
    args = parser.parse_args()

    # use_reloader=False にしてプロセスを必ず 1つに固定する。
    # Werkzeug リローダー有効時に招かれた子プロセスが COM ポートを二重オープンする問題を防ぐ。
    # また、app.run(debug=True) 呼び出し前は app.debug == False なので、
    # 旧来の "not app.debug" チェックは常に True になり両プロセスで起動していた。
    USE_RELOADER = False

    # リローダーなし -> 起動時必ずスレッド起動
    # リローダーあり -> WERKZEUG_RUN_MAIN=true の子プロセスでのみ起動
    if not USE_RELOADER or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        start_all(
            port=SCANNER_SERIAL_PORT,
            baudrate=SCANNER_SERIAL_BAUDRATE,
            nfc_enabled=SCANNER_NFC_ENABLED,
        )

    app.run(debug=True, host="0.0.0.0", port=args.port,
            threaded=True, use_reloader=USE_RELOADER)
