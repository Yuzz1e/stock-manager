"""
NFC (RC-S300 / pyscard) + シリアルバーコードリーダー バックグラウンドスレッド + SSE ブロードキャスト。

依存ライブラリ:
  pip install pyscard pyserial

環境変数（.env で設定可能）:
  SCANNER_SERIAL_PORT     : シリアルポート (デフォルト: COM5)
  SCANNER_SERIAL_BAUDRATE : ボーレート    (デフォルト: 9600)
  SCANNER_NFC_ENABLED     : NFC 有効化   (デフォルト: true)

■ RC-S300 学生証読み取り APDU フォーマット (FF FE コマンド)
  RC-S300 (NFC Port Software 4.x / PaSoRi 4.0) は FF C2 透過交換をサポートしない。
  代わりに以下の携帯型コマンドを使用する。

  学籍番号 (Service 0x200B, Block 1, デフォルト領域):
    送信: FF FE 00 00 07  06 01 0B 20 01 80 01  00
    レス: [07][00][...][data 4..19]

  氏名 (Service 0x1A8B, Block 1, System 0xFE00):
    ポーリング: FF FE 01 00 06  06 00 FE 00 00 00
    送信: FF FE 01 00 1a  10 06 [IDm*8] 01 8B 1A 01 80 01
    レス: [?][07][...][data 13..28]
"""
import json
import logging
import queue
import re
import struct
import threading
import time

logger = logging.getLogger("scanner")


# ─── 半角カナ → 全角カナ変換 ──────────────────────────────────────────────

# 濁点・半濁点が付く文字の変換表（先に処理する）
_DAKUTEN_MAP: dict[str, str] = {
    "ｶﾞ": "ガ", "ｷﾞ": "ギ", "ｸﾞ": "グ", "ｹﾞ": "ゲ", "ｺﾞ": "ゴ",
    "ｻﾞ": "ザ", "ｼﾞ": "ジ", "ｽﾞ": "ズ", "ｾﾞ": "ゼ", "ｿﾞ": "ゾ",
    "ﾀﾞ": "ダ", "ﾁﾞ": "ヂ", "ﾂﾞ": "ヅ", "ﾃﾞ": "デ", "ﾄﾞ": "ド",
    "ﾊﾞ": "バ", "ﾋﾞ": "ビ", "ﾌﾞ": "ブ", "ﾍﾞ": "ベ", "ﾎﾞ": "ボ",
    "ｳﾞ": "ヴ",
    "ﾊﾟ": "パ", "ﾋﾟ": "ピ", "ﾌﾟ": "プ", "ﾍﾟ": "ペ", "ﾎﾟ": "ポ",
}

# 単体の半角カナ → 全角カナ
_HANKAKU_MAP: dict[str, str] = {
    "ｦ": "ヲ", "ｧ": "ァ", "ｨ": "ィ", "ｩ": "ゥ", "ｪ": "ェ", "ｫ": "ォ",
    "ｬ": "ャ", "ｭ": "ュ", "ｮ": "ョ", "ｯ": "ッ", "ｰ": "ー",
    "ｱ": "ア", "ｲ": "イ", "ｳ": "ウ", "ｴ": "エ", "ｵ": "オ",
    "ｶ": "カ", "ｷ": "キ", "ｸ": "ク", "ｹ": "ケ", "ｺ": "コ",
    "ｻ": "サ", "ｼ": "シ", "ｽ": "ス", "ｾ": "セ", "ｿ": "ソ",
    "ﾀ": "タ", "ﾁ": "チ", "ﾂ": "ツ", "ﾃ": "テ", "ﾄ": "ト",
    "ﾅ": "ナ", "ﾆ": "ニ", "ﾇ": "ヌ", "ﾈ": "ネ", "ﾉ": "ノ",
    "ﾊ": "ハ", "ﾋ": "ヒ", "ﾌ": "フ", "ﾍ": "ヘ", "ﾎ": "ホ",
    "ﾏ": "マ", "ﾐ": "ミ", "ﾑ": "ム", "ﾒ": "メ", "ﾓ": "モ",
    "ﾔ": "ヤ", "ﾕ": "ユ", "ﾖ": "ヨ",
    "ﾗ": "ラ", "ﾘ": "リ", "ﾙ": "ル", "ﾚ": "レ", "ﾛ": "ロ",
    "ﾜ": "ワ", "ﾝ": "ン",
    "ﾞ": "゛", "ﾟ": "゜",
    "｡": "。", "｢": "「", "｣": "」", "､": "、", "･": "・",
}

# ビルド済み変換テーブル（str.translate 用）
_HANKAKU_TABLE = str.maketrans(_HANKAKU_MAP)


def hankaku_to_zenkaku(text: str) -> str:
    """半角カナを全角カナに変換する。濁点・半濁点の結合も正しく処理する。"""
    # 先に2文字組（濁点付き）を置換してから1文字ずつ変換する
    for hk, zk in _DAKUTEN_MAP.items():
        text = text.replace(hk, zk)
    return text.translate(_HANKAKU_TABLE)


# ─── SSE ブロードキャスター ────────────────────────────────────────────────

class ScannerBroadcaster:
    """接続中の全 SSE クライアントにスキャンイベントを配信する。"""

    def __init__(self):
        self._queues: set = set()
        self._lock = threading.Lock()
        self.nfc_connected    = False
        self.serial_connected = False

    def subscribe(self) -> queue.Queue:
        q = queue.Queue(maxsize=100)
        with self._lock:
            self._queues.add(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            self._queues.discard(q)

    def broadcast(self, event_type: str, data: dict) -> None:
        msg = f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        with self._lock:
            for q in list(self._queues):
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    pass

    def status(self) -> dict:
        return {
            "nfc_connected":    self.nfc_connected,
            "serial_connected": self.serial_connected,
        }


broadcaster = ScannerBroadcaster()


# ─── FeliCa ヘルパー関数 ──────────────────────────────────────────────────

def _felica_svc_bytes(number: int, attribute: int) -> list:
    """
    nfcpy の ServiceCode(number, attribute) を
    FeliCa コマンド用の 2バイトリスト (little-endian) に変換する。

    nfcpy 内部エンコード: value = (number << 4) | (attribute & 0xF)
    例: ServiceCode(106, 0x0b) → 0x06AB → [0xAB, 0x06]
    """
    v = (number << 4) | (attribute & 0xF)
    lo, hi = struct.pack("<H", v)
    return [lo, hi]


def _parse_felica_read_response(data: list, block_num: int):
    """
    FeliCa Read Without Encryption レスポンスを解析しデータ 16 バイトを返す。
    NFC Port Software ラッパー (95 00 len) および生パケットの両方に対応。
    """
    if not data:
        return None
    if data[0] == 0x95:
        if len(data) < 4 or data[1] != 0x00:
            logger.warning("[NFC] block%d NFC Port Software ステータスエラー: 0x%02X",
                           block_num, data[1] if len(data) > 1 else 0xFF)
            return None
        felica_resp = data[3:]
    elif data[0] == 0xC0:
        logger.warning("[NFC] block%d NFC Port Software エラー (C0): %s",
                       block_num, bytes(data).hex())
        return None
    else:
        felica_resp = data
    if len(felica_resp) < 29:
        logger.warning("[NFC] block%d FeliCa レスポンス短すぎ (%d bytes): %s",
                       block_num, len(felica_resp), bytes(felica_resp).hex())
        return None
    if felica_resp[1] != 0x07:
        logger.warning("[NFC] block%d FeliCa 応答コード不正: 0x%02X", block_num, felica_resp[1])
        return None
    stat1, stat2 = felica_resp[10], felica_resp[11]
    if stat1 != 0x00:
        logger.warning("[NFC] block%d STATUS1=0x%02X STATUS2=0x%02X", block_num, stat1, stat2)
        return None
    return bytes(felica_resp[13:29])


def _felica_read_block(conn, idm: list, sc_bytes: list, block_num: int):
    """
    RC-S300 で FeliCa Read Without Encryption を実行。
    3 種類の APDU 形式 (A:ラッパーなし / B:ラッパーあり / C:FF B0) を順に試みる。
    """
    cmd = [0x06] + idm + [0x01] + sc_bytes + [0x01, 0x80, block_num]
    pkt = [len(cmd) + 1] + cmd

    # -- 方法 A: FF C2 ラッパーなし (PaSoRi 4.x / RC-S300) --
    apdu_a = [0xFF, 0xC2, 0x00, 0x00, len(pkt)] + pkt + [0x00]
    data, sw1, sw2 = conn.transmit(apdu_a)
    logger.info("[NFC] block%d [A] FF C2 no-wrap  SW=%02X%02X  resp=%s",
                block_num, sw1, sw2, bytes(data).hex() if data else "(空)")
    if sw1 == 0x90 and data and data[0] not in (0xC0,):
        result = _parse_felica_read_response(list(data), block_num)
        if result:
            return result

    # -- 方法 B: FF C2 NFC Port Software ラッパーあり (PaSoRi 5.x / RC-S380) --
    wrapper = [0x95, 0x01, len(pkt)] + pkt
    apdu_b  = [0xFF, 0xC2, 0x00, 0x00, len(wrapper)] + wrapper + [0x00]
    data, sw1, sw2 = conn.transmit(apdu_b)
    logger.info("[NFC] block%d [B] FF C2 wrapped  SW=%02X%02X  resp=%s",
                block_num, sw1, sw2, bytes(data).hex() if data else "(空)")
    if sw1 == 0x90 and data and data[0] not in (0xC0,):
        result = _parse_felica_read_response(list(data), block_num)
        if result:
            return result

    # -- 方法 C: FF B0 Read Binary (ブロック番号を P2 に指定) --
    apdu_c = [0xFF, 0xB0, 0x00, block_num, 0x10]
    data, sw1, sw2 = conn.transmit(apdu_c)
    logger.info("[NFC] block%d [C] FF B0 ReadBin  SW=%02X%02X  resp=%s",
                block_num, sw1, sw2, bytes(data).hex() if data else "(空)")
    if sw1 == 0x90 and data and len(data) == 16:
        logger.info("[NFC] block%d [C] FF B0 成功: %s", block_num, bytes(data).hex())
        return bytes(data)

    logger.warning("[NFC] block%d 全アプローチ失敗", block_num)
    return None

def _felica_poll(conn, system_code: int = 0xFE00):
    """
    FeliCa Polling コマンドを透過交換 (FF C2) で送信し、指定システムの IDm を返す。
    失敗時は None を返す。

    FeliCa Polling (0x04) パケット:
      [LEN=6][04][sys_hi][sys_lo][req_code=0x01][time_slot=0x00]
    レスポンス (NFC Port Software ラップあり):
      [95][00][len][len][05][IDm*8][PMm*8][SysCode*2]
    """
    sys_hi = (system_code >> 8) & 0xFF
    sys_lo = system_code & 0xFF

    # Polling パケット (req_code=0x01 で System Code も返す)
    pkt     = [0x06, 0x04, sys_hi, sys_lo, 0x01, 0x00]
    wrapper = [0x95, 0x01, len(pkt)] + pkt
    apdu    = [0xFF, 0xC2, 0x00, 0x00, len(wrapper)] + wrapper + [0x00]

    data, sw1, sw2 = conn.transmit(apdu)
    logger.info("[NFC] Polling 0x%04X  APDU=%s  SW=%02X%02X  resp=%s",
                system_code, bytes(apdu).hex(), sw1, sw2,
                bytes(data).hex() if data else "(空)")

    if sw1 != 0x90:
        logger.warning("[NFC] Polling SW エラー: %02X%02X", sw1, sw2)
        return None

    # NFC Port Software ラップーの有無を判定
    if len(data) >= 3 and data[0] == 0x95:
        if data[1] != 0x00:
            logger.warning("[NFC] Polling ステータスエラー: 0x%02X", data[1])
            return None
        felica_resp = data[3:]   # [95][00][len] を除去
    else:
        felica_resp = data       # 生レスポンス

    # felica_resp: [len][05][IDm*8][PMm*8][sys*2] → 最小 10 バイト必要
    if len(felica_resp) < 10 or felica_resp[1] != 0x05:
        logger.warning("[NFC] Polling レスポンス不正: %s",
                       bytes(felica_resp).hex() if felica_resp else "(空)")
        return None

    idm = list(felica_resp[2:10])
    logger.info("[NFC] Polling 成功  IDm: %s", bytes(idm).hex())
    return idm


# ─── NFC リーダースレッド (pyscard / RC-S300) ──────────────────────────────

def _nfc_reader_loop() -> None:
    """
    RC-S300 (PaSoRi 4.0) 用 NFC ループ。
    FF FE コマンドで学籍番号（デフォルト領域・ Service 0x200B）と
    氏名（System 0xFE00 ・ Service 0x1A8B）を読み取る。
    """
    try:
        from smartcard.System import readers as scard_readers
        from smartcard.Exceptions import (
            CardConnectionException,
            NoCardException,
            NoReadersException,
        )
    except ImportError:
        logger.warning("pyscard がインストールされていません (pip install pyscard)")
        return

    while True:
        # ── リーダー一覧の取得 ────────────────────────────
        try:
            r_list = scard_readers()
        except NoReadersException:
            r_list = []
        except Exception as exc:
            logger.error("readers() エラー: %s", exc)
            r_list = []

        if not r_list:
            if broadcaster.nfc_connected:
                broadcaster.nfc_connected = False
                broadcaster.broadcast("reader_status", broadcaster.status())
                logger.warning("NFC リーダーが見つかりません。3秒後に再試行します。")
            time.sleep(3)
            continue

        if not broadcaster.nfc_connected:
            broadcaster.nfc_connected = True
            broadcaster.broadcast("reader_status", broadcaster.status())
            logger.info("NFC リーダー検出: %s", r_list[0])

        # ── カード読み取り試行 ──────────────────────────
        conn = None
        try:
            conn = r_list[0].createConnection()
            conn.connect()
            logger.info("[NFC] カード検出")

            # 1. GetUID でカード存在を確認
            res, sw1, sw2 = conn.transmit([0xFF, 0xCA, 0x00, 0x00, 0x00])
            logger.info("[NFC] GetUID  SW=%02X%02X  data=%s",
                        sw1, sw2, bytes(res).hex() if res else "(空)")
            if sw1 != 0x90:
                conn.disconnect(); conn = None
                time.sleep(0.3)
                continue

            # ── 学籍番号読み取り (デフォルト領域 / Service 0x200B / Block 1) ────
            student_id = ""
            cmd_num = [0x06, 0x01, 0x0B, 0x20, 0x01, 0x80, 0x01]
            apdu_num = [0xFF, 0xFE, 0x00, 0x00, len(cmd_num)] + cmd_num + [0x00]
            res_num, s1, s2 = conn.transmit(apdu_num)
            logger.info("[NFC] 学籍番号  FF FE 00  SW=%02X%02X  resp=%s",
                        s1, s2, bytes(res_num).hex() if res_num else "(空)")

            if s1 == 0x90 and len(res_num) >= 4 and res_num[0] == 0x07 and res_num[1] == 0x00:
                data_num_raw = bytes(res_num[4:20])
                text_num = data_num_raw.decode("shift_jis", errors="ignore")
                logger.info("[NFC] 学籍番号 raw text: %r", text_num)
                digits = re.sub(r"\D", "", text_num)
                logger.info("[NFC] 学籍番号 digits: %s", digits)
                if len(digits) >= 14:
                    student_id = digits[10:14] + digits[2:9]
                    logger.info("[NFC] 学籍番号: %r", student_id)
                else:
                    logger.warning("[NFC] 学籍番号 digits 不足 (%d桁): %s", len(digits), digits)
            else:
                logger.warning("[NFC] 学籍番号読み取り失敗 SW=%02X%02X", s1, s2)

            # ── 氏名読み取り (System 0xFE00 / Service 0x1A8B / Block 1) ────────
            student_name = ""
            poll_cmd  = [0x06, 0x00, 0xFE, 0x00, 0x00, 0x00]
            apdu_poll = [0xFF, 0xFE, 0x01, 0x00, len(poll_cmd)] + poll_cmd
            res_poll, s1, s2 = conn.transmit(apdu_poll)
            logger.info("[NFC] 0xFE00 Polling  FF FE 01  SW=%02X%02X  resp=%s",
                        s1, s2, bytes(res_poll).hex() if res_poll else "(空)")

            if s1 == 0x90 and len(res_poll) >= 18 and res_poll[1] == 0x01:
                idm_fe00 = list(res_poll[2:10])
                logger.info("[NFC] 0xFE00 IDm: %s", bytes(idm_fe00).hex())

                read_payload = [0x10, 0x06] + idm_fe00 + [0x01, 0x8B, 0x1A, 0x01, 0x80, 0x01]
                apdu_name   = [0xFF, 0xFE, 0x01, 0x00, len(read_payload)] + read_payload
                res_name, s1_n, s2_n = conn.transmit(apdu_name)
                logger.info("[NFC] 氏名 read  FF FE 01  SW=%02X%02X  resp=%s",
                            s1_n, s2_n, bytes(res_name).hex() if res_name else "(空)")

                if (s1_n == 0x90 and len(res_name) >= 29
                        and res_name[1] == 0x07 and res_name[10] == 0x00):
                    name_data    = bytes(res_name[13:29])
                    student_name = name_data.decode("shift_jis", errors="ignore") \
                                            .replace("\x00", "").strip()
                    student_name = hankaku_to_zenkaku(student_name)
                    logger.info("[NFC] 氏名: %r", student_name)
                else:
                    logger.warning("[NFC] 氏名読み取り失敗 SW=%02X%02X  len=%d",
                                   s1_n, s2_n, len(res_name) if res_name else 0)
            else:
                logger.warning("[NFC] 0xFE00 Polling 失敗 SW=%02X%02X  len=%d",
                               s1, s2, len(res_poll) if res_poll else 0)

            # ── 配信 ────────────────────────────────────────────
            if student_id or student_name:
                logger.info("[NFC] 読み取り成功: id=%r  name=%r", student_id, student_name)
                broadcaster.broadcast("student_scan", {
                    "student_id":   student_id,
                    "student_name": student_name,
                })
                # カードが抜かれるまで待機（同一カードの連続読み取り防止）
                conn.disconnect(); conn = None
                logger.info("[NFC] カード抜去待ち...")
                while True:
                    time.sleep(0.4)
                    try:
                        tmp = r_list[0].createConnection()
                        tmp.connect()
                        tmp.disconnect()
                    except (CardConnectionException, NoCardException):
                        logger.info("[NFC] カード抜去検出 — 次のカードを待機します")
                        break
            else:
                logger.warning("[NFC] 学籍番号・氏名いずれも取得できませんでした")

        except (CardConnectionException, NoCardException):
            pass  # カードなし（ポーリング中）
        except Exception as exc:
            logger.error("[NFC] 読み取りエラー: %s", exc, exc_info=True)
            broadcaster.nfc_connected = False
            broadcaster.broadcast("reader_status", broadcaster.status())
            time.sleep(3)
        finally:
            if conn:
                try:
                    conn.disconnect()
                except Exception:
                    pass

        time.sleep(0.2)


def start_nfc_thread() -> threading.Thread:
    t = threading.Thread(target=_nfc_reader_loop, name="nfc-reader", daemon=True)
    t.start()
    logger.info("NFC リーダースレッドを起動しました。")
    return t


# ─── シリアルバーコードリーダースレッド ────────────────────────────────────

def _list_serial_ports() -> list:
    try:
        import serial.tools.list_ports  # type: ignore
        return [p.device for p in serial.tools.list_ports.comports()]
    except Exception:
        return []


def _serial_reader_loop(port: str, baudrate: int) -> None:
    try:
        import serial  # type: ignore
    except ImportError:
        logger.warning("pyserial がインストールされていません (pip install pyserial)")
        return

    _perm_logged = False  # PermissionError の詳細メッセージを初回のみ表示

    while True:
        try:
            with serial.Serial(port, baudrate, timeout=1) as ser:
                _perm_logged = False
                logger.info("シリアルポート %s (%d bps) に接続しました。", port, baudrate)
                broadcaster.serial_connected = True
                broadcaster.broadcast("reader_status", broadcaster.status())

                buf = b""
                while True:
                    chunk = ser.read(ser.in_waiting or 1)
                    if not chunk:
                        continue
                    buf += chunk
                    while b"\r" in buf or b"\n" in buf:
                        cr  = buf.find(b"\r") if b"\r" in buf else len(buf)
                        lf  = buf.find(b"\n") if b"\n" in buf else len(buf)
                        idx  = min(cr, lf)
                        line = buf[:idx].decode("ascii", errors="ignore").strip()
                        buf  = buf[idx + 1:].lstrip(b"\r\n")
                        if line:
                            logger.info("バーコード読み取り: %s", line)
                            broadcaster.broadcast("barcode_scan", {
                                "management_id": line,
                            })

        except serial.SerialException as exc:
            broadcaster.serial_connected = False
            broadcaster.broadcast("reader_status", broadcaster.status())

            is_perm = (
                isinstance(exc.__cause__, PermissionError)
                or "PermissionError" in str(exc)
                or "Access" in str(exc)
            )

            if is_perm:
                if not _perm_logged:
                    available = _list_serial_ports()
                    logger.error(
                        "\n"
                        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        "  シリアルポート %s へのアクセスが拒否されました。\n"
                        "\n"
                        "  よくある原因:\n"
                        "   1) 別アプリが開いている (Tera Term / Arduino IDE 等)\n"
                        "   2) ブラウザの Web Serial API が接続中 (タブを閉じてください)\n"
                        "   3) Flask を二重起動している\n"
                        "\n"
                        "  現在利用可能なポート: %s\n"
                        "  別ポートを使う場合は .env の SCANNER_SERIAL_PORT を変更\n"
                        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                        port,
                        ", ".join(available) if available else "(なし)",
                    )
                    _perm_logged = True
                else:
                    logger.warning("%s: アクセス拒否 — 5秒後に再試行します", port)
                time.sleep(5)
            else:
                logger.error("シリアル接続エラー (%s): %s", port, exc)
                time.sleep(3)

        except Exception as exc:
            broadcaster.serial_connected = False
            broadcaster.broadcast("reader_status", broadcaster.status())
            logger.error("シリアル接続エラー (%s): %s", port, exc)
            time.sleep(3)


def start_serial_thread(port: str = "COM5", baudrate: int = 9600) -> threading.Thread:
    t = threading.Thread(
        target=_serial_reader_loop,
        args=(port, baudrate),
        name="serial-reader",
        daemon=True,
    )
    t.start()
    logger.info("シリアルリーダースレッド起動: port=%s  baudrate=%d", port, baudrate)
    return t


# ─── 一括起動 ─────────────────────────────────────────────────────────────

def start_all(port: str = "COM5", baudrate: int = 9600,
              nfc_enabled: bool = True) -> None:
    """NFC + シリアル バックグラウンドスレッドを全て起動する。"""
    if nfc_enabled:
        start_nfc_thread()
    start_serial_thread(port, baudrate)
