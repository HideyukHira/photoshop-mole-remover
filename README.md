# ホクロ自動検出 & Photoshop 一括レタッチツール (`moles_remove`)

指定フォルダ内の人物・イラスト画像（PNG / JPG など）から、肌領域内の小さなホクロ（暗い点）を Python（MediaPipe + OpenCV）で自動検出し、Photoshop で元レイヤーを複製した別レイヤーに対して一括スポット修復（コンテンツに応じた塗りつぶし）を行い、PSD 形式で保存するツールです。

---

## ファイル構成

```text
moles_remove/
├─ run_mole_removal.bat   # 一括実行用バッチファイル（Python検出 → Photoshopレタッチ）
├─ detect_moles.py        # ホクロ検出・JSON出力・赤丸プレビュー生成（MediaPipe + OpenCV）
├─ remove_moles.jsx       # Photoshop用スクリプト（レイヤー複製・コンテンツに応じた塗りつぶし・PSD保存）
├─ requirements.txt       # Python依存パッケージ
├─ LICENSE                # MIT License
├─ models/                # MediaPipeモデル配置フォルダ（初回セットアップ時に配置）
│  ├─ selfie_multiclass_256x256.tflite
│  └─ face_landmarker.task
├─ input/                 # デフォルトの入力画像フォルダ（必要に応じて作成）
└─ output/
   ├─ moles_coords.json   # 検出したホクロ座標リスト
   ├─ preview/            # 検出箇所を赤丸で囲んだプレビュー画像
   └─ psd/                # レタッチ済みPSD（*_retouched.psd）と実行ログ（photoshop_log.txt）
```

---

## 動作環境

- Windows 10 / 11
- Python 3.10〜3.12（`requirements.txt` のパッケージ導入済み）
- Adobe Photoshop（2020〜2027 / Beta を自動検出）
- 対応画像形式: `.png`, `.jpg`, `.jpeg`, `.bmp`, `.webp`, `.tif`, `.tiff`

---

## セットアップ

### 1. Python 環境と依存パッケージのインストール

リポジトリ直下で仮想環境（`venv`）を作成し、依存ライブラリをインストールします。

```powershell
python -m venv venv
.\venv\Scripts\pip install -r requirements.txt
```

※ `run_mole_removal.bat` は環境変数 `PYTHON_EXE` → 同階層の `venv` / `.venv` → PATH 上の `python` の順で自動検出します。

### 2. MediaPipe モデルのダウンロード（AI肌抽出・顔パーツ除外用）

`models/` フォルダを作成し、以下の公式モデル 2 ファイルを配置してください。

| ファイル名 | 用途 | 公式ダウンロードリンク |
| --- | --- | --- |
| `selfie_multiclass_256x256.tflite` | 顔肌・体肌のAIセグメンテーション | [selfie_multiclass_256x256.tflite](https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_multiclass_256x256/float32/latest/selfie_multiclass_256x256.tflite) |
| `face_landmarker.task` | 目・眉・唇・鼻孔の自動除外 | [face_landmarker.task](https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task) |

PowerShell での一括ダウンロード例:

```powershell
mkdir models -Force
Invoke-WebRequest -Uri "https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_multiclass_256x256/float32/latest/selfie_multiclass_256x256.tflite" -OutFile "models\selfie_multiclass_256x256.tflite"
Invoke-WebRequest -Uri "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task" -OutFile "models\face_landmarker.task"
```

※ モデルを配置しない場合でも、色ベース（YCrCb + HSV）の肌色検出に自動フォールバックして動作します。

---

## 使い方

### 1. 基本実行（ドラッグ＆ドロップ）

画像が入ったフォルダを **`run_mole_removal.bat`** にドラッグ＆ドロップします。  
Python による検出完了後、自動的に Photoshop が起動してレタッチと PSD 保存を行います。

### 2. デフォルトフォルダで実行

同階層に `input` フォルダを作成して画像を入れ、`run_mole_removal.bat` をダブルクリックします。

### 3. 検出結果だけ先に確認したい場合（Photoshop を起動しない）

コマンドプロンプトまたは PowerShell で `--detect-only` を付けて実行します。

```bat
run_mole_removal.bat "C:\path\to\images" --detect-only
```

実行後、`output\preview` の赤丸プレビュー画像で検出精度を確認できます。

---

## 出力結果の確認

- **プレビュー画像**: `output\preview\<元ファイル名>_preview.png`  
  検出されたホクロが赤丸と番号でマークされます。
- **レタッチ済み PSD**: `output\psd\<元ファイル名>_retouched.psd`  
  元レイヤーはそのまま残り、複製された **`Moles_Removed`** レイヤーのみにスポット修復が適用されます（ビフォー／アフター比較やマスク調整が可能）。
- **実行ログ**: `output\psd\photoshop_log.txt`

---

## パラメータ調整の目安

### 検出感度の調整（`detect_moles.py`）

必要に応じてコマンドライン引数で調整できます。

| オプション | 既定値 | 説明 |
| --- | --- | --- |
| `--dog-thresh` | `10.5` | シャープな暗点（DoG）の閾値。下げると極小・薄いホクロも検出、上げると誤検出が減少 |
| `--contrast-thresh` | `14.0` | 周囲の肌との輝度差閾値。下げると薄いホクロも検出、上げると濃いホクロのみ検出 |
| `--min-radius` / `--max-radius` | `1.0` / `9.0` | 検出するホクロの半径範囲（px） |
| `--min-area` / `--max-area` | `1.5` / `260.0` | 検出するホクロの面積範囲（px²） |
| `--min-circularity` | `0.42` | 円形度の下限（0〜1）。上げるほど細長い影や線などを除外 |
| `--min-ring-skin-ratio` | `0.88` | 周囲リングのAI肌マスク比率。上げるほど境界付近の誤検出が減少 |
| `--max-ring-std` | `13.0` | 周囲リング輝度のばらつき上限。下げるほど滑らかな肌上のホクロのみに限定 |
| `--edge-erode` | `8` | 肌の輪郭線から除外する幅（px） |
| `--no-ai` | `false` | MediaPipe AI肌抽出を使わず、色ベースのみで実行する（イラスト専用時など） |

### Photoshop 側の修復範囲調整（`remove_moles.jsx` 上部）

- `SELECTION_RADIUS_MULT`（既定 `2.2`）: 検出半径に対する修復選択範囲の倍率
- `SELECTION_PADDING_PX`（既定 `4`）: 選択範囲の追加余白（px）
- `SELECTION_FEATHER_PX`（既定 `1.5`）: 選択範囲のぼかし（px）
- `SAVE_IF_NO_MOLES`（既定 `false`）: ホクロが 0 個の画像も PSD 保存する場合は `true` に変更

---

## トラブルシューティング

- **Photoshop が見つからないと表示される場合**  
  実行前に環境変数 `PS_EXE` に `Photoshop.exe` のフルパスを指定してください。
  ```bat
  set "PS_EXE=C:\Program Files\Adobe\Adobe Photoshop 2026\Photoshop.exe"
  run_mole_removal.bat "C:\path\to\images"
  ```
- **Photoshop から手動で `.jsx` だけ実行したい場合**  
  Photoshop のメニュー `ファイル > スクリプト > 参照...` から `remove_moles.jsx` を選択してください（直前の `moles_coords.json` を自動読み込みします）。

---

## ライセンス

[MIT License](LICENSE)
