"""
テプラ SPC10 向け CSV 生成・自動印刷モジュール。

CSV フォーマット（固定ヘッダー）:
  管理番号, 購入日, QRｺｰﾄﾞ

自動印刷コマンド例:
  SPC10.exe /p "template.lw1,data.csv,1, /B -a temp_dir,/TW -off"

環境変数（.env で設定）:
  TEPRA_SPC10_PATH  : SPC10.exe のフルパス
  TEPRA_LW1_PATH    : .lw1 テンプレートファイルのフルパス
  TEPRA_TEMP_DIR    : SPC10 の一時出力フォルダ（省略可）
  TEPRA_COPIES      : 印刷枚数（デフォルト 1）

ログ:
  logs/tepra.log に印刷コマンドと結果を記録する。
"""
import csv
import logging
import os
import subprocess
from datetime import datetime
from logging.handlers import RotatingFileHandler


TEPRA_CSV_FIELDS = ["管理番号", "購入日", "QRｺｰﾄﾞ"]

# ─── ロガー設定 ──────────────────────────────────────────────────────────────
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_LOG_DIR = os.path.join(_BASE_DIR, "logs")
os.makedirs(_LOG_DIR, exist_ok=True)

_log_file = os.path.join(_LOG_DIR, "tepra.log")

logger = logging.getLogger("tepra")
if not logger.handlers:
    logger.setLevel(logging.DEBUG)

    # ファイルハンドラ（最大 5MB × 3 世代ローテーション）
    fh = RotatingFileHandler(
        _log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s\t%(levelname)s\t%(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(fh)

    # コンソールハンドラ（INFO 以上）
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                                      datefmt="%H:%M:%S"))
    logger.addHandler(ch)
# ─────────────────────────────────────────────────────────────────────────────


def generate_tepra_csv(management_id: str, labels_dir: str,
                       purchase_date: str | None = None) -> str:
    """
    テプラ差し込み用 CSV を生成して保存し、ファイル名を返す。
    CSV 文字コード: Shift_JIS（テプラソフト標準）
    purchase_date が省略された場合は今日の日付（YYYY/MM/DD）を使う。
    """
    if purchase_date is None:
        purchase_date = datetime.now().strftime("%Y/%m/%d")

    os.makedirs(labels_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"tepra_{management_id}_{timestamp}.csv"
    filepath = os.path.join(labels_dir, filename)

    with open(filepath, "w", newline="", encoding="shift_jis", errors="replace") as f:
        writer = csv.DictWriter(f, fieldnames=TEPRA_CSV_FIELDS)
        writer.writeheader()
        writer.writerow({
            "管理番号": management_id,
            "購入日": purchase_date,
            "QRｺｰﾄﾞ": management_id,
        })

    logger.info("CSV生成: %s  管理番号=%s  購入日=%s", filename, management_id, purchase_date)
    return filename


def print_tepra_label(csv_filepath: str, lw1_path: str, spc10_path: str,
                      temp_dir: str | None = None, copies: int = 1) -> tuple[bool, str]:
    """
    SPC10.exe を使ってテプララベルを印刷する。
    戻り値: (成功フラグ, エラーメッセージ)
    """
    if not spc10_path:
        msg = "TEPRA_SPC10_PATH が設定されていません。"
        logger.error("印刷スキップ: %s", msg)
        return False, msg
    if not os.path.isfile(spc10_path):
        msg = f"SPC10.exe が見つかりません: {spc10_path}"
        logger.error("印刷スキップ: %s", msg)
        return False, msg
    if not lw1_path:
        msg = "TEPRA_LW1_PATH が設定されていません。"
        logger.error("印刷スキップ: %s", msg)
        return False, msg
    if not os.path.isfile(lw1_path):
        msg = f"テンプレートファイルが見つかりません: {lw1_path}"
        logger.error("印刷スキップ: %s", msg)
        return False, msg

    if temp_dir:
        os.makedirs(temp_dir, exist_ok=True)
    else:
        temp_dir = os.path.dirname(csv_filepath)
    error_log_path = os.path.join(temp_dir, "E_log.txt")

    # コマンド: SPC10.exe /p "lw1,csv,copies, /B -a temp,/TW -off"
    print_arg = f"{lw1_path},{csv_filepath},{copies},/TW -off,/E -on {error_log_path},/CT"
    cmd = [spc10_path, "/pt", print_arg, "KING JIM SR3700P"]

    logger.info("印刷コマンド実行: %s /pt \"%s\" \"KING JIM SR3700P\"", spc10_path, print_arg)

    try:
        subprocess.Popen(
            cmd,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        logger.info("印刷コマンド送信完了: CSV=%s  テンプレート=%s  枚数=%d",
                    os.path.basename(csv_filepath), os.path.basename(lw1_path), copies)
        return True, ""
    except FileNotFoundError:
        msg = f"SPC10.exe の起動に失敗しました: {spc10_path}"
        logger.error("印刷エラー: %s", msg)
        return False, msg
    except Exception as exc:
        logger.error("印刷エラー: %s", exc, exc_info=True)
        return False, str(exc)


def generate_tepra_csv_bulk(management_ids: list[str], labels_dir: str,
                             purchase_date: str | None = None) -> str:
    """複数管理 ID の一括 CSV 生成。"""
    if purchase_date is None:
        purchase_date = datetime.now().strftime("%Y/%m/%d")

    os.makedirs(labels_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"tepra_bulk_{timestamp}.csv"
    filepath = os.path.join(labels_dir, filename)

    with open(filepath, "w", newline="", encoding="shift_jis", errors="replace") as f:
        writer = csv.DictWriter(f, fieldnames=TEPRA_CSV_FIELDS)
        writer.writeheader()
        for mid in management_ids:
            writer.writerow({
                "管理番号": mid,
                "購入日": purchase_date,
                "QRｺｰﾄﾞ": mid,
            })

    logger.info("一括CSV生成: %s  件数=%d  購入日=%s", filename, len(management_ids), purchase_date)
    return filename