#target photoshop
app.bringToFront();

/**
 * remove_moles.jsx
 * detect_moles.py が出力した座標JSONを読み込み、
 * 元レイヤーを複製した別レイヤーに対してスポット修復（コンテンツに応じた塗りつぶし）を実行し、
 * PSD形式で保存する Photoshop ExtendScript。
 */

// ============================================================
// 設定
// ============================================================
var RETOUCH_LAYER_NAME = "Moles_Removed";
var SAVE_IF_NO_MOLES = false;       // ホクロ0個でもPSD保存する場合は true
var SELECTION_RADIUS_MULT = 2.2;    // 検出半径に対する選択範囲倍率
var SELECTION_PADDING_PX = 4;       // 選択範囲の追加余白 (px)
var SELECTION_MIN_RADIUS_PX = 8;    // 最小選択半径 (px)
var SELECTION_FEATHER_PX = 1.5;     // 選択範囲のぼかし (px)

// ============================================================
// ES3 互換 JSON パーサ
// ============================================================
function parseJSON(text) {
    var at = 0;
    var ch = " ";

    // UTF-8 BOM 除去
    if (text && text.charCodeAt(0) === 0xFEFF) {
        text = text.slice(1);
    }

    function error(m) {
        throw new Error("JSON Parse Error at " + at + ": " + m);
    }

    function next(c) {
        if (c && c !== ch) {
            error("Expected '" + c + "' instead of '" + ch + "'");
        }
        ch = text.charAt(at);
        at += 1;
        return ch;
    }

    function white() {
        while (ch && ch <= " ") {
            next();
        }
    }

    function number() {
        var str = "";
        if (ch === "-") {
            str = "-";
            next("-");
        }
        while (ch >= "0" && ch <= "9") {
            str += ch;
            next();
        }
        if (ch === ".") {
            str += ".";
            while (next() && ch >= "0" && ch <= "9") {
                str += ch;
            }
        }
        if (ch === "e" || ch === "E") {
            str += ch;
            next();
            if (ch === "-" || ch === "+") {
                str += ch;
                next();
            }
            while (ch >= "0" && ch <= "9") {
                str += ch;
                next();
            }
        }
        var num = Number(str);
        if (isNaN(num)) {
            error("Bad number: " + str);
        }
        return num;
    }

    function string() {
        var hex, i, str = "", uffff;
        var escapee = {
            '"': '"',
            "\\": "\\",
            "/": "/",
            b: "\b",
            f: "\f",
            n: "\n",
            r: "\r",
            t: "\t"
        };
        if (ch === '"') {
            while (next()) {
                if (ch === '"') {
                    next();
                    return str;
                }
                if (ch === "\\") {
                    next();
                    if (ch === "u") {
                        uffff = 0;
                        for (i = 0; i < 4; i += 1) {
                            hex = parseInt(next(), 16);
                            if (!isFinite(hex)) {
                                break;
                            }
                            uffff = uffff * 16 + hex;
                        }
                        str += String.fromCharCode(uffff);
                    } else if (typeof escapee[ch] === "string") {
                        str += escapee[ch];
                    } else {
                        break;
                    }
                } else {
                    str += ch;
                }
            }
        }
        error("Bad string");
    }

    function word() {
        switch (ch) {
            case "t":
                next("t"); next("r"); next("u"); next("e");
                return true;
            case "f":
                next("f"); next("a"); next("l"); next("s"); next("e");
                return false;
            case "n":
                next("n"); next("u"); next("l"); next("l");
                return null;
        }
        error("Unexpected '" + ch + "'");
    }

    function array() {
        var arr = [];
        if (ch === "[") {
            next("[");
            white();
            if (ch === "]") {
                next("]");
                return arr;
            }
            while (ch) {
                arr.push(value());
                white();
                if (ch === "]") {
                    next("]");
                    return arr;
                }
                next(",");
                white();
            }
        }
        error("Bad array");
    }

    function object() {
        var key, obj = {};
        if (ch === "{") {
            next("{");
            white();
            if (ch === "}") {
                next("}");
                return obj;
            }
            while (ch) {
                key = string();
                white();
                next(":");
                obj[key] = value();
                white();
                if (ch === "}") {
                    next("}");
                    return obj;
                }
                next(",");
                white();
            }
        }
        error("Bad object");
    }

    function value() {
        white();
        switch (ch) {
            case "{": return object();
            case "[": return array();
            case '"': return string();
            case "-": return number();
            default:
                return (ch >= "0" && ch <= "9") ? number() : word();
        }
    }

    var result = value();
    white();
    if (ch) {
        error("Trailing characters");
    }
    return result;
}

// ============================================================
// ユーティリティ関数
// ============================================================
function trimString(s) {
    return s.replace(/^\s+|\s+$/g, "").replace(/^\uFEFF/, "");
}

function readUtf8File(fileObj) {
    fileObj.encoding = "UTF-8";
    if (!fileObj.open("r")) {
        throw new Error("ファイルを開けません: " + fileObj.fsName);
    }
    var content = fileObj.read();
    fileObj.close();
    return content;
}

function writeUtf8File(fileObj, content) {
    fileObj.encoding = "UTF-8";
    if (!fileObj.open("w")) {
        return;
    }
    fileObj.write(content);
    fileObj.close();
}

function getBaseName(filename) {
    var idx = filename.lastIndexOf(".");
    return (idx > 0) ? filename.substring(0, idx) : filename;
}

function resolveJsonFile() {
    var scriptFolder = File($.fileName).parent;

    // 1. detect_moles.py が書き出すポインタファイルを確認
    var pointerFile = new File(scriptFolder.fsName + "/last_job.txt");
    if (pointerFile.exists) {
        var jsonPath = trimString(readUtf8File(pointerFile));
        if (jsonPath.length > 0) {
            var target = new File(jsonPath);
            if (target.exists) {
                return target;
            }
        }
    }

    // 2. デフォルト出力先を確認
    var defaultJson = new File(scriptFolder.fsName + "/output/moles_coords.json");
    if (defaultJson.exists) {
        return defaultJson;
    }

    // 3. 手動実行時のフォールバックダイアログ
    return File.openDialog("ホクロ座標JSONファイルを選択してください", "*.json");
}

// ============================================================
// Photoshop 選択 & コンテンツに応じた塗りつぶし (ActionManager)
// ============================================================
function setEllipticalSelection(topPx, leftPx, bottomPx, rightPx, featherPx) {
    var descSet = new ActionDescriptor();
    var refSel = new ActionReference();
    refSel.putProperty(charIDToTypeID("Chnl"), charIDToTypeID("fsel"));
    descSet.putReference(charIDToTypeID("null"), refSel);

    var descElps = new ActionDescriptor();
    descElps.putUnitDouble(charIDToTypeID("Top "), charIDToTypeID("#Pxl"), topPx);
    descElps.putUnitDouble(charIDToTypeID("Left"), charIDToTypeID("#Pxl"), leftPx);
    descElps.putUnitDouble(charIDToTypeID("Btom"), charIDToTypeID("#Pxl"), bottomPx);
    descElps.putUnitDouble(charIDToTypeID("Rght"), charIDToTypeID("#Pxl"), rightPx);

    descSet.putObject(charIDToTypeID("T   "), charIDToTypeID("Elps"), descElps);
    if (featherPx > 0) {
        descSet.putUnitDouble(charIDToTypeID("Fthr"), charIDToTypeID("#Pxl"), featherPx);
    }
    descSet.putBoolean(charIDToTypeID("AntA"), true);

    executeAction(charIDToTypeID("setd"), descSet, DialogModes.NO);
}

function runContentAwareFill() {
    var descFill = new ActionDescriptor();
    descFill.putEnumerated(
        charIDToTypeID("Usng"),
        charIDToTypeID("FlCn"),
        stringIDToTypeID("contentAware")
    );
    descFill.putBoolean(stringIDToTypeID("contentAwareColorAdaptationFill"), true);
    descFill.putUnitDouble(charIDToTypeID("Opct"), charIDToTypeID("#Prc"), 100.0);
    descFill.putEnumerated(
        charIDToTypeID("Md  "),
        charIDToTypeID("BlnM"),
        charIDToTypeID("Nrml")
    );
    executeAction(charIDToTypeID("Fl  "), descFill, DialogModes.NO);
}

function saveAsPSD(doc, outputFile) {
    var opts = new PhotoshopSaveOptions();
    opts.alphaChannels = true;
    opts.annotations = true;
    opts.embedColorProfile = true;
    opts.layers = true;
    opts.spotColors = true;
    opts.maximizeCompatibility = true;
    doc.saveAs(outputFile, opts, true, Extension.LOWERCASE);
}

// ============================================================
// メイン処理
// ============================================================
function main() {
    var originalRulerUnits = app.preferences.rulerUnits;
    var originalDialogs = app.displayDialogs;

    var logLines = [];
    function log(msg) {
        logLines.push(msg);
    }

    try {
        app.preferences.rulerUnits = Units.PIXELS;
        app.displayDialogs = DialogModes.NO;

        var jsonFile = resolveJsonFile();
        if (!jsonFile || !jsonFile.exists) {
            alert("座標JSONファイルが見つかりませんでした。処理を中止します。");
            return;
        }

        log("JSON: " + jsonFile.fsName);
        var jsonText = readUtf8File(jsonFile);
        var data = parseJSON(jsonText);

        var outputDirPath = data.output_psd_dir || (jsonFile.parent.fsName + "/psd");
        var outputFolder = new Folder(outputDirPath);
        if (!outputFolder.exists) {
            outputFolder.create();
        }

        var images = data.images || [];
        var processedCount = 0;
        var skippedCount = 0;
        var errorCount = 0;

        for (var i = 0; i < images.length; i++) {
            var item = images[i];
            var moles = item.moles || [];

            if (moles.length === 0 && !SAVE_IF_NO_MOLES) {
                skippedCount++;
                log("[SKIP] " + item.filename + " (ホクロ検出 0 個)");
                continue;
            }

            var srcFile = new File(item.filepath);
            if (!srcFile.exists) {
                errorCount++;
                log("[ERROR] 元画像が見つかりません: " + item.filepath);
                continue;
            }

            var doc = null;
            try {
                doc = app.open(srcFile);

                // インデックスカラー等の場合はRGBに変換（コンテンツに応じた塗りつぶし対応）
                if (doc.mode !== DocumentMode.RGB) {
                    doc.changeMode(ChangeMode.RGB);
                }

                // 元レイヤーを複製して別レイヤーを作成
                var originalLayer = doc.activeLayer;
                var retouchLayer = originalLayer.duplicate();
                retouchLayer.name = RETOUCH_LAYER_NAME;
                doc.activeLayer = retouchLayer;

                var docW = doc.width.as("px");
                var docH = doc.height.as("px");

                // 各ホクロ座標に対してスポット修復（コンテンツに応じた塗りつぶし）を実行
                for (var j = 0; j < moles.length; j++) {
                    var m = moles[j];
                    var cx = Number(m.x);
                    var cy = Number(m.y);
                    var r = Number(m.radius || 3);

                    var selR = Math.max(
                        Math.round(r * SELECTION_RADIUS_MULT) + SELECTION_PADDING_PX,
                        SELECTION_MIN_RADIUS_PX
                    );

                    var left = Math.max(0, cx - selR);
                    var top = Math.max(0, cy - selR);
                    var right = Math.min(docW, cx + selR);
                    var bottom = Math.min(docH, cy + selR);

                    if (right - left < 2 || bottom - top < 2) {
                        continue;
                    }

                    setEllipticalSelection(top, left, bottom, right, SELECTION_FEATHER_PX);
                    runContentAwareFill();
                    doc.selection.deselect();
                }

                // PSD保存
                var baseName = getBaseName(item.filename);
                var outFile = new File(outputFolder.fsName + "/" + baseName + "_retouched.psd");
                saveAsPSD(doc, outFile);

                processedCount++;
                log("[OK] " + item.filename + " (" + moles.length + " 箇所修復) -> " + outFile.name);
            } catch (imgErr) {
                errorCount++;
                log("[ERROR] " + item.filename + ": " + imgErr.message);
            } finally {
                if (doc !== null) {
                    doc.close(SaveOptions.DONOTSAVECHANGES);
                }
            }
        }

        log("--------------------------------------------------");
        log("完了: 処理 " + processedCount + " 枚 / スキップ " + skippedCount + " 枚 / エラー " + errorCount + " 枚");

        var logFile = new File(outputFolder.fsName + "/photoshop_log.txt");
        writeUtf8File(logFile, logLines.join("\r\n"));
    } catch (e) {
        alert("remove_moles.jsx でエラーが発生しました:\n" + e.message);
    } finally {
        app.preferences.rulerUnits = originalRulerUnits;
        app.displayDialogs = originalDialogs;
    }
}

main();
