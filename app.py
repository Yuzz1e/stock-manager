import os
from datetime import datetime, timezone

from flask import Flask, jsonify, redirect, render_template, request, send_from_directory, url_for

from models import Category, Equipment, Loan, Place, Shelf, db
from tepra import generate_tepra_csv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LABELS_DIR = os.path.join(BASE_DIR, "labels")


def build_shelf_grid(shelves):
    """
    棚リストをExcel風グリッド用に整形して返す。
    戻り値:
      row_labels  : ['A', 'B', 'C', ...]  （行ヘッダー）
      col_nums    : [1, 2, 3, ...]         （列ヘッダー）
      grid        : {row_label: {col_num: Shelf or None}}
    """
    row_labels_set = {}
    col_nums_set = set()
    for shelf in shelves:
        label = chr(64 + shelf.row_num)
        row_labels_set[shelf.row_num] = label
        col_nums_set.add(shelf.col_num)

    row_labels = [row_labels_set[k] for k in sorted(row_labels_set)]
    col_nums = sorted(col_nums_set)

    grid = {lbl: {} for lbl in row_labels}
    for shelf in shelves:
        lbl = chr(64 + shelf.row_num)
        grid[lbl][shelf.col_num] = shelf

    return row_labels, col_nums, grid


def create_app():
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{os.path.join(BASE_DIR, 'stock.db')}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")

    db.init_app(app)

    with app.app_context():
        db.create_all()

    return app


app = create_app()


# ─── ホーム ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ─── 使用（貸出）───────────────────────────────────────────────────────────────

@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    if request.method == "POST":
        student_id = request.form.get("student_id", "").strip()
        management_id = request.form.get("management_id", "").strip()
        student_name = request.form.get("student_name", "").strip()

        if not student_id or not management_id:
            return render_template("checkout.html", error="学生IDと管理IDを入力してください。")

        equipment = Equipment.query.filter_by(management_id=management_id).first()
        if not equipment:
            return render_template("checkout.html", error=f"管理ID「{management_id}」の機材が見つかりません。")

        if equipment.status == "使用中":
            existing_loan = equipment.current_loan
            borrower = existing_loan.student_id if existing_loan else "不明"
            return render_template(
                "checkout.html",
                error=f"この機材は現在「{borrower}」が使用中です。",
            )

        loan = Loan(
            equipment_id=equipment.id,
            student_id=student_id,
            student_name=student_name or None,
            checked_out_at=datetime.now(timezone.utc),
        )
        equipment.status = "使用中"
        equipment.storage_row = None
        equipment.storage_col = None
        equipment.updated_at = datetime.now(timezone.utc)

        db.session.add(loan)
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
    places = Place.query.order_by(Place.name).all()
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
        shelf_id = request.form.get("shelf_id", "").strip()
        place_id = request.form.get("place_id", "").strip()

        if not management_id or (not shelf_id and not place_id):
            return _render({"error": "管理IDと保管場所（棚または場所）を選択してください。"})

        equipment = Equipment.query.filter_by(management_id=management_id).first()
        if not equipment:
            return _render({"error": f"管理ID「{management_id}」の機材が見つかりません。"})

        location_label = None

        if shelf_id:
            shelf = Shelf.query.get(shelf_id)
            if not shelf:
                return _render({"error": "指定した棚が見つかりません。"})
            equipment.storage_row = shelf.row_num
            equipment.storage_col = shelf.col_num
            equipment.place_id = None
            location_label = shelf.label
        else:
            place = Place.query.get(place_id)
            if not place:
                return _render({"error": "指定した場所が見つかりません。"})
            equipment.storage_row = None
            equipment.storage_col = None
            equipment.place_id = place.id
            location_label = place.name

        if equipment.status == "使用中":
            loan = equipment.current_loan
            if loan:
                loan.returned_at = datetime.now(timezone.utc)
                loan.return_location = location_label

        equipment.status = "保管中"
        equipment.updated_at = datetime.now(timezone.utc)
        db.session.commit()

        return _render({"success": True, "equipment": equipment, "location_label": location_label})

    return _render()


# ─── 新規ラベル発行 ─────────────────────────────────────────────────────────────

@app.route("/new-label", methods=["GET", "POST"])
def new_label():
    categories = Category.query.order_by(Category.name).all()
    shelves = Shelf.query.order_by(Shelf.row_num, Shelf.col_num).all()
    places = Place.query.order_by(Place.name).all()
    row_labels, col_nums, shelf_grid = build_shelf_grid(shelves)

    def _render(extra=None):
        kwargs = dict(
            categories=categories,
            row_labels=row_labels,
            col_nums=col_nums,
            shelf_grid=shelf_grid,
            places=places,
        )
        if extra:
            kwargs.update(extra)
        return render_template("new_label.html", **kwargs)

    if request.method == "POST":
        category_id = request.form.get("category_id", "").strip()
        item_name = request.form.get("item_name", "").strip()
        status = request.form.get("status", "保管中").strip()
        shelf_id = request.form.get("shelf_id", "").strip()
        place_id = request.form.get("place_id", "").strip()
        student_id = request.form.get("student_id", "").strip()
        student_name = request.form.get("student_name", "").strip()

        if not category_id or not item_name:
            return _render({"error": "カテゴリと物品名を入力してください。"})

        category = Category.query.get(category_id)
        if not category:
            return _render({"error": "カテゴリが見つかりません。"})

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

        db.session.commit()

        csv_filename = generate_tepra_csv(
            management_id=management_id,
            labels_dir=LABELS_DIR,
        )

        return _render({"success": True, "equipment": equipment, "csv_file": csv_filename})

    return _render()


# ─── API ──────────────────────────────────────────────────────────────────────

@app.route("/api/equipment/lookup", methods=["POST"])
def api_equipment_lookup():
    data = request.get_json()
    management_id = (data or {}).get("management_id", "").strip()
    if not management_id:
        return jsonify({"error": "管理IDが必要です。"}), 400

    equipment = Equipment.query.filter_by(management_id=management_id).first()
    if not equipment:
        return jsonify({"error": f"管理ID「{management_id}」が見つかりません。"}), 404

    return jsonify(equipment.to_dict())


@app.route("/api/next-number/<int:category_id>")
def api_next_number(category_id):
    category = Category.query.get_or_404(category_id)
    preview_id = f"{category.prefix}{category.next_number:03d}"
    return jsonify({"management_id": preview_id, "next_number": category.next_number})


@app.route("/api/categories", methods=["GET", "POST"])
def api_categories():
    if request.method == "POST":
        data = request.get_json()
        name = (data or {}).get("name", "").strip()
        prefix = (data or {}).get("prefix", "").strip().upper()
        if not name or not prefix:
            return jsonify({"error": "名前とプレフィックスが必要です。"}), 400
        if Category.query.filter_by(prefix=prefix).first():
            return jsonify({"error": f"プレフィックス「{prefix}」は既に使用されています。"}), 409
        category = Category(name=name, prefix=prefix)
        db.session.add(category)
        db.session.commit()
        return jsonify({"id": category.id, "name": category.name, "prefix": category.prefix}), 201

    categories = Category.query.order_by(Category.name).all()
    return jsonify([{"id": c.id, "name": c.name, "prefix": c.prefix, "next_number": c.next_number} for c in categories])


@app.route("/api/shelves", methods=["GET", "POST"])
def api_shelves():
    if request.method == "POST":
        data = request.get_json()
        row_num = (data or {}).get("row_num")
        col_num = (data or {}).get("col_num")
        label = (data or {}).get("label", "").strip()
        if row_num is None or col_num is None or not label:
            return jsonify({"error": "行番号・列番号・ラベルが必要です。"}), 400
        shelf = Shelf(row_num=row_num, col_num=col_num, label=label)
        db.session.add(shelf)
        db.session.commit()
        return jsonify({"id": shelf.id, "row_num": shelf.row_num, "col_num": shelf.col_num, "label": shelf.label}), 201

    shelves = Shelf.query.order_by(Shelf.row_num, Shelf.col_num).all()
    return jsonify([{"id": s.id, "row_num": s.row_num, "col_num": s.col_num, "label": s.label} for s in shelves])


@app.route("/api/places", methods=["GET", "POST"])
def api_places():
    if request.method == "POST":
        data = request.get_json()
        name = (data or {}).get("name", "").strip()
        if not name:
            return jsonify({"error": "場所名が必要です。"}), 400
        if Place.query.filter_by(name=name).first():
            return jsonify({"error": f"「{name}」は既に登録されています。"}), 409
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


@app.route("/api/loans")
def api_loans():
    active_only = request.args.get("active") == "1"
    query = Loan.query
    if active_only:
        query = query.filter_by(returned_at=None)
    loans = query.order_by(Loan.checked_out_at.desc()).limit(100).all()
    return jsonify([l.to_dict() for l in loans])


# ─── 静的ファイル配信 ──────────────────────────────────────────────────────────

@app.route("/labels/<path:filename>")
def serve_label(filename):
    return send_from_directory(LABELS_DIR, filename)


# ─── 管理画面 ─────────────────────────────────────────────────────────────────

@app.route("/admin")
def admin():
    categories = Category.query.order_by(Category.name).all()
    shelves = Shelf.query.order_by(Shelf.row_num, Shelf.col_num).all()
    places = Place.query.order_by(Place.name).all()
    active_loans = Loan.query.filter_by(returned_at=None).order_by(Loan.checked_out_at.desc()).all()
    equipment_list = Equipment.query.order_by(Equipment.management_id).all()
    return render_template(
        "admin.html",
        categories=categories,
        shelves=shelves,
        places=places,
        active_loans=active_loans,
        equipment_list=equipment_list,
    )


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5001)
    args = parser.parse_args()
    app.run(debug=True, host="0.0.0.0", port=args.port)
