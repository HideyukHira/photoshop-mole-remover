#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
detect_moles.py
指定フォルダ内の人物・イラスト画像（PNG/JPG等）から、
肌領域内の極小の暗い点（ホクロ）を自動検出し、
座標リストをJSON出力 + 検出箇所を赤丸で囲んだプレビュー画像を出力するスクリプト。

検出アルゴリズム:
1. MediaPipe Multiclass Selfie Segmenter による高精度な肌領域（顔肌・体肌）抽出
   + MediaPipe Face Landmarker による目・眉・唇・鼻孔の自動除外
   （イラスト等でAI肌領域が検出されない場合は YCrCb+HSV 肌色マスクへ自動フォールバック）
2. LAB輝度チャンネルのマルチスケール DoG (Difference of Gaussians) によるシャープな暗点抽出
3. 8方向放射プロファイル（全方向が周囲の滑らかな肌へ立ち上がるか）と
   周囲リングの滑らかさ・肌純度チェックによる誤検出除外
"""

import os

# MediaPipe / TensorFlow の冗長なログ出力を抑制
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")
os.environ.setdefault("GLOG_minloglevel", "3")

import argparse
import datetime
import json
import math
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np


SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}

# MediaPipe FaceLandmarker 468点インデックス（目・眉・唇・鼻孔）
FACE_EXCLUSION_GROUPS = (
    # 左目
    [33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246],
    # 右目
    [362, 382, 381, 380, 374, 373, 390, 249, 263, 466, 388, 387, 386, 385, 384, 398],
    # 左眉
    [70, 63, 105, 66, 107, 55, 65, 52, 53, 46],
    # 右眉
    [300, 293, 334, 296, 336, 285, 295, 282, 283, 276],
    # 唇
    [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 409, 270, 269, 267, 0, 37, 39, 40, 185],
    # 鼻孔・鼻先下部
    [98, 97, 2, 326, 327, 294, 278, 344, 440, 275, 4, 45, 220, 115, 48, 64],
)


def imread_unicode(filepath: Path) -> np.ndarray:
    """日本語パスを含む画像ファイルを安全に読み込む（BGR形式）。"""
    data = np.fromfile(str(filepath), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"画像を読み込めませんでした: {filepath}")
    return img


def imwrite_unicode(filepath: Path, img: np.ndarray) -> None:
    """日本語パスを含む出力先へ安全に画像を書き出す。"""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    ext = filepath.suffix.lower() or ".png"
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        raise ValueError(f"画像のエンコードに失敗しました: {filepath}")
    buf.tofile(str(filepath))


class MediaPipeSkinAnalyzer:
    """MediaPipe のマルチクラス肌セグメンテーションと顔パーツ除外を管理するクラス。"""

    def __init__(self, models_dir: Path, enabled: bool = True) -> None:
        self.segmenter = None
        self.face_landmarker = None
        self.mp = None

        if not enabled:
            return

        seg_model = models_dir / "selfie_multiclass_256x256.tflite"
        fl_model = models_dir / "face_landmarker.task"

        try:
            import mediapipe as mp
            from mediapipe.tasks import python as mp_python
            from mediapipe.tasks.python import vision

            self.mp = mp

            if seg_model.exists():
                seg_opts = vision.ImageSegmenterOptions(
                    base_options=mp_python.BaseOptions(model_asset_path=str(seg_model)),
                    output_category_mask=False,
                    output_confidence_masks=True,
                )
                self.segmenter = vision.ImageSegmenter.create_from_options(seg_opts)
            else:
                print(f"[WARN] AI肌セグメンテーションモデルが見つかりません: {seg_model}")

            if fl_model.exists():
                fl_opts = vision.FaceLandmarkerOptions(
                    base_options=mp_python.BaseOptions(model_asset_path=str(fl_model)),
                    num_faces=4,
                )
                self.face_landmarker = vision.FaceLandmarker.create_from_options(fl_opts)
        except Exception as exc:
            print(f"[WARN] MediaPipe 初期化に失敗したため色ベース検出へフォールバックします: {exc}")
            self.segmenter = None
            self.face_landmarker = None

    def get_skin_and_exclusion(self, img_bgr: np.ndarray) -> Tuple[Optional[np.ndarray], np.ndarray]:
        """
        Returns:
            ai_skin_mask: AIによる肌マスク (0 or 255)。利用不可/未検出時は None
            face_excl_mask: 目・眉・唇・鼻孔の除外マスク (0 or 255)
        """
        h, w = img_bgr.shape[:2]
        face_excl = np.zeros((h, w), dtype=np.uint8)
        ai_skin_mask: Optional[np.ndarray] = None

        if self.mp is None or (self.segmenter is None and self.face_landmarker is None):
            return None, face_excl

        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        mp_img = self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=img_rgb)

        if self.segmenter is not None:
            res_seg = self.segmenter.segment(mp_img)
            confs = [m.numpy_view() for m in res_seg.confidence_masks]
            if len(confs) >= 6:
                # 0:bg, 1:hair, 2:body-skin, 3:face-skin, 4:clothes, 5:others(accessories)
                skin_prob = confs[2] + confs[3]
                raw_ai = (
                    (skin_prob >= 0.55)
                    & (confs[1] < 0.25)
                    & (confs[4] < 0.25)
                    & (confs[5] < 0.25)
                ).astype(np.uint8) * 255

                if raw_ai.shape[:2] != (h, w):
                    raw_ai = cv2.resize(raw_ai, (w, h), interpolation=cv2.INTER_NEAREST)

                # AI肌領域が画面の1.5%以上あれば採用（2Dイラスト等で不発なら色ベースへフォールバック）
                if (cv2.countNonZero(raw_ai) / float(h * w)) >= 0.015:
                    # 細かな穴埋めとノイズ除去
                    close_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))
                    open_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
                    ai_skin_mask = cv2.morphologyEx(raw_ai, cv2.MORPH_CLOSE, close_k)
                    ai_skin_mask = cv2.morphologyEx(ai_skin_mask, cv2.MORPH_OPEN, open_k)

        if self.face_landmarker is not None:
            res_fl = self.face_landmarker.detect(mp_img)
            for lms in res_fl.face_landmarks:
                xs = [lm.x * w for lm in lms]
                ys = [lm.y * h for lm in lms]
                face_w = max(xs) - min(xs)
                pad = max(3, int(round(face_w * 0.025)))
                k_pad = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (pad * 2 + 1, pad * 2 + 1))

                for group in FACE_EXCLUSION_GROUPS:
                    pts = np.array(
                        [[int(round(lms[idx].x * w)), int(round(lms[idx].y * h))] for idx in group],
                        dtype=np.int32,
                    )
                    hull = cv2.convexHull(pts)
                    tmp = np.zeros((h, w), dtype=np.uint8)
                    cv2.fillConvexPoly(tmp, hull, 255)
                    tmp = cv2.dilate(tmp, k_pad)
                    face_excl = cv2.bitwise_or(face_excl, tmp)

        return ai_skin_mask, face_excl


def build_color_skin_mask(img_bgr: np.ndarray) -> np.ndarray:
    """フォールバック用（イラスト等向け）の YCrCb + HSV 肌色マスクを生成する。"""
    ycrcb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2YCrCb)
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)

    mask_ycrcb = cv2.inRange(
        ycrcb,
        np.array([45, 130, 75], dtype=np.uint8),
        np.array([255, 178, 132], dtype=np.uint8),
    )
    mask_hsv1 = cv2.inRange(
        hsv,
        np.array([0, 15, 65], dtype=np.uint8),
        np.array([28, 190, 255], dtype=np.uint8),
    )
    mask_hsv2 = cv2.inRange(
        hsv,
        np.array([165, 15, 65], dtype=np.uint8),
        np.array([180, 190, 255], dtype=np.uint8),
    )
    raw_skin = cv2.bitwise_and(mask_ycrcb, cv2.bitwise_or(mask_hsv1, mask_hsv2))

    close_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (17, 17))
    open_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    skin_mask = cv2.morphologyEx(raw_skin, cv2.MORPH_CLOSE, close_k)
    skin_mask = cv2.morphologyEx(skin_mask, cv2.MORPH_OPEN, open_k)
    return skin_mask


def build_skin_masks(
    img_bgr: np.ndarray,
    analyzer: Optional[MediaPipeSkinAnalyzer] = None,
    edge_erode_px: int = 8,
) -> Tuple[np.ndarray, np.ndarray, str]:
    """
    AI肌セグメンテーション優先＋顔パーツ除外の肌マスクを生成する。

    Returns:
        skin_mask: 肌領域マスク (0 or 255)
        inner_skin_mask: 境界誤検出を避けるため内側へ収縮した肌マスク (0 or 255)
        mode: "ai" または "color_fallback"
    """
    ai_skin = None
    face_excl = np.zeros(img_bgr.shape[:2], dtype=np.uint8)

    if analyzer is not None:
        ai_skin, face_excl = analyzer.get_skin_and_exclusion(img_bgr)

    if ai_skin is not None:
        skin_mask = cv2.bitwise_and(ai_skin, cv2.bitwise_not(face_excl))
        mode = "ai"
    else:
        skin_mask = cv2.bitwise_and(build_color_skin_mask(img_bgr), cv2.bitwise_not(face_excl))
        mode = "color_fallback"

    if edge_erode_px > 0:
        erode_size = edge_erode_px * 2 + 1
        erode_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (erode_size, erode_size))
        inner_skin_mask = cv2.erode(skin_mask, erode_k)
    else:
        inner_skin_mask = skin_mask.copy()

    return skin_mask, inner_skin_mask, mode


def detect_moles_in_image(
    img_bgr: np.ndarray,
    analyzer: Optional[MediaPipeSkinAnalyzer] = None,
    min_area: float = 1.5,
    max_area: float = 260.0,
    min_radius: float = 1.0,
    max_radius: float = 9.0,
    dog_thresh: float = 10.5,
    contrast_thresh: float = 14.0,
    min_circularity: float = 0.42,
    min_ring_skin_ratio: float = 0.88,
    max_ring_std: float = 13.0,
    edge_erode_px: int = 8,
) -> Tuple[List[Dict], str]:
    """
    単一画像から肌領域内のホクロ（極小の暗い点）を検出する。

    Returns:
        moles: 検出されたホクロ辞書のリスト [{"x", "y", "radius", "area", "contrast", "sharpness"}, ...]
        mode: 使用した肌抽出モード ("ai" / "color_fallback")
    """
    h, w = img_bgr.shape[:2]
    skin_mask, inner_skin_mask, mode = build_skin_masks(
        img_bgr, analyzer=analyzer, edge_erode_px=edge_erode_px
    )

    if cv2.countNonZero(inner_skin_mask) == 0:
        return [], mode

    lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    l_channel = lab[:, :, 0]

    # マルチスケール DoG（小スケールは極小ホクロに鋭く反応し、広い柔らかな影には反応しにくい）
    dog_small = cv2.GaussianBlur(l_channel, (0, 0), 3.0) - cv2.GaussianBlur(l_channel, (0, 0), 0.6)
    dog_med = cv2.GaussianBlur(l_channel, (0, 0), 6.0) - cv2.GaussianBlur(l_channel, (0, 0), 1.2)

    # 候補抽出: シャープな暗点（dog_small >= dog_thresh）またはやや大きめの濃い暗点
    cand_mask = (
        ((dog_small >= dog_thresh) | ((dog_med >= dog_thresh * 1.45) & (dog_small >= dog_thresh * 0.75)))
        & (inner_skin_mask > 0)
    ).astype(np.uint8) * 255

    contours, _ = cv2.findContours(cand_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    moles: List[Dict] = []

    for cnt in contours:
        area = cv2.contourArea(cnt)
        # 1〜2pxの極小ホクロは輪郭面積が0〜1.5になることがあるためピクセル数も考慮
        if area < min_area:
            x_b, y_b, bw_tmp, bh_tmp = cv2.boundingRect(cnt)
            pix_count = int(cv2.countNonZero(cand_mask[y_b : y_b + bh_tmp, x_b : x_b + bw_tmp]))
            if pix_count < max(2, int(round(min_area))):
                continue
            area = float(pix_count)
        if area > max_area:
            continue

        if area >= 10.0:
            perimeter = cv2.arcLength(cnt, True)
            if perimeter <= 0:
                continue
            circularity = 4.0 * math.pi * area / (perimeter * perimeter)
            if circularity < min_circularity:
                continue

        _, _, bw, bh = cv2.boundingRect(cnt)
        aspect = min(bw, bh) / max(bw, bh) if max(bw, bh) > 0 else 0.0
        if aspect < 0.45:
            continue

        (cx, cy), radius = cv2.minEnclosingCircle(cnt)
        if radius < min_radius or radius > max_radius:
            continue

        ix, iy = int(round(cx)), int(round(cy))
        if not (0 <= ix < w and 0 <= iy < h):
            continue

        # 中心付近のシャープネス検証（指の影・関節のくぼみ・鼻の陰影などの柔らかな影を除外）
        py0, py1 = max(0, iy - 2), min(h, iy + 3)
        px0, px1 = max(0, ix - 2), min(w, ix + 3)
        peak_dog_small = float(dog_small[py0:py1, px0:px1].max())
        peak_dog_med = float(dog_med[py0:py1, px0:px1].max())

        # 小さな点ほど鋭さ（dog_small）を重視。広い影（dog_small < dog_med * 0.85 かつ dog_small が弱い）を除外
        if peak_dog_small < dog_thresh:
            continue
        if radius <= 3.5 and peak_dog_small < peak_dog_med * 0.85:
            continue

        # 周囲リングの設定
        r_inner = max(radius + 2.5, 4.0)
        r_outer = r_inner + max(4.0, radius * 0.9)

        y0 = max(0, int(iy - r_outer - 1))
        y1 = min(h, int(iy + r_outer + 2))
        x0 = max(0, int(ix - r_outer - 1))
        x1 = min(w, int(ix + r_outer + 2))

        roi_skin = skin_mask[y0:y1, x0:x1]
        roi_l = l_channel[y0:y1, x0:x1]

        yy, xx = np.ogrid[y0:y1, x0:x1]
        dy = yy - cy
        dx = xx - cx
        dist = np.sqrt(dx * dx + dy * dy)

        ring_mask = (dist >= r_inner) & (dist <= r_outer)
        ring_total = int(np.count_nonzero(ring_mask))
        if ring_total < 12:
            continue

        ring_skin_mask = ring_mask & (roi_skin > 0)
        ring_skin_ratio = int(np.count_nonzero(ring_skin_mask)) / float(ring_total)
        if ring_skin_ratio < min_ring_skin_ratio:
            continue

        # 周囲の肌が滑らかであることを確認（耳・アクセサリ・レース・髪の境界・高ノイズ領域を除外）
        ring_l_vals = roi_l[ring_skin_mask]
        if ring_l_vals.size < 12:
            continue
        ring_std = float(np.std(ring_l_vals))
        if ring_std > max_ring_std:
            continue

        spot_mask = dist <= max(1.2, radius)
        spot_l_vals = roi_l[spot_mask]
        if spot_l_vals.size == 0:
            continue
        center_l = float(np.percentile(spot_l_vals, 15))

        # 8方向放射プロファイルチェック（全方向が周囲の明るい肌へ立ち上がる孤立点のみ通過）
        angles = np.arctan2(dy, dx)
        sector_contrasts: List[float] = []
        for s in range(8):
            a0 = -math.pi + s * (math.pi / 4.0)
            a1 = a0 + (math.pi / 4.0)
            sm = ring_skin_mask & (angles >= a0) & (angles < a1)
            if int(np.count_nonzero(sm)) >= 2:
                sector_contrasts.append(float(np.median(roi_l[sm])) - center_l)

        if len(sector_contrasts) < 7:
            continue

        sector_contrasts.sort()
        median_contrast = float(np.median(sector_contrasts))
        if median_contrast < contrast_thresh:
            continue

        # 線状の影・髪の毛・シワ・輪郭線は2方向以上が暗いままなのでここで確実に弾かれる
        if sector_contrasts[1] < max(6.0, 0.45 * median_contrast):
            continue
        if sector_contrasts[0] < max(3.0, 0.25 * median_contrast):
            continue

        moles.append(
            {
                "x": round(float(cx), 2),
                "y": round(float(cy), 2),
                "radius": round(float(radius), 2),
                "area": round(float(area), 2),
                "contrast": round(median_contrast, 2),
                "sharpness": round(peak_dog_small, 2),
            }
        )

    moles.sort(key=lambda m: (m["y"], m["x"]))
    return moles, mode


def draw_preview(img_bgr: np.ndarray, moles: List[Dict], mode: str = "") -> np.ndarray:
    """検出箇所を赤丸で囲んだプレビュー画像を生成する。"""
    preview = img_bgr.copy()
    for idx, m in enumerate(moles, start=1):
        cx = int(round(m["x"]))
        cy = int(round(m["y"]))
        r_draw = max(int(round(m["radius"])) + 7, 10)
        cv2.circle(preview, (cx, cy), r_draw, (0, 0, 255), 2, lineType=cv2.LINE_AA)
        cv2.putText(
            preview,
            str(idx),
            (cx + r_draw + 2, cy + 4),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (0, 0, 255),
            1,
            cv2.LINE_AA,
        )

    label = f"Detected moles: {len(moles)}" + (f" [{mode}]" if mode else "")
    cv2.putText(preview, label, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(preview, label, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2, cv2.LINE_AA)
    return preview


def collect_images(input_dir: Path, recursive: bool = False) -> List[Path]:
    """対象フォルダから画像ファイル一覧を取得する。"""
    if recursive:
        files = [p for p in input_dir.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS]
    else:
        files = [p for p in input_dir.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS]
    return sorted(files)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="肌領域内の小さなホクロ（暗い点）を自動検出し、JSONとプレビュー画像を出力します。"
    )
    parser.add_argument("--input", "-i", required=True, help="入力画像フォルダのパス")
    parser.add_argument("--json", "-j", required=True, help="座標リストJSONの出力パス")
    parser.add_argument("--preview-dir", "-p", required=True, help="赤丸プレビュー画像の出力フォルダ")
    parser.add_argument("--psd-dir", "-o", required=True, help="PhotoshopのPSD出力フォルダ（JSONへ記録）")
    parser.add_argument("--recursive", action="store_true", help="サブフォルダも再帰的に探索する")
    parser.add_argument("--no-ai", action="store_true", help="MediaPipe AI肌抽出を使わず色ベースのみで実行する")

    # 検出感度パラメータ
    parser.add_argument("--min-area", type=float, default=1.5, help="最小面積 px^2 (default: 1.5)")
    parser.add_argument("--max-area", type=float, default=260.0, help="最大面積 px^2 (default: 260.0)")
    parser.add_argument("--min-radius", type=float, default=1.0, help="最小半径 px (default: 1.0)")
    parser.add_argument("--max-radius", type=float, default=9.0, help="最大半径 px (default: 9.0)")
    parser.add_argument("--dog-thresh", type=float, default=10.5, help="シャープ暗点 DoG 閾値 (default: 10.5)")
    parser.add_argument("--contrast-thresh", type=float, default=14.0, help="周囲肌との輝度差閾値 (default: 14.0)")
    parser.add_argument("--min-circularity", type=float, default=0.42, help="最小円形度 0-1 (default: 0.42)")
    parser.add_argument("--min-ring-skin-ratio", type=float, default=0.88, help="周囲リングの肌色比率 (default: 0.88)")
    parser.add_argument("--max-ring-std", type=float, default=13.0, help="周囲リング輝度標準偏差の上限 (default: 13.0)")
    parser.add_argument("--edge-erode", type=int, default=8, help="肌輪郭からの除外幅 px (default: 8)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    input_dir = Path(args.input).resolve()
    json_path = Path(args.json).resolve()
    preview_dir = Path(args.preview_dir).resolve()
    psd_dir = Path(args.psd_dir).resolve()

    if not input_dir.exists() or not input_dir.is_dir():
        print(f"[ERROR] 入力フォルダが存在しません: {input_dir}", file=sys.stderr)
        return 1

    preview_dir.mkdir(parents=True, exist_ok=True)
    psd_dir.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)

    models_dir = Path(__file__).resolve().parent / "models"
    analyzer = MediaPipeSkinAnalyzer(models_dir=models_dir, enabled=not args.no_ai)

    image_files = collect_images(input_dir, recursive=args.recursive)
    if not image_files:
        print(f"[WARN] 対象画像が見つかりませんでした: {input_dir}")

    results = []
    total_moles = 0

    for img_path in image_files:
        try:
            img_bgr = imread_unicode(img_path)
            h, w = img_bgr.shape[:2]
            moles, mode = detect_moles_in_image(
                img_bgr,
                analyzer=analyzer,
                min_area=args.min_area,
                max_area=args.max_area,
                min_radius=args.min_radius,
                max_radius=args.max_radius,
                dog_thresh=args.dog_thresh,
                contrast_thresh=args.contrast_thresh,
                min_circularity=args.min_circularity,
                min_ring_skin_ratio=args.min_ring_skin_ratio,
                max_ring_std=args.max_ring_std,
                edge_erode_px=args.edge_erode,
            )

            preview_img = draw_preview(img_bgr, moles, mode=mode)
            rel_name = img_path.relative_to(input_dir)
            preview_out = preview_dir / rel_name.with_name(f"{img_path.stem}_preview.png")
            imwrite_unicode(preview_out, preview_img)

            results.append(
                {
                    "filename": img_path.name,
                    "filepath": str(img_path),
                    "preview_path": str(preview_out),
                    "width": w,
                    "height": h,
                    "skin_mode": mode,
                    "moles": moles,
                }
            )
            total_moles += len(moles)
            print(f"[OK] {img_path.name} [{mode}]: {len(moles)} 個検出 -> {preview_out.name}")
        except Exception as exc:
            print(f"[ERROR] {img_path.name} の処理中にエラー: {exc}", file=sys.stderr)

    payload = {
        "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "input_dir": str(input_dir),
        "preview_dir": str(preview_dir),
        "output_psd_dir": str(psd_dir),
        "params": {
            "ai_enabled": not args.no_ai,
            "min_area": args.min_area,
            "max_area": args.max_area,
            "min_radius": args.min_radius,
            "max_radius": args.max_radius,
            "dog_thresh": args.dog_thresh,
            "contrast_thresh": args.contrast_thresh,
            "min_circularity": args.min_circularity,
            "min_ring_skin_ratio": args.min_ring_skin_ratio,
            "max_ring_std": args.max_ring_std,
            "edge_erode": args.edge_erode,
        },
        "summary": {
            "total_images": len(results),
            "total_moles": total_moles,
        },
        "images": results,
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    pointer_path = Path(__file__).resolve().parent / "last_job.txt"
    pointer_path.write_text(str(json_path), encoding="utf-8")

    print(f"\n完了: {len(results)} 枚処理 / 合計 {total_moles} 個のホクロを検出")
    print(f"JSON出力: {json_path}")
    print(f"プレビュー出力: {preview_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
