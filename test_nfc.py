import time
import re
from smartcard.System import readers

def read_student_card():
    r = readers()
    if len(r) == 0:
        return False

    conn = r[0].createConnection()

    try:
        conn.connect()
        
        # --- 1. デフォルト領域でカード検知 ---
        res, sw1, sw2 = conn.transmit([0xFF, 0xCA, 0x00, 0x00, 0x00])
        if sw1 != 0x90: return False
            
        print("\n✅ カードを読み取りました")

        # --- 2. 学籍番号の読み取り (System: デフォルト, Service: 0x200B, Block: 1) ---
        # THRU通信 (FF FE 00) を使って生データを取得
        cmd_b1 = [0x06, 0x01, 0x0B, 0x20, 0x01, 0x80, 0x01]
        apdu_b1 = [0xFF, 0xFE, 0x00, 0x00, len(cmd_b1)] + cmd_b1 + [0x00]
        res_b1, s1, s2 = conn.transmit(apdu_b1)

        student_num = "読取失敗"
        if s1 == 0x90 and len(res_b1) >= 4 and res_b1[0] == 0x07 and res_b1[1] == 0x00:
            data_b1 = bytes(res_b1[4:20])
            text_b1 = data_b1.decode('shift_jis', errors='ignore')
            
            # 数字だけを抽出して合体 (例: 2600 + 2101466)
            digits = re.sub(r'\D', '', text_b1)
            if len(digits) >= 14:
                student_num = digits[10:14] + digits[2:9]
            else:
                student_num = f"解析不能 ({digits})"

        # --- 3. 氏名の読み取り (System: 0xFE00, Service: 0x1A8B, Block: 1) ---
        student_name = "読取失敗"
        
        # Step 3-1: DIRECT通信 (FF FE 01) で System Code 0xFE00 をポーリング
        poll_cmd = [0x06, 0x00, 0xFE, 0x00, 0x00, 0x00]
        apdu_poll = [0xFF, 0xFE, 0x01, 0x00, len(poll_cmd)] + poll_cmd
        res_poll, s1, s2 = conn.transmit(apdu_poll)
        
        # ポーリング成功時、専用のIDm（8バイト）を取得
        if s1 == 0x90 and len(res_poll) >= 18 and res_poll[1] == 0x01:
            idm_fe00 = list(res_poll[2:10])
            
            # Step 3-2: 取得したIDmを使って Service: 0x1A8B, Block: 1 を読み取り
            # 0x1A8B はリトルエンディアンで [0x8B, 0x1A] になります
            read_payload = [0x10, 0x06] + idm_fe00 + [0x01, 0x8B, 0x1A, 0x01, 0x80, 0x01]
            apdu_read = [0xFF, 0xFE, 0x01, 0x00, len(read_payload)] + read_payload
            
            res_name, s1_name, s2_name = conn.transmit(apdu_read)
            
            # 読み取り成功時、データ部分（13バイト目から16バイト）を抽出
            if s1_name == 0x90 and len(res_name) >= 29 and res_name[1] == 0x07 and res_name[10] == 0x00:
                name_data = bytes(res_name[13:29])
                # Shift-JISでデコード (半角カタカナも自動で変換されます)
                student_name = name_data.decode('shift_jis', errors='ignore').replace('\x00', '').strip()
            else:
                student_name = "名前データなし (Service 0x1A8B エラー)"
        else:
            student_name = "0xFE00領域にアクセスできません"

        # --- 4. 結果の表示 ---
        print(f"🎓 学籍番号: {student_num}")
        print(f"👤 氏名    : {student_name}")
        print("-" * 30)
        
        return True

    except Exception as e:
        # カードがない場合などは無視
        return False
    finally:
        try: conn.disconnect()
        except: pass

if __name__ == '__main__':
    print("========================================")
    print(" 学生証スキャナー (学籍番号＋半角カナ氏名)")
    print(" 学生証をかざしてください (Ctrl+Cで終了)")
    print("========================================")
    
    while True:
        if read_student_card():
            time.sleep(3)
        time.sleep(0.5)