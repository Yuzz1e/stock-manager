from datetime import datetime, timezone, timedelta
from flask_sqlalchemy import SQLAlchemy


def _utc_iso(dt):
    """naive/aware UTC datetime を +00:00 付き ISO 文字列に変換する"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()

db = SQLAlchemy()


class Category(db.Model):
    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    prefix = db.Column(db.String(10), nullable=False, unique=True)
    next_number = db.Column(db.Integer, nullable=False, default=1)

    equipment = db.relationship("Equipment", back_populates="category", lazy="dynamic")

    def __repr__(self):
        return f"<Category {self.prefix}: {self.name}>"


class Shelf(db.Model):
    __tablename__ = "shelves"

    id = db.Column(db.Integer, primary_key=True)
    row_num = db.Column(db.Integer, nullable=False)
    col_num = db.Column(db.Integer, nullable=False)
    label = db.Column(db.String(20), nullable=False)

    __table_args__ = (db.UniqueConstraint("row_num", "col_num", name="uq_shelf_position"),)

    def __repr__(self):
        return f"<Shelf {self.label}>"


class Place(db.Model):
    """棚以外の保管場所（レンタルラボ、倉庫など）"""
    __tablename__ = "places"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)

    equipment = db.relationship("Equipment", back_populates="place", lazy="dynamic")

    def __repr__(self):
        return f"<Place {self.name}>"


class Equipment(db.Model):
    __tablename__ = "equipment"

    id = db.Column(db.Integer, primary_key=True)
    management_id = db.Column(db.String(20), nullable=False, unique=True)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=False)
    item_name = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="保管中")
    storage_row = db.Column(db.Integer, nullable=True)
    storage_col = db.Column(db.Integer, nullable=True)
    place_id = db.Column(db.Integer, db.ForeignKey("places.id"), nullable=True)
    supply_year = db.Column(db.String(10),  nullable=True)
    supply_code = db.Column(db.String(50),  nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    category = db.relationship("Category", back_populates="equipment")
    place = db.relationship("Place", back_populates="equipment")
    loans = db.relationship("Loan", back_populates="equipment", lazy="dynamic")

    @property
    def supply_label(self):
        """用品ラベルの表示文字列（例: 2022年度　H0196）"""
        if self.supply_year and self.supply_code:
            return f"{self.supply_year}年度　{self.supply_code}"
        if self.supply_code:
            return self.supply_code
        return None

    @property
    def storage_label(self):
        if self.storage_row is not None and self.storage_col is not None:
            return f"{chr(64 + self.storage_row)}-{self.storage_col}"
        if self.place:
            return self.place.name
        return None

    @property
    def current_loan(self):
        return self.loans.filter_by(returned_at=None).first()

    def to_dict(self):
        loan = self.current_loan
        return {
            "id": self.id,
            "management_id": self.management_id,
            "item_name": self.item_name,
            "status": self.status,
            "storage_label": self.storage_label,
            "storage_row": self.storage_row,
            "storage_col": self.storage_col,
            "place_id": self.place_id,
            "place_name": self.place.name if self.place else None,
            "category_name": self.category.name if self.category else None,
            "current_borrower": loan.student_name if loan else None,
            "student_id": loan.student_id if loan else None,
            "supply_year": self.supply_year,
            "supply_code": self.supply_code,
            "supply_label": self.supply_label,
            "created_at": _utc_iso(self.created_at),
        }

    def __repr__(self):
        return f"<Equipment {self.management_id}: {self.item_name}>"


class Loan(db.Model):
    __tablename__ = "loans"

    id = db.Column(db.Integer, primary_key=True)
    equipment_id = db.Column(db.Integer, db.ForeignKey("equipment.id"), nullable=False)
    student_id = db.Column(db.String(50), nullable=False)
    student_name = db.Column(db.String(100), nullable=True)
    checked_out_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    returned_at = db.Column(db.DateTime, nullable=True)
    return_location = db.Column(db.String(20), nullable=True)

    equipment = db.relationship("Equipment", back_populates="loans")

    def to_dict(self):
        return {
            "id": self.id,
            "equipment_id": self.equipment_id,
            "management_id": self.equipment.management_id if self.equipment else None,
            "item_name": self.equipment.item_name if self.equipment else None,
            "student_id": self.student_id,
            "student_name": self.student_name,
            "checked_out_at": _utc_iso(self.checked_out_at),
            "returned_at": _utc_iso(self.returned_at),
            "return_location": self.return_location,
        }

    def __repr__(self):
        return f"<Loan {self.id}: {self.student_id} -> {self.equipment_id}>"


class ActivityLog(db.Model):
    """すべての操作履歴を記録するログテーブル"""
    __tablename__ = "activity_logs"

    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    action = db.Column(db.String(30), nullable=False, index=True)
    management_id = db.Column(db.String(20), nullable=True, index=True)
    item_name = db.Column(db.String(200), nullable=True)
    student_id = db.Column(db.String(50), nullable=True, index=True)
    student_name = db.Column(db.String(100), nullable=True)
    details = db.Column(db.String(300), nullable=True)

    ACTION_LABELS = {
        "checkout":     "使用開始",
        "return":       "返却",
        "register":     "新規登録",
        "force_return": "強制返却",
    }

    def to_dict(self):
        return {
            "id": self.id,
            "timestamp": _utc_iso(self.timestamp),
            "action": self.action,
            "action_label": self.ACTION_LABELS.get(self.action, self.action),
            "management_id": self.management_id,
            "item_name": self.item_name,
            "student_id": self.student_id,
            "student_name": self.student_name,
            "details": self.details,
        }

    def __repr__(self):
        return f"<ActivityLog {self.id}: {self.action} {self.management_id}>"
