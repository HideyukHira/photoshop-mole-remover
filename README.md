**English** | [日本語 (Japanese)](README.ja.md)

# Photoshop Mole Remover (`photoshop-mole-remover`)

An automated batch retouching pipeline that detects small moles and dark blemishes on skin regions using **Python (MediaPipe + OpenCV)** and removes them non-destructively in **Adobe Photoshop (ExtendScript)** via Content-Aware Fill, exporting layered PSD files.

---

## Key Features

- **AI Skin Segmentation & Facial Feature Exclusion**: Uses MediaPipe Multiclass Selfie Segmenter to isolate face/body skin and MediaPipe Face Landmarker (468 landmarks) to automatically exclude eyes, eyebrows, lips, and nostrils. Automatically falls back to YCrCb + HSV color-based skin masking for illustrations.
- **High-Precision Blemish Detection**: Applies multi-scale Difference of Gaussians (DoG) on the LAB lightness channel, combined with 8-direction radial profile checks and surrounding-ring smoothness validation to suppress false positives.
- **Non-Destructive Photoshop Batch Retouching**: Duplicates the original layer into a dedicated `Moles_Removed` layer, applies Content-Aware Fill only on detected coordinates, and saves the result as a `.psd` file for easy before/after comparison and manual fine-tuning.
- **Preview-Only Mode**: Verify detection accuracy with red-circle preview images (`--detect-only`) before launching Photoshop.

---

## Directory Structure

```text
photoshop-mole-remover/
├─ run_mole_removal.bat   # One-click / drag-and-drop runner (Python detection -> Photoshop retouch)
├─ detect_moles.py        # Mole detection, JSON export, and preview image generator (MediaPipe + OpenCV)
├─ remove_moles.jsx       # Photoshop ExtendScript (layer duplication, Content-Aware Fill, PSD export)
├─ requirements.txt       # Python dependencies
├─ LICENSE                # MIT License
├─ models/                # MediaPipe model directory (downloaded during setup)
│  ├─ selfie_multiclass_256x256.tflite
│  └─ face_landmarker.task
├─ input/                 # Default input image folder (create as needed)
└─ output/
   ├─ moles_coords.json   # Detected mole coordinates
   ├─ preview/            # Preview images with red-circle markers
   └─ psd/                # Retouched PSDs (*_retouched.psd) and execution log (photoshop_log.txt)
```

---

## Requirements

- Windows 10 / 11
- Python 3.10 – 3.12 (with packages from `requirements.txt`)
- Adobe Photoshop (automatically detects versions 2020–2027 and Beta)
- Supported image formats: `.png`, `.jpg`, `.jpeg`, `.bmp`, `.webp`, `.tif`, `.tiff`

---

## Setup

### 1. Install Python Dependencies

Create a virtual environment (`venv`) in the repository root and install the required packages:

```powershell
python -m venv venv
.\venv\Scripts\pip install -r requirements.txt
```

> `run_mole_removal.bat` automatically searches for Python in this order: `PYTHON_EXE` environment variable → local `venv` / `.venv` → system `python` on `PATH`.

### 2. Download MediaPipe Models (Recommended)

Create a `models/` directory and download the two official MediaPipe model files:

| File | Purpose | Official Download |
| --- | --- | --- |
| `selfie_multiclass_256x256.tflite` | Face & body skin segmentation | [selfie_multiclass_256x256.tflite](https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_multiclass_256x256/float32/latest/selfie_multiclass_256x256.tflite) |
| `face_landmarker.task` | Automatic exclusion of eyes, brows, lips, and nostrils | [face_landmarker.task](https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task) |

Quick download via PowerShell:

```powershell
mkdir models -Force
Invoke-WebRequest -Uri "https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_multiclass_256x256/float32/latest/selfie_multiclass_256x256.tflite" -OutFile "models\selfie_multiclass_256x256.tflite"
Invoke-WebRequest -Uri "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task" -OutFile "models\face_landmarker.task"
```

> If the model files are not present, the script automatically falls back to color-based (YCrCb + HSV) skin detection.

---

## Usage

### 1. Drag & Drop (Recommended)

Drag and drop any folder containing images onto **`run_mole_removal.bat`**.  
After Python finishes detection, Photoshop launches automatically to retouch the images and save layered PSD files.

### 2. Default Folder Mode

Create an `input/` folder in the repository directory, place your images inside, and double-click `run_mole_removal.bat`.

### 3. Detection Preview Only (Skip Photoshop)

Run with `--detect-only` from Command Prompt or PowerShell:

```bat
run_mole_removal.bat "C:\path\to\images" --detect-only
```

Inspect the red-circle preview images in `output\preview` to verify detection sensitivity before running Photoshop.

---

## Output Files

- **Preview images**: `output\preview\<filename>_preview.png` — Marks each detected mole with a numbered red circle.
- **Retouched PSDs**: `output\psd\<filename>_retouched.psd` — Keeps the original layer intact and applies Content-Aware Fill only on the duplicated **`Moles_Removed`** layer.
- **Execution log**: `output\psd\photoshop_log.txt`

---

## Tuning Parameters

### Detection Sensitivity (`detect_moles.py`)

Pass CLI flags as needed:

| Option | Default | Description |
| --- | --- | --- |
| `--dog-thresh` | `10.5` | DoG threshold for sharp dark spots. Lower detects fainter/smaller spots; higher reduces false positives. |
| `--contrast-thresh` | `14.0` | Luminance difference vs. surrounding skin. Lower catches lighter moles; higher limits to darker ones. |
| `--min-radius` / `--max-radius` | `1.0` / `9.0` | Target mole radius range (px). |
| `--min-area` / `--max-area` | `1.5` / `260.0` | Target mole area range (px²). |
| `--min-circularity` | `0.42` | Minimum circularity (0–1). Higher values reject elongated shadows and lines. |
| `--min-ring-skin-ratio` | `0.88` | Minimum AI skin ratio in the surrounding ring. Higher reduces edge false positives. |
| `--max-ring-std` | `13.0` | Maximum luminance std-dev in the surrounding ring. Lower restricts to smooth skin areas. |
| `--edge-erode` | `8` | Margin (px) eroded from skin boundaries. |
| `--no-ai` | `false` | Disable MediaPipe AI segmentation and use color-based detection only (useful for illustrations). |

### Photoshop Selection Settings (`remove_moles.jsx`)

Edit the constants at the top of `remove_moles.jsx`:

- `SELECTION_RADIUS_MULT` (default `2.2`): Multiplier applied to detected mole radius
- `SELECTION_PADDING_PX` (default `4`): Extra selection padding (px)
- `SELECTION_FEATHER_PX` (default `1.5`): Selection feather radius (px)
- `SAVE_IF_NO_MOLES` (default `false`): Set to `true` to still save a PSD even when 0 moles are detected

---

## Troubleshooting

- **Photoshop executable not found**  
  Set the `PS_EXE` environment variable to your `Photoshop.exe` path before running:
  ```bat
  set "PS_EXE=C:\Program Files\Adobe\Adobe Photoshop 2026\Photoshop.exe"
  run_mole_removal.bat "C:\path\to\images"
  ```
- **Running `.jsx` manually inside Photoshop**  
  Go to `File > Scripts > Browse...` and select `remove_moles.jsx` (it automatically loads the latest `moles_coords.json`).

---

## License

[MIT License](LICENSE)
