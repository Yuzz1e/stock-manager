# 在庫管理システム

Flask + SQLite を使った機材貸出管理Webアプリです。

## 機能

- **使用登録**: NFC（学生証）＋バーコード（機材）をスキャンして貸出登録
- **保管・返却**: 機材バーコードをスキャン → 棚の場所を選択して返却登録
- **新規ラベル発行**: カテゴリ選択 → 連番自動発行 → テプラ用CSV＆ラベル画像生成
- **管理画面**: 貸出中一覧・機材一覧・カテゴリ/棚マスタ管理

## セットアップ

```bash
# 仮想環境作成・パッケージインストール
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 初期データ投入（カテゴリ8種・棚4行×5列）
python seed.py

# サーバー起動
python app.py
```

ブラウザで http://localhost:5000 を開く。

## テプラ SR3700P の使い方

1. テプラPROソフトウェアで `.lw1` テンプレートを作成する
   - フィールド名: `management_id` / `item_name` / `status` / `location`
2. Webアプリで新規ラベル発行すると `labels/tepra_*.csv` が生成される（Shift-JIS）
3. テプラソフトの「差し込み印刷」でCSVを読み込み、テンプレートと組み合わせて印刷

## ハードウェア接続

| 機器 | 接続方式 | 備考 |
|------|----------|------|
| NFCリーダー | HIDキーボードエミュレーション | フォーカスが当たっている入力欄に自動入力 |
| バーコードリーダー | HIDキーボードまたはカメラ | カメラスキャンはブラウザで動作 |
| テプラ SR3700P | USB（標準プリンター） | CSVをテプラソフトから印刷 |

## ファイル構成

```
stock-manager/
├── app.py              # Flask アプリ・全ルート
├── models.py           # SQLAlchemy モデル
├── label_generator.py  # QRコード・ラベル画像生成
├── tepra.py            # テプラ用 CSV 生成
├── seed.py             # 初期データ投入スクリプト
├── stock.db            # SQLite データベース（自動生成）
├── labels/             # 生成されたラベル画像・CSV
├── static/
│   ├── css/style.css
│   └── js/
│       ├── scanner.js   # カメラスキャン共通
│       ├── checkout.js
│       ├── return.js
│       └── new_label.js
└── templates/
    ├── base.html
    ├── index.html
    ├── checkout.html
    ├── return.html
    ├── new_label.html
    └── admin.html
```

## 棚マスタのカスタマイズ

デフォルトは A〜D 行 × 1〜5 列の 20 マスです。
管理画面（/admin）の「マスタ設定」タブから追加できます。
または `seed.py` の `rows`/`cols` を変更して `python seed.py` を再実行してください。

## 多言語対応 (i18n)

Flask-Babel により日本語（既定）と英語をサポートしています。
ユーザーはナビゲーションバー右側の「言語」ドロップダウンから切り替えでき、
選択はセッションに保存されます（`/i18n/ja`・`/i18n/en`）。

### 翻訳カタログの更新手順

テンプレートや Python コード内の翻訳対象文字列 (`_()`, `_l()`, `{{ _() }}`) を
追加・変更したら以下を実行してカタログを更新します。

```bash
# 1. 抽出: 全翻訳対象を messages.pot に抽出
pybabel extract -F babel.cfg -k _l -o messages.pot .

# 2. 更新: 既存カタログへ反映（新規 msgid 追加・未使用 msgid を obsolete 化）
pybabel update -i messages.pot -d translations

# 3. 翻訳: translations/en/LC_MESSAGES/messages.po を編集して msgstr を埋める
#    ja カタログは msgid が日本語のため空のままで OK（fallback で msgid が出る）

# 4. コンパイル: .mo を生成（Flask-Babel は .mo をロードする）
pybabel compile -d translations
```

新しい言語を追加する場合は次のように初期化します。

```bash
pybabel init -i messages.pot -d translations -l <locale>
```

加えて `app.py` の `SUPPORTED_LOCALES` と `templates/base.html` の言語
ドロップダウンにロケールを追記してください。

### JS 内の翻訳文字列

静的 JS ファイル（`static/js/*.js`）や `admin.html` のインライン JS は
テンプレートから `window.I18N` オブジェクト経由で翻訳文字列を受け取ります。
プレースホルダーは `{var}` 形式で、`_fmt(tmpl, { var: value })` で展開します。
JS 内に新しい翻訳対象が出たら、利用元のテンプレートの `<script>window.I18N = {...}`
ブロックに `{{ _('...') | tojson }}` のエントリを追加してください。
