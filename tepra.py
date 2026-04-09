"""
テプラ SR3700P 向け CSV 生成モジュール。

テプラPROソフトウェアの「差し込み印刷」機能を使用する前提：
  1. テプラPROソフトウェアで .lw1 テンプレートを事前に作成しておく
  2. テンプレートのフィールド名を以下の列名と対応させる:
       - management_id : 管理ID（例 CAM001）
  3. このスクリプトが出力するCSVをテプラソフトで読み込んで印刷する

将来的には subprocess でテプラソフトを自動起動することも可能。
"""
import csv
import os
from datetime import datetime


TEPRA_CSV_FIELDS = ["management_id"]


def generate_tepra_csv(management_id: str, labels_dir: str) -> str:
    """
    テプラ差し込み用CSVファイルを生成して保存し、ファイル名を返す。
    CSV文字コードはShift_JIS（テプラソフト標準）。
    """
    os.makedirs(labels_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"tepra_{management_id}_{timestamp}.csv"
    filepath = os.path.join(labels_dir, filename)

    with open(filepath, "w", newline="", encoding="shift_jis", errors="replace") as f:
        writer = csv.DictWriter(f, fieldnames=TEPRA_CSV_FIELDS)
        writer.writeheader()
        writer.writerow({"management_id": management_id})

    return filename


def generate_tepra_csv_bulk(management_ids: list[str], labels_dir: str) -> str:
    """
    複数管理IDの一括CSV生成。
    """
    os.makedirs(labels_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"tepra_bulk_{timestamp}.csv"
    filepath = os.path.join(labels_dir, filename)

    with open(filepath, "w", newline="", encoding="shift_jis", errors="replace") as f:
        writer = csv.DictWriter(f, fieldnames=TEPRA_CSV_FIELDS)
        writer.writeheader()
        for mid in management_ids:
            writer.writerow({"management_id": mid})

    return filename
