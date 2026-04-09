"""
初期データ投入スクリプト
実行: python seed.py
"""
from app import app
from models import Category, Shelf, db


def seed():
    with app.app_context():
        # カテゴリ
        default_categories = [
            {"name": "カメラ", "prefix": "CAM"},
            {"name": "三脚", "prefix": "TRP"},
            {"name": "レンズ", "prefix": "LNS"},
            {"name": "照明機材", "prefix": "LGT"},
            {"name": "音声機材", "prefix": "AUD"},
            {"name": "PC・タブレット", "prefix": "PCB"},
            {"name": "ケーブル・アダプタ", "prefix": "CBL"},
            {"name": "その他", "prefix": "OTH"},
        ]
        for cat_data in default_categories:
            if not Category.query.filter_by(prefix=cat_data["prefix"]).first():
                db.session.add(Category(name=cat_data["name"], prefix=cat_data["prefix"]))
                print(f"  カテゴリ追加: {cat_data['name']} ({cat_data['prefix']})")

        # 棚マスタ（5列 × 4行）
        # 行: A, B, C, D / 列: 1〜5
        rows = 4
        cols = 5
        for row in range(1, rows + 1):
            for col in range(1, cols + 1):
                label = f"{chr(64 + row)}-{col}"
                if not Shelf.query.filter_by(row_num=row, col_num=col).first():
                    db.session.add(Shelf(row_num=row, col_num=col, label=label))
                    print(f"  棚追加: {label}")

        db.session.commit()
        print("\nシードデータ投入完了。")


if __name__ == "__main__":
    seed()
