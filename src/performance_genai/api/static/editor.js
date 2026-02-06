(function () {
  try {
    var desc = Object.getOwnPropertyDescriptor(CanvasRenderingContext2D.prototype, "textBaseline");
    if (desc && desc.set && desc.get) {
      Object.defineProperty(CanvasRenderingContext2D.prototype, "textBaseline", {
        configurable: true,
        get: function () {
          return desc.get.call(this);
        },
        set: function (value) {
          var v = value === "alphabetical" ? "alphabetic" : value;
          return desc.set.call(this, v);
        },
      });
    }
  } catch (e) {
    // Ignore if the environment disallows patching.
  }

  function startEditor() {
    if (!window.fabric) {
      return false;
    }
  var kvDataEl = document.getElementById("kv-data");
  if (!kvDataEl) return;
  var layoutDataEl = document.getElementById("layout-data");

  var projectId = (document.body && document.body.dataset && document.body.dataset.projectId) || "default";
  var stateKey = "pg_editor_state_" + projectId;
  var previewDensityKey = "pg_preview_density_" + projectId;
  var debugEl = document.getElementById("debug-log");
  function log(msg) {
    if (!debugEl) return;
    var line = "[" + new Date().toISOString() + "] " + msg;
    debugEl.textContent += line + "\n";
  }

  var kvs = [];
  try {
    kvs = JSON.parse(kvDataEl.textContent || "[]");
  } catch (e) {
    kvs = [];
  }
  log("KV choices: " + kvs.length);
  var kvMap = {};
  kvs.forEach(function (k) {
    kvMap[k.id] = k;
  });

  var layoutData = null;
  if (layoutDataEl) {
    try {
      layoutData = JSON.parse(layoutDataEl.textContent || "null");
    } catch (e) {
      layoutData = null;
    }
  }

  var select = document.getElementById("kv-select");
  var label = document.getElementById("kv-label");
  var fontSelect = document.getElementById("font-select");
  var fontScaleInput = document.getElementById("font-scale");
  var fontScaleValue = document.getElementById("font-scale-value");
  var fontSizeSelect = document.getElementById("font-size-select");
  var fontSizeCustom = document.getElementById("font-size-custom");
  var alignSelect = document.getElementById("align-select");
  var guideSelect = document.getElementById("guide-select");
  var btnPreview = document.getElementById("btn-preview");
  var btnInsertText = document.getElementById("btn-insert-text");
  var btnUndo = document.getElementById("btn-undo");
  var btnDeleteText = document.getElementById("btn-delete-text");
  var btnDuplicateText = document.getElementById("btn-duplicate-text");
  var btnBringForward = document.getElementById("btn-bring-forward");
  var btnSendBack = document.getElementById("btn-send-back");
  var copyButtons = document.querySelectorAll(".use-copy-set");
  var assetInsertButtons = document.querySelectorAll("[data-insert-asset]");
  var layerPanel = document.getElementById("layer-panel");
  var ratioLabel = document.getElementById("ratio-label");
  var loadingOverlay = document.getElementById("loading-overlay");
  var canvasWrap = document.getElementById("canvas-wrap");
  var btnCenterGuide = document.getElementById("btn-center-guide");
  var btnZoomIn = document.getElementById("btn-zoom-in");
  var btnZoomOut = document.getElementById("btn-zoom-out");
  var btnZoomFit = document.getElementById("btn-zoom-fit");
  var zoomReadout = document.getElementById("zoom-readout");
  var btnPreviewDensity = document.getElementById("btn-preview-density");
  var btnExportCurrent = document.getElementById("btn-export-current");

  var colorPicker = document.getElementById("color-picker");
  var colorInput = document.getElementById("color-input");
  var colorSwatch = document.getElementById("color-swatch");
  var textBgColor = document.getElementById("text-bg-color");
  var textBgHex = document.getElementById("text-bg-hex");
  var textBgOpacity = document.getElementById("text-bg-opacity");
  var textBgRadius = document.getElementById("text-bg-radius");
  var shapeColor = document.getElementById("shape-color");
  var shapeHex = document.getElementById("shape-hex");
  var shapeOpacity = document.getElementById("shape-opacity");
  var shapeButtons = document.querySelectorAll("[data-shape]");
  var assetUploadBtn = document.getElementById("btn-upload-asset");
  var assetUploadFile = document.getElementById("asset-upload-file");
  var assetUploadName = document.getElementById("asset-upload-name");

  if (!select || !document.getElementById("editor-canvas")) return;

    var canvas = new fabric.Canvas("editor-canvas", {
    selection: true,
    preserveObjectStacking: true,
  });
    var stageEl = document.getElementById("canvas-stage");
    if (stageEl && canvas && canvas.wrapperEl) {
      canvas.wrapperEl.style.position = "relative";
      canvas.wrapperEl.style.left = "0px";
      canvas.wrapperEl.style.top = "0px";
      canvas.wrapperEl.style.zIndex = "2";
      canvas.wrapperEl.style.background = "transparent";
    }
    if (fabric.Textbox && fabric.Textbox.prototype) {
      fabric.Textbox.prototype.textBaseline = "alphabetic";
    }
    if (fabric.Text && fabric.Text.prototype) {
      fabric.Text.prototype.textBaseline = "alphabetic";
    }

  if (colorSwatch && colorInput) {
    colorSwatch.style.background = colorInput.value || "#ffffff";
  }

  var canvasSize = { w: canvas.getWidth(), h: canvas.getHeight() };
  var imageSize = { w: canvasSize.w, h: canvasSize.h };
  var bgObj = null;
  var currentOffset = { x: 0, y: 0 };
  var guideRatio = (guideSelect && guideSelect.value) || "1:1";
  var guideBounds = null;
  var guideRect = null;
  var boardEdgeRect = null;
  var deadzoneRects = [];
  var deadzonePatternSource = null;
  var zoomLevel = 1;

  var defaultTextBox = { x: 0.08, y: 0.62, w: 0.80, h: 0.14 };
  var defaultCopyBoxes = [
    { x: 0.08, y: 0.60, w: 0.84, h: 0.16 },
    { x: 0.08, y: 0.78, w: 0.84, h: 0.10 },
    { x: 0.08, y: 0.90, w: 0.44, h: 0.07 },
  ];

  var history = [];
  var historyIndex = -1;
  var historyLock = false;
  var historyTimer = null;
  var lastSnapshot = "";
  var historyLimit = 3;
  var isSpaceDown = false;
  var isPanDragging = false;
  var panStartX = 0;
  var panStartY = 0;
  var panStartLeft = 0;
  var panStartTop = 0;
  var panStartViewportX = 0;
  var panStartViewportY = 0;
  var panMode = "scroll";
  var resizeTimer = null;

  function showLoader() {
    if (loadingOverlay) {
      loadingOverlay.classList.add("active");
    }
  }

  function updateRatioLabel() {
    if (!ratioLabel) return;
    ratioLabel.textContent = "ratio: " + guideRatio;
  }

  function getTextObjects() {
    return canvas.getObjects().filter(function (obj) {
      return obj && obj.type === "textbox";
    });
  }

  function getBackgroundObject() {
    return bgObj;
  }

  function getElementObjects() {
    return canvas.getObjects().filter(function (obj) {
      return obj && obj.type === "image" && obj.pg_asset_id;
    });
  }

  function getShapeObjects() {
    return canvas.getObjects().filter(function (obj) {
      return obj && obj.pg_is_shape;
    });
  }

  function findTextBgRect(textObj) {
    if (!textObj || !textObj.pg_id) return null;
    var objs = canvas.getObjects();
    for (var i = 0; i < objs.length; i++) {
      var obj = objs[i];
      if (obj && obj.pg_is_text_bg && obj.pg_bg_for === textObj.pg_id) {
        return obj;
      }
    }
    return null;
  }

  function rgbaFromHex(hex, opacity) {
    var h = (hex || "").replace("#", "");
    if (h.length === 3) {
      h = h.split("").map(function (c) { return c + c; }).join("");
    }
    var r = parseInt(h.substring(0, 2) || "00", 16);
    var g = parseInt(h.substring(2, 4) || "00", 16);
    var b = parseInt(h.substring(4, 6) || "00", 16);
    var a = Math.max(0, Math.min(1, opacity == null ? 1 : opacity));
    return "rgba(" + r + "," + g + "," + b + "," + a.toFixed(3) + ")";
  }

  function getTextBgSettings() {
    var color = (textBgHex && textBgHex.value) || (textBgColor && textBgColor.value) || "#000000";
    var opacity = textBgOpacity ? (parseFloat(textBgOpacity.value || "0") / 100) : 0;
    var radiusType = textBgRadius ? textBgRadius.value : "square";
    var radius = 0;
    if (radiusType === "soft") radius = 8;
    if (radiusType === "round") radius = 999;
    return { color: color, opacity: opacity, radius: radius };
  }

  function getTextBgPadding(obj) {
    var base = getGuideBounds();
    var baseW = base.width || 1;
    var fontPx = (obj && obj.fontSize) ? obj.fontSize : 12;
    var pad = Math.max(4, Math.min(24, fontPx * 0.22));
    return { pad: pad, baseWidth: baseW };
  }

  function syncTextBgControls(obj) {
    if (!obj) return;
    var color = obj.pg_bg_color || ((textBgHex && textBgHex.value) || "#000000");
    var opacity = obj.pg_bg_opacity == null ? (textBgOpacity ? parseFloat(textBgOpacity.value || "0") / 100 : 0) : obj.pg_bg_opacity;
    var radius = obj.pg_bg_radius == null ? getTextBgSettings().radius : obj.pg_bg_radius;
    if (textBgHex) textBgHex.value = color;
    if (textBgColor) textBgColor.value = color;
    if (textBgOpacity) textBgOpacity.value = Math.round(opacity * 100);
    if (textBgRadius) {
      if (radius >= 999) textBgRadius.value = "round";
      else if (radius > 0) textBgRadius.value = "soft";
      else textBgRadius.value = "square";
    }
  }

  function syncShapeControls(obj) {
    if (!obj || !obj.pg_is_shape) return;
    var color = obj.pg_shape_color || obj.fill || "#ffffff";
    if (shapeHex) shapeHex.value = color;
    if (shapeColor) shapeColor.value = color;
    if (shapeOpacity) shapeOpacity.value = Math.round((obj.pg_shape_opacity == null ? 1 : obj.pg_shape_opacity) * 100);
  }

  function updateTextBackground(obj) {
    if (!obj) return;
    var rect = findTextBgRect(obj);
    var color = obj.pg_bg_color;
    var opacity = obj.pg_bg_opacity;
    var radius = obj.pg_bg_radius || 0;
    if (!color || opacity == null || opacity <= 0) {
      if (rect) canvas.remove(rect);
      return;
    }
    var box = getObjectRect(obj);
    var padInfo = getTextBgPadding(obj);
    obj.pg_bg_pad = padInfo.pad;
    obj.pg_bg_pad_base_width = padInfo.baseWidth;
    var pad = padInfo.pad;
    var left = box.left - pad;
    var top = box.top - pad;
    var width = box.width + pad * 2;
    var height = box.height + pad * 2;
    var rx = radius >= 999 ? Math.min(width, height) / 2 : radius;
    if (!rect) {
      rect = new fabric.Rect({
        left: left,
        top: top,
        width: width,
        height: height,
        fill: rgbaFromHex(color, opacity),
        rx: rx,
        ry: rx,
        selectable: false,
        evented: false,
        hoverCursor: "default",
        excludeFromExport: true,
      });
      rect.pg_is_text_bg = true;
      rect.pg_bg_for = obj.pg_id;
      canvas.add(rect);
    } else {
      rect.set({
        left: left,
        top: top,
        width: width,
        height: height,
        fill: rgbaFromHex(color, opacity),
        rx: rx,
        ry: rx,
      });
    }
    var idx = canvas.getObjects().indexOf(obj);
    if (idx >= 1) {
      canvas.moveTo(rect, idx - 1);
    } else {
      canvas.sendToBack(rect);
    }
    syncCanvasOrder();
  }

  function applyTextBackgroundToSelection() {
    var obj = getActiveText();
    if (!obj) return;
    var settings = getTextBgSettings();
    obj.pg_bg_color = settings.color;
    obj.pg_bg_opacity = settings.opacity;
    obj.pg_bg_radius = settings.radius;
    obj.pg_bg_radius_base_width = getGuideBounds().width;
    updateTextBackground(obj);
    canvas.renderAll();
    saveState();
    snapshotNow();
  }

  function removeTextBackground(obj) {
    if (!obj) return;
    var rect = findTextBgRect(obj);
    if (rect) canvas.remove(rect);
  }

  function ensureObjectId(obj) {
    if (!obj) return;
    if (!obj.pg_id) {
      obj.pg_id = "obj_" + Math.random().toString(36).slice(2, 10);
    }
  }

  function getActiveText() {
    var obj = canvas.getActiveObject();
    if (obj && obj.type === "textbox") return obj;
    return null;
  }

  function getActiveObject() {
    return canvas.getActiveObject();
  }

  function parseRatio(value) {
    var parts = (value || "").split(":");
    if (parts.length !== 2) return null;
    var w = parseFloat(parts[0]);
    var h = parseFloat(parts[1]);
    if (!w || !h) return null;
    return { w: w, h: h };
  }

  function normalizeBox(box) {
    if (!box) return null;
    if (Array.isArray(box) && box.length >= 4) {
      return { x: box[0], y: box[1], w: box[2], h: box[3] };
    }
    if (typeof box.x === "number" && typeof box.y === "number") {
      return box;
    }
    return null;
  }

  function getGuideBounds() {
    if (guideBounds && guideBounds.width && guideBounds.height) return guideBounds;
    return { left: 0, top: 0, width: canvasSize.w, height: canvasSize.h };
  }

  function getObjectRect(obj) {
    if (!obj) return { left: 0, top: 0, width: 0, height: 0 };
    var width = obj.getScaledWidth ? obj.getScaledWidth() : ((obj.width || 0) * (obj.scaleX || 1));
    var height = obj.getScaledHeight ? obj.getScaledHeight() : ((obj.height || 0) * (obj.scaleY || 1));
    var left = obj.left || 0;
    var top = obj.top || 0;
    return {
      left: left,
      top: top,
      width: width,
      height: height,
    };
  }

  function getDeadzonePattern() {
    if (!deadzonePatternSource) {
      deadzonePatternSource = document.createElement("canvas");
      deadzonePatternSource.width = 14;
      deadzonePatternSource.height = 14;
      var ctx = deadzonePatternSource.getContext("2d");
      if (ctx) {
        ctx.fillStyle = "rgba(8,10,14,0.42)";
        ctx.fillRect(0, 0, 14, 14);
        ctx.fillStyle = "rgba(255,255,255,0.16)";
        ctx.beginPath();
        ctx.arc(3.5, 3.5, 1, 0, Math.PI * 2);
        ctx.fill();
        ctx.beginPath();
        ctx.arc(10.5, 10.5, 1, 0, Math.PI * 2);
        ctx.fill();
      }
    }
    return new fabric.Pattern({
      source: deadzonePatternSource,
      repeat: "repeat",
    });
  }

  function ensureDeadzoneRects() {
    if (deadzoneRects.length === 4) return;
    while (deadzoneRects.length < 4) {
      var rect = new fabric.Rect({
        left: 0,
        top: 0,
        width: 0,
        height: 0,
        fill: getDeadzonePattern(),
        selectable: false,
        evented: false,
        hoverCursor: "default",
        excludeFromExport: true,
      });
      rect.pg_is_deadzone = true;
      deadzoneRects.push(rect);
      canvas.add(rect);
    }
  }

  function updateBoardEdge() {
    if (!boardEdgeRect) {
      boardEdgeRect = new fabric.Rect({
        left: 0,
        top: 0,
        width: canvasSize.w,
        height: canvasSize.h,
        fill: "rgba(0,0,0,0)",
        stroke: "rgba(255,255,255,0.28)",
        strokeWidth: 1,
        selectable: false,
        evented: false,
        hoverCursor: "default",
        excludeFromExport: true,
      });
      boardEdgeRect.pg_is_board_edge = true;
      canvas.add(boardEdgeRect);
    } else {
      boardEdgeRect.set({
        left: 0,
        top: 0,
        width: canvasSize.w,
        height: canvasSize.h,
      });
    }
    boardEdgeRect.setCoords();
  }

  function updateDeadzoneOverlay(bounds) {
    ensureDeadzoneRects();
    var fullW = Math.max(0, canvasSize.w);
    var fullH = Math.max(0, canvasSize.h);
    var left = Math.max(0, Math.floor(bounds.left));
    var top = Math.max(0, Math.floor(bounds.top));
    var right = Math.min(fullW, Math.ceil(bounds.left + bounds.width));
    var bottom = Math.min(fullH, Math.ceil(bounds.top + bounds.height));
    var zones = [
      { left: 0, top: 0, width: fullW, height: top },
      { left: 0, top: top, width: left, height: Math.max(0, bottom - top) },
      { left: right, top: top, width: Math.max(0, fullW - right), height: Math.max(0, bottom - top) },
      { left: 0, top: bottom, width: fullW, height: Math.max(0, fullH - bottom) },
    ];
    for (var i = 0; i < deadzoneRects.length; i++) {
      var rect = deadzoneRects[i];
      var zone = zones[i];
      rect.set({
        left: zone.left,
        top: zone.top,
        width: Math.max(0, zone.width),
        height: Math.max(0, zone.height),
        visible: zone.width > 0 && zone.height > 0,
      });
      rect.setCoords();
    }
  }

  function syncCanvasOrder() {
    if (bgObj) {
      canvas.sendToBack(bgObj);
    }
    ensureDeadzoneRects();
    updateBoardEdge();
    var start = bgObj ? 1 : 0;
    for (var i = 0; i < deadzoneRects.length; i++) {
      var rect = deadzoneRects[i];
      if (canvas.getObjects().indexOf(rect) === -1) {
        canvas.add(rect);
      }
      canvas.moveTo(rect, start + i);
    }
    if (boardEdgeRect && canvas.getObjects().indexOf(boardEdgeRect) === -1) {
      canvas.add(boardEdgeRect);
    }
    if (boardEdgeRect) {
      canvas.bringToFront(boardEdgeRect);
    }
    if (guideRect) {
      canvas.bringToFront(guideRect);
    }
  }

  function getDragOverflowRatio(obj) {
    if (!obj) return 0.25;
    if (obj.pg_is_background) return 0.45;
    return 0.25;
  }

  function clampObjectToWorkspace(obj) {
    if (!obj) return;
    if (obj === guideRect || obj.pg_is_deadzone || obj.pg_is_board_edge || obj.pg_is_text_bg) return;
    var rect = getObjectRect(obj);
    var over = getDragOverflowRatio(obj);
    var maxOverX = canvasSize.w * over;
    var maxOverY = canvasSize.h * over;
    var minLeft = -maxOverX;
    var maxLeft = canvasSize.w - rect.width + maxOverX;
    var minTop = -maxOverY;
    var maxTop = canvasSize.h - rect.height + maxOverY;
    var nextLeft = obj.left;
    var nextTop = obj.top;
    if (maxLeft < minLeft) {
      nextLeft = (minLeft + maxLeft) / 2;
    } else {
      nextLeft = Math.max(minLeft, Math.min(maxLeft, nextLeft));
    }
    if (maxTop < minTop) {
      nextTop = (minTop + maxTop) / 2;
    } else {
      nextTop = Math.max(minTop, Math.min(maxTop, nextTop));
    }
    if (nextLeft !== obj.left || nextTop !== obj.top) {
      obj.set({ left: nextLeft, top: nextTop });
    }
  }

  function updateZoomReadout() {
    if (!zoomReadout) return;
    zoomReadout.textContent = Math.round(zoomLevel * 100) + "%";
  }

  function clampViewport() {
    var vpt = canvas.viewportTransform;
    if (!vpt || vpt.length < 6) return;
    var zoom = vpt[0] || 1;
    var scaledW = canvasSize.w * zoom;
    var scaledH = canvasSize.h * zoom;
    if (zoom <= 1) {
      vpt[4] = (canvasSize.w - scaledW) / 2;
      vpt[5] = (canvasSize.h - scaledH) / 2;
    } else {
      var minX = canvasSize.w - scaledW;
      var minY = canvasSize.h - scaledH;
      if (vpt[4] < minX) vpt[4] = minX;
      if (vpt[4] > 0) vpt[4] = 0;
      if (vpt[5] < minY) vpt[5] = minY;
      if (vpt[5] > 0) vpt[5] = 0;
    }
    canvas.setViewportTransform(vpt);
  }

  function applyZoom(next) {
    var target = Math.max(0.4, Math.min(2.5, next));
    var center = new fabric.Point(canvasSize.w / 2, canvasSize.h / 2);
    canvas.zoomToPoint(center, target);
    zoomLevel = target;
    clampViewport();
    canvas.requestRenderAll();
    updateZoomReadout();
  }

  function fitToScreen() {
    canvas.setViewportTransform([1, 0, 0, 1, 0, 0]);
    zoomLevel = 1;
    clampViewport();
    canvas.requestRenderAll();
    updateZoomReadout();
    centerGuideInViewport();
  }

  function centerGuideInViewport() {
    var guide = getGuideBounds();
    var zoom = canvas.getZoom ? canvas.getZoom() : 1;
    if (zoom > 1.001) {
      var vpt = canvas.viewportTransform || [zoom, 0, 0, zoom, 0, 0];
      vpt[4] = (canvasSize.w / 2) - ((guide.left + (guide.width / 2)) * zoom);
      vpt[5] = (canvasSize.h / 2) - ((guide.top + (guide.height / 2)) * zoom);
      canvas.setViewportTransform(vpt);
      clampViewport();
      canvas.requestRenderAll();
    }
    if (!canvasWrap) return;
    var targetLeft = (guide.left + (guide.width / 2)) - (canvasWrap.clientWidth / 2);
    var targetTop = (guide.top + (guide.height / 2)) - (canvasWrap.clientHeight / 2);
    canvasWrap.scrollLeft = Math.max(0, Math.round(targetLeft));
    canvasWrap.scrollTop = Math.max(0, Math.round(targetTop));
  }

  function finishPan() {
    if (!isPanDragging) return;
    isPanDragging = false;
    if (canvasWrap) {
      canvasWrap.classList.remove("panning");
    }
    canvas.defaultCursor = "default";
    canvas.skipTargetFind = false;
    canvas.selection = true;
    panMode = "scroll";
  }

  function normalizeObjectScale(obj) {
    if (!obj || obj.type !== "textbox") return;
    var sx = obj.scaleX || 1;
    var sy = obj.scaleY || 1;
    if (sx !== 1) {
      obj.set({ width: obj.width * sx, scaleX: 1 });
    }
    if (sy !== 1) {
      obj.set({ fontSize: obj.fontSize * sy, scaleY: 1 });
    }
    updateTextBackground(obj);
  }

  var fontScale = 1.0;

  function applyTextStyles(obj) {
    if (!obj) return;
    var colorValue = (colorInput && colorInput.value) ? colorInput.value : "#ffffff";
    obj.set({
      fontFamily: fontSelect.value,
      fill: colorValue,
      textAlign: alignSelect.value,
    });
  }

  function syncFontSizeControls(px) {
    if (!px) return;
    if (fontSizeSelect) {
      var val = String(px);
      var found = false;
      for (var i = 0; i < fontSizeSelect.options.length; i++) {
        if (fontSizeSelect.options[i].value === val) {
          found = true;
          break;
        }
      }
      fontSizeSelect.value = found ? val : "";
    }
    if (fontSizeCustom) fontSizeCustom.value = String(px);
  }

  function syncControlsFromSelection(obj) {
    if (!obj) return;
    if (fontSelect && obj.fontFamily) fontSelect.value = obj.fontFamily;
    if (colorInput && obj.fill) colorInput.value = obj.fill;
    if (colorPicker && obj.fill) colorPicker.value = obj.fill;
    if (colorSwatch && obj.fill) colorSwatch.style.background = obj.fill;
    if (alignSelect && obj.textAlign) alignSelect.value = obj.textAlign;
    syncFontSizeControls(Math.round(obj.fontSize || 12));
    syncTextBgControls(obj);
  }

  function applyStyleToSelection() {
    var obj = getActiveText();
    if (!obj) return;
    applyTextStyles(obj);
    updateTextBackground(obj);
    canvas.renderAll();
    saveState();
  }

  function createText(text, box, opts) {
    var base = getGuideBounds();
    var fontPx = Math.max(16, box.h * base.height * 0.6);
    if (opts && opts.fontSizePx) {
      fontPx = Math.max(10, opts.fontSizePx);
    }
    var obj = new fabric.Textbox(text || "", {
      left: base.left + box.x * base.width,
      top: base.top + box.y * base.height,
      width: box.w * base.width,
      fontSize: fontPx,
      fill: (opts && opts.fill) || colorInput.value,
      fontFamily: (opts && opts.fontFamily) || fontSelect.value,
      textAlign: (opts && opts.align) || alignSelect.value,
      editable: true,
      lockRotation: true,
      borderColor: "#8fe4c7",
      cornerColor: "#8fe4c7",
      cornerStyle: "circle",
      transparentCorners: false,
    });
    var bgSettings = getTextBgSettings();
    obj.pg_bg_color = bgSettings.color;
    obj.pg_bg_opacity = bgSettings.opacity;
    obj.pg_bg_radius = bgSettings.radius;
    obj.pg_bg_radius_base_width = base.width;
    ensureObjectId(obj);
    canvas.add(obj);
    updateTextBackground(obj);
    return obj;
  }

  function resetTextBoxes(state) {
    canvas.getObjects().forEach(function (obj) {
      if (obj && (obj.type === "textbox" || obj.pg_is_text_bg)) canvas.remove(obj);
    });
    var defaults = [{ text: "", box: defaultTextBox }];
    var layers = (state && state.layers && state.layers.length) ? state.layers : defaults;
    layers.forEach(function (layer) {
      var box = layer.box || { x: 0.08, y: 0.62, w: 0.80, h: 0.14 };
      var base = getGuideBounds();
      var opts = {
        fontFamily: layer.font_family || fontSelect.value,
        fill: layer.color || colorInput.value,
        align: layer.align || alignSelect.value,
        fontSizePx: (layer.font_px && layer.font_base_width)
          ? (layer.font_px * (base.width / layer.font_base_width))
          : (layer.font_size_box_norm
            ? layer.font_size_box_norm * (box.h * base.height)
            : (layer.font_size_norm ? layer.font_size_norm * base.width : null)),
      };
      var obj = createText(layer.text || "", box, opts);
      if (obj && layer.bg_color) {
        obj.pg_bg_color = layer.bg_color;
        obj.pg_bg_opacity = layer.bg_opacity == null ? 0 : layer.bg_opacity;
        obj.pg_bg_radius = layer.bg_radius_px == null ? 0 : layer.bg_radius_px;
        obj.pg_bg_radius_base_width = layer.bg_radius_base_width || base.width;
        obj.pg_bg_pad = layer.bg_padding_px == null ? null : layer.bg_padding_px;
        obj.pg_bg_pad_base_width = layer.bg_padding_base_width || base.width;
        updateTextBackground(obj);
      }
    });
    var objs = getTextObjects();
    if (objs.length) canvas.setActiveObject(objs[0]);
    canvas.renderAll();
  }

  function addTextBox(text, box, opts) {
    var offset = (opts && typeof opts.offsetPx === "number") ? opts.offsetPx : (getTextObjects().length * 10);
    var useBox = box || defaultTextBox;
    var obj = createText(text || "", useBox, opts);
    obj.set({ left: obj.left + offset, top: obj.top + offset });
    canvas.setActiveObject(obj);
    syncControlsFromSelection(obj);
    canvas.renderAll();
    saveState();
    snapshotNow();
    return obj;
  }

  function restoreElements(state) {
    getElementObjects().forEach(function (obj) {
      canvas.remove(obj);
    });
    if (!state || !state.elements || !state.elements.length) {
      return;
    }
    var base = getGuideBounds();
    state.elements.forEach(function (el) {
      if (!el || !el.src) return;
      var box = normalizeBox(el.box);
      fabric.Image.fromURL(el.src, function (img) {
        var left = el.left || 0;
        var top = el.top || 0;
        var scaleX = el.scaleX || 1;
        var scaleY = el.scaleY || 1;
        if (box && base && base.width && base.height) {
          var bw = box.w * base.width;
          var bh = box.h * base.height;
          var cx = base.left + (box.x + box.w / 2) * base.width;
          var cy = base.top + (box.y + box.h / 2) * base.height;
          var ratio = img.width / Math.max(1, img.height);
          var targetW = Math.max(1, bw);
          var targetH = Math.max(1, targetW / ratio);
          scaleX = targetW / img.width;
          scaleY = targetH / img.height;
          left = cx - (targetW / 2);
          top = cy - (targetH / 2);
        }
        img.set({
          left: left,
          top: top,
          scaleX: scaleX,
          scaleY: scaleY,
          opacity: el.opacity == null ? 1 : el.opacity,
          cornerColor: "#8fe4c7",
          borderColor: "#8fe4c7",
          transparentCorners: false,
        });
        img.pg_asset_id = el.asset_id || el.pg_asset_id || "";
        img.pg_src = el.src;
        img.pg_id = el.pg_id || null;
        ensureObjectId(img);
        canvas.add(img);
        canvas.renderAll();
        updateLayerPanel();
      }, { crossOrigin: "anonymous" });
    });
  }

  function insertAssetFromUrl(url, assetId) {
    if (!url) return;
    var base = getGuideBounds();
    fabric.Image.fromURL(url, function (img) {
      var maxW = base.width * 0.25;
      var maxH = base.height * 0.25;
      var scale = Math.min(1, maxW / img.width, maxH / img.height);
      var left = base.left + base.width * 0.08;
      var top = base.top + base.height * 0.08;
      img.set({
        left: left,
        top: top,
        scaleX: scale,
        scaleY: scale,
        cornerColor: "#8fe4c7",
        borderColor: "#8fe4c7",
        transparentCorners: false,
      });
      img.pg_asset_id = assetId || "";
      img.pg_src = url;
      ensureObjectId(img);
      canvas.add(img);
      syncCanvasOrder();
      canvas.setActiveObject(img);
      canvas.renderAll();
      saveState();
      snapshotNow();
    }, { crossOrigin: "anonymous" });
  }

  function addShape(type) {
    var base = getGuideBounds();
    var color = (shapeHex && shapeHex.value) || (shapeColor && shapeColor.value) || "#ffffff";
    var opacity = shapeOpacity ? (parseFloat(shapeOpacity.value || "100") / 100) : 1;
    var width = Math.max(40, base.width * 0.25);
    var height = Math.max(40, base.height * 0.18);
    var left = base.left + base.width * 0.1;
    var top = base.top + base.height * 0.1;
    var obj = null;
    if (type === "square") {
      var size = Math.min(width, height);
      obj = new fabric.Rect({ width: size, height: size, left: left, top: top });
    } else if (type === "circle") {
      var radius = Math.min(width, height) / 2;
      obj = new fabric.Circle({ radius: radius, left: left, top: top });
    } else if (type === "triangle") {
      obj = new fabric.Triangle({ width: width, height: height, left: left, top: top });
    } else if (type === "star") {
      var points = [];
      var spikes = 5;
      var size = Math.min(width, height);
      var outer = size / 2;
      var inner = outer * 0.5;
      var cx = outer;
      var cy = outer;
      for (var i = 0; i < spikes * 2; i++) {
        var ang = (Math.PI / spikes) * i - Math.PI / 2;
        var r = (i % 2 === 0) ? outer : inner;
        points.push({ x: cx + Math.cos(ang) * r, y: cy + Math.sin(ang) * r });
      }
      obj = new fabric.Polygon(points, { left: left, top: top });
    } else {
      obj = new fabric.Rect({ width: width, height: height, left: left, top: top });
    }
    if (!obj) return;
    obj.set({
      fill: color,
      opacity: opacity,
      cornerColor: "#8fe4c7",
      borderColor: "#8fe4c7",
      transparentCorners: false,
    });
    obj.pg_is_shape = true;
    obj.pg_shape_type = type;
    obj.pg_shape_color = color;
    obj.pg_shape_opacity = opacity;
    ensureObjectId(obj);
    canvas.add(obj);
    syncCanvasOrder();
    canvas.setActiveObject(obj);
    canvas.renderAll();
    saveState();
    snapshotNow();
    updateLayerPanel();
  }

  function updateGuideRect(bounds) {
    if (!bounds) return;
    if (!guideRect) {
      guideRect = new fabric.Rect({
        left: bounds.left,
        top: bounds.top,
        width: bounds.width,
        height: bounds.height,
        fill: "rgba(0,0,0,0)",
        stroke: "#8fe4c7",
        strokeWidth: 2,
        strokeDashArray: [8, 6],
        selectable: false,
        evented: false,
        hoverCursor: "default",
        excludeFromExport: true,
      });
      guideRect.pg_is_guide = true;
      canvas.add(guideRect);
    } else {
      guideRect.set({
        left: bounds.left,
        top: bounds.top,
        width: bounds.width,
        height: bounds.height,
      });
    }
    updateDeadzoneOverlay(bounds);
    syncCanvasOrder();
  }

  function snapshotNow() {
    if (historyLock) return;
    var json = canvas.toDatalessJSON([
      "pg_asset_id",
      "pg_src",
      "pg_id",
      "pg_is_background",
      "pg_kv_id",
      "pg_is_text_bg",
      "pg_bg_for",
      "pg_is_guide",
      "pg_is_deadzone",
      "pg_is_board_edge",
      "pg_is_shape",
      "pg_shape_type",
      "pg_shape_color",
      "pg_shape_opacity",
    ]);
    if (json && Array.isArray(json.objects)) {
      json.objects = json.objects.filter(function (obj) {
        return !(obj && (obj.pg_is_guide || obj.pg_is_deadzone || obj.pg_is_board_edge));
      });
    }
    var serialized = "";
    try {
      serialized = JSON.stringify(json);
    } catch (e) {
      return;
    }
    if (serialized === lastSnapshot) return;
    lastSnapshot = serialized;
    if (historyIndex < history.length - 1) {
      history = history.slice(0, historyIndex + 1);
    }
    history.push(json);
    if (history.length > historyLimit) {
      history.shift();
    }
    historyIndex = history.length - 1;
  }

  function queueSnapshot() {
    if (historyLock) return;
    if (historyTimer) window.clearTimeout(historyTimer);
    historyTimer = window.setTimeout(snapshotNow, 250);
  }

  function restoreHistory(index) {
    if (index < 0 || index >= history.length) return;
    historyLock = true;
    canvas.loadFromJSON(history[index], function () {
      bgObj = null;
      canvas.getObjects().forEach(function (obj) {
        if (obj && obj.pg_is_background) {
          bgObj = obj;
          obj.set({
            selectable: true,
            evented: true,
            hasControls: false,
            lockScalingX: true,
            lockScalingY: true,
            lockRotation: true,
            hoverCursor: "move",
          });
          currentOffset = { x: obj.left || 0, y: obj.top || 0 };
          imageSize = {
            w: Math.round(obj.getScaledWidth ? obj.getScaledWidth() : obj.width || imageSize.w),
            h: Math.round(obj.getScaledHeight ? obj.getScaledHeight() : obj.height || imageSize.h),
          };
        }
      });
      updateGuideRect(getGuideBounds());
      syncCanvasOrder();
      clampViewport();
      canvas.renderAll();
      historyLock = false;
      saveState();
      updateLayerPanel();
    });
  }

  function undo() {
    if (historyIndex <= 0) return;
    historyIndex -= 1;
    restoreHistory(historyIndex);
  }

  function applyGuide(state, opts) {
    var ratio = parseRatio(guideRatio) || { w: 1, h: 1 };
    var guideW = imageSize.w;
    var guideH = Math.round(guideW * ratio.h / ratio.w);
    var pad = Math.round(Math.max(40, Math.min(200, guideW * 0.12)));
    var canvasW = Math.max(imageSize.w, guideW) + pad * 2;
    if (canvasWrap) {
      var stageChromeX = 22;
      if (stageEl && window.getComputedStyle) {
        var st = window.getComputedStyle(stageEl);
        var pL = parseFloat(st.paddingLeft || "0") || 0;
        var pR = parseFloat(st.paddingRight || "0") || 0;
        var bL = parseFloat(st.borderLeftWidth || "0") || 0;
        var bR = parseFloat(st.borderRightWidth || "0") || 0;
        stageChromeX = pL + pR + bL + bR;
      }
      var viewportMinW = Math.max(320, Math.floor(canvasWrap.clientWidth - stageChromeX));
      canvasW = Math.max(canvasW, viewportMinW);
    }
    var canvasH = Math.max(imageSize.h, guideH) + pad * 2;
    var nextOffset = {
      x: Math.round((canvasW - imageSize.w) / 2),
      y: Math.round((canvasH - imageSize.h) / 2),
    };
    var nextGuide = {
      left: Math.round((canvasW - guideW) / 2),
      top: Math.round((canvasH - guideH) / 2),
      width: guideW,
      height: guideH,
    };
    var imageBox = normalizeBox(state && state.image_box ? state.image_box : null);
    if (imageBox) {
      nextOffset.x = Math.round(nextGuide.left + imageBox.x * nextGuide.width);
      nextOffset.y = Math.round(nextGuide.top + imageBox.y * nextGuide.height);
    }
    guideBounds = nextGuide;

    canvas.setWidth(canvasW);
    canvas.setHeight(canvasH);
    if (canvas.wrapperEl) {
      canvas.wrapperEl.style.width = canvasW + "px";
      canvas.wrapperEl.style.height = canvasH + "px";
    }
    if (canvas.lowerCanvasEl) {
      canvas.lowerCanvasEl.style.width = canvasW + "px";
      canvas.lowerCanvasEl.style.height = canvasH + "px";
    }
    if (canvas.upperCanvasEl) {
      canvas.upperCanvasEl.style.width = canvasW + "px";
      canvas.upperCanvasEl.style.height = canvasH + "px";
    }
    canvasSize = { w: canvasW, h: canvasH };

    if (stageEl) {
      stageEl.style.width = canvasW + "px";
      stageEl.style.height = canvasH + "px";
    }

    if (opts && opts.preserveText) {
      var dx = nextOffset.x - currentOffset.x;
      var dy = nextOffset.y - currentOffset.y;
      if (dx || dy) {
        canvas.getObjects().forEach(function (obj) {
          if (!obj || obj === guideRect || obj.pg_is_background || obj.pg_is_deadzone || obj.pg_is_board_edge) return;
          obj.set({ left: obj.left + dx, top: obj.top + dy });
        });
      }
    } else {
      resetTextBoxes(state);
    }

    if (bgObj) {
      bgObj.set({ left: nextOffset.x, top: nextOffset.y });
      bgObj.setCoords();
    }

    updateGuideRect(nextGuide);
    clampViewport();
    currentOffset = nextOffset;
    canvas.renderAll();
    updateRatioLabel();
    centerGuideInViewport();
  }

  function reflowWorkspaceToViewport() {
    if (!bgObj) return;
    var state = { image_box: collectImageBox() };
    applyGuide(state, { preserveText: true });
    saveState();
  }

  function setBackground(kv, state) {
    if (!kv) return;
    log("Loading image: " + kv.url);
    fetch(kv.url, { method: "GET" })
      .then(function (res) {
        log("Fetch status: " + res.status + " " + res.statusText);
        log("Content-Type: " + (res.headers.get("content-type") || "unknown"));
      })
      .catch(function (err) {
        log("Fetch error: " + err);
      });

    fabric.Image.fromURL(kv.url, function (img) {
      if (!img) return;
      log("Image loaded: " + img.width + "x" + img.height);
      var maxDim = 900;
      var scale = Math.min(maxDim / img.width, maxDim / img.height, 1);
      var cw = Math.round(img.width * scale);
      var ch = Math.round(img.height * scale);
      imageSize = { w: cw, h: ch };
      applyGuide(state);
      if (bgObj) {
        canvas.remove(bgObj);
      }
      img.set({
        left: currentOffset.x,
        top: currentOffset.y,
        scaleX: scale,
        scaleY: scale,
        selectable: true,
        evented: true,
        hasControls: false,
        lockScalingX: true,
        lockScalingY: true,
        lockRotation: true,
        hoverCursor: "move",
      });
      img.pg_is_background = true;
      img.pg_kv_id = kv.id;
      ensureObjectId(img);
      bgObj = img;
      canvas.add(img);
      updateGuideRect(getGuideBounds());
      restoreElements(state);
      restoreShapes(state);
      syncCanvasOrder();
      label.textContent = kv.label || kv.id;
      log("Canvas size: " + canvas.getWidth() + "x" + canvas.getHeight());
      canvas.renderAll();
      centerGuideInViewport();
      snapshotNow();
    }, { crossOrigin: "anonymous" });
  }

  function updateAllStyles() {
    applyStyleToSelection();
  }

  function clamp01(v) {
    if (v < 0) return 0;
    if (v > 1) return 1;
    return v;
  }

  function normBox(obj) {
    if (!obj) return { x: 0, y: 0, w: 0, h: 0 };
    var rect = getObjectRect(obj);
    var base = getGuideBounds();
    return {
      x: clamp01((rect.left - base.left) / base.width),
      y: clamp01((rect.top - base.top) / base.height),
      w: clamp01(rect.width / base.width),
      h: clamp01(rect.height / base.height),
    };
  }

  function setHidden(id, value) {
    var el = document.getElementById(id);
    if (el) el.value = value;
  }

  function populateLayoutFormFields(prefix) {
    setHidden(prefix + "-kv", select.value);
    setHidden(prefix + "-font", fontSelect.value);
    setHidden(prefix + "-color", colorInput.value);
    setHidden(prefix + "-align", alignSelect.value);
    setHidden(prefix + "-text-layers", JSON.stringify(collectTextLayers()));
    setHidden(prefix + "-elements", JSON.stringify(collectElements()));
    setHidden(prefix + "-shapes", JSON.stringify(collectShapes()));
    setHidden(prefix + "-guide-ratio", guideRatio);
    var imageBox = collectImageBox();
    if (imageBox) {
      setHidden(prefix + "-image-box", JSON.stringify(imageBox));
    }
  }

  function collectTextLayers() {
    var layers = [];
    var objs = getTextObjects();
    var base = getGuideBounds();
    for (var i = 0; i < objs.length; i++) {
      var obj = objs[i];
      var rect = getObjectRect(obj);
      var wrapped = obj.text || "";
      if (obj._textLines && obj._textLines.length) {
        wrapped = obj._textLines.map(function (line) {
          return Array.isArray(line) ? line.join("") : line;
        }).join("\n");
      } else if (obj.textLines && obj.textLines.length) {
        wrapped = obj.textLines.map(function (line) {
          return Array.isArray(line) ? line.join("") : line;
        }).join("\n");
      }
      layers.push({
        text: obj.text || "",
        text_wrapped: wrapped,
        box: {
          x: (rect.left - base.left) / base.width,
          y: (rect.top - base.top) / base.height,
          w: rect.width / base.width,
          h: rect.height / base.height,
        },
        font_px: obj.fontSize || 12,
        font_base_width: base.width,
        font_size_norm: (obj.fontSize || 12) / base.width,
        font_size_box_norm: (obj.fontSize || 12) / Math.max(1, rect.height),
        font_family: obj.fontFamily || fontSelect.value,
        color: obj.fill || colorInput.value,
        align: obj.textAlign || alignSelect.value,
        bg_color: obj.pg_bg_color || null,
        bg_opacity: obj.pg_bg_opacity == null ? null : obj.pg_bg_opacity,
        bg_radius_px: obj.pg_bg_radius == null ? null : obj.pg_bg_radius,
        bg_radius_base_width: obj.pg_bg_radius_base_width || base.width,
        bg_padding_px: obj.pg_bg_pad == null ? null : obj.pg_bg_pad,
        bg_padding_base_width: obj.pg_bg_pad_base_width || base.width,
      });
    }
    return layers;
  }

  function collectElements() {
    var elements = [];
    var base = getGuideBounds();
    var objs = getElementObjects();
    for (var i = 0; i < objs.length; i++) {
      var obj = objs[i];
      var rect = getObjectRect(obj);
      elements.push({
        asset_id: obj.pg_asset_id || "",
        src: obj.pg_src || "",
        box: {
          x: (rect.left - base.left) / base.width,
          y: (rect.top - base.top) / base.height,
          w: rect.width / base.width,
          h: rect.height / base.height,
        },
        opacity: obj.opacity == null ? 1 : obj.opacity,
      });
    }
    return elements;
  }

  function collectShapes() {
    var shapes = [];
    var base = getGuideBounds();
    var objs = getShapeObjects();
    for (var i = 0; i < objs.length; i++) {
      var obj = objs[i];
      var rect = getObjectRect(obj);
      shapes.push({
        shape: obj.pg_shape_type || obj.type || "rect",
        box: {
          x: (rect.left - base.left) / base.width,
          y: (rect.top - base.top) / base.height,
          w: rect.width / base.width,
          h: rect.height / base.height,
        },
        color: obj.pg_shape_color || obj.fill || "#ffffff",
        opacity: obj.pg_shape_opacity == null ? 1 : obj.pg_shape_opacity,
      });
    }
    return shapes;
  }

  function restoreShapes(state) {
    getShapeObjects().forEach(function (obj) {
      canvas.remove(obj);
    });
    if (!state || !state.shapes || !state.shapes.length) return;
    var base = getGuideBounds();
    state.shapes.forEach(function (shape) {
      if (!shape) return;
      var box = normalizeBox(shape.box);
      if (!box) return;
      var color = shape.color || "#ffffff";
      var opacity = shape.opacity == null ? 1 : shape.opacity;
      var left = base.left + box.x * base.width;
      var top = base.top + box.y * base.height;
      var width = Math.max(1, box.w * base.width);
      var height = Math.max(1, box.h * base.height);
      var obj = null;
      if (shape.shape === "circle") {
        var radius = Math.min(width, height) / 2;
        obj = new fabric.Circle({ radius: radius, left: left, top: top });
      } else if (shape.shape === "triangle") {
        obj = new fabric.Triangle({ width: width, height: height, left: left, top: top });
      } else if (shape.shape === "star") {
        var points = [];
        var spikes = 5;
        var size = Math.min(width, height);
        var outer = size / 2;
        var inner = outer * 0.5;
        var cx = outer;
        var cy = outer;
        for (var i = 0; i < spikes * 2; i++) {
          var ang = (Math.PI / spikes) * i - Math.PI / 2;
          var r = (i % 2 === 0) ? outer : inner;
          points.push({ x: cx + Math.cos(ang) * r, y: cy + Math.sin(ang) * r });
        }
        obj = new fabric.Polygon(points, { left: left, top: top });
      } else {
        obj = new fabric.Rect({ width: width, height: height, left: left, top: top });
      }
      if (!obj) return;
      obj.set({
        fill: color,
        opacity: opacity,
        cornerColor: "#8fe4c7",
        borderColor: "#8fe4c7",
        transparentCorners: false,
      });
      obj.pg_is_shape = true;
      obj.pg_shape_type = shape.shape;
      obj.pg_shape_color = color;
      obj.pg_shape_opacity = opacity;
      ensureObjectId(obj);
      canvas.add(obj);
      canvas.renderAll();
      updateLayerPanel();
    });
  }

  function collectImageBox() {
    var base = getGuideBounds();
    if (!base || !base.width || !base.height) {
      return null;
    }
    var bg = getBackgroundObject();
    if (bg) {
      var rect = getObjectRect(bg);
      return {
        x: (rect.left - base.left) / base.width,
        y: (rect.top - base.top) / base.height,
        w: rect.width / base.width,
        h: rect.height / base.height,
      };
    }
    return {
      x: (currentOffset.x - base.left) / base.width,
      y: (currentOffset.y - base.top) / base.height,
      w: imageSize.w / base.width,
      h: imageSize.h / base.height,
    };
  }

  function collectAndSubmit() {
    if (!select.value) return;
    saveState();
    populateLayoutFormFields("form");
    setHidden("form-font-scale", fontScale.toFixed(3));
    var form = document.getElementById("preview-form");
    if (form) {
      showLoader();
      form.submit();
    }
  }

  function collectAndExportCurrent() {
    if (!select.value) return;
    saveState();
    populateLayoutFormFields("eform");
    var form = document.getElementById("export-form");
    if (form) {
      form.submit();
    }
  }

  function saveState() {
    var state = {
      kv_asset_id: select.value,
      font_family: fontSelect.value,
      text_color: colorInput ? colorInput.value : "#ffffff",
      text_align: alignSelect.value,
      font_scale: fontScale,
      guide_ratio: guideRatio,
      image_box: collectImageBox(),
      layers: collectTextLayers(),
      shapes: collectShapes(),
      elements: getElementObjects().map(function (obj) {
        return {
          pg_id: obj.pg_id || "",
          asset_id: obj.pg_asset_id || "",
          src: obj.pg_src || obj.src,
          left: obj.left || 0,
          top: obj.top || 0,
          scaleX: obj.scaleX || 1,
          scaleY: obj.scaleY || 1,
          opacity: obj.opacity == null ? 1 : obj.opacity,
        };
      }),
    };
    try {
      localStorage.setItem(stateKey, JSON.stringify(state));
    } catch (e) {
      // Ignore quota errors.
    }
  }

  function loadState() {
    try {
      var raw = localStorage.getItem(stateKey);
      if (!raw) return null;
      return JSON.parse(raw);
    } catch (e) {
      return null;
    }
  }

  function setupPreviewBulkSelect() {
    var selectAll = document.getElementById("preview-select-all");
    if (!selectAll) return;
    var boxes = Array.prototype.slice.call(document.querySelectorAll(".preview-select"));
    selectAll.addEventListener("change", function () {
      var next = !!selectAll.checked;
      boxes.forEach(function (box) {
        box.checked = next;
      });
    });
  }

  function loadPreviewDensity() {
    try {
      var mode = localStorage.getItem(previewDensityKey);
      if (mode === "comfy" || mode === "compact") return mode;
      return "compact";
    } catch (e) {
      return "compact";
    }
  }

  function savePreviewDensity(mode) {
    try {
      localStorage.setItem(previewDensityKey, mode);
    } catch (e) {
      // Ignore quota errors.
    }
  }

  function applyPreviewDensity(mode) {
    if (!document.body) return;
    var comfy = mode === "comfy";
    document.body.classList.toggle("preview-density-comfy", comfy);
    if (btnPreviewDensity) {
      btnPreviewDensity.textContent = comfy ? "Density: Comfy" : "Density: Compact";
    }
  }

  function updateLayerPanel() {
    if (!layerPanel) return;
    var objs = canvas.getObjects().filter(function (obj) {
      return obj && obj !== guideRect && !obj.pg_is_text_bg && !obj.pg_is_deadzone && !obj.pg_is_guide && !obj.pg_is_board_edge;
    });
    layerPanel.innerHTML = "";
    if (!objs.length) {
      layerPanel.innerHTML = "<div class=\"muted\">No layers yet.</div>";
      return;
    }
    // Top-most first.
    var active = canvas.getActiveObject();
    var activeId = active && active.pg_id;
    for (var i = objs.length - 1; i >= 0; i--) {
      var obj = objs[i];
      ensureObjectId(obj);
      var row = document.createElement("div");
      row.className = "layer-row";
      if (activeId && obj.pg_id === activeId) {
        row.classList.add("active");
      }
      row.dataset.objId = obj.pg_id;
      var label = document.createElement("div");
      label.className = "label";
      if (obj.pg_is_background) {
        label.textContent = "KV";
      } else if (obj.pg_is_shape) {
        label.textContent = "Shape";
      } else if (obj.type === "textbox") {
        label.textContent = "Text";
      } else if (obj.type === "image") {
        label.textContent = obj.pg_asset_id ? ("Asset " + obj.pg_asset_id.slice(0, 6)) : "Asset";
      } else {
        label.textContent = obj.type || "Layer";
      }
      var controls = document.createElement("div");
      controls.className = "layer-controls";
      var up = document.createElement("button");
      up.className = "btn btn-icon";
      up.type = "button";
      up.title = "Bring forward";
      up.textContent = "↑";
      var down = document.createElement("button");
      down.className = "btn btn-icon";
      down.type = "button";
      down.title = "Send back";
      down.textContent = "↓";
      controls.appendChild(up);
      controls.appendChild(down);

      row.appendChild(label);
      row.appendChild(controls);

      row.addEventListener("click", function (e) {
        if (e.target && e.target.tagName === "BUTTON") return;
        var id = this.dataset.objId;
        var target = canvas.getObjects().find(function (o) {
          return o.pg_id === id;
        });
        if (target) {
          canvas.setActiveObject(target);
          canvas.renderAll();
          syncControlsFromSelection(target);
          updateLayerPanel();
        }
      });
      up.addEventListener("click", function (e) {
        e.stopPropagation();
        var id = this.parentNode.parentNode.dataset.objId;
        var target = canvas.getObjects().find(function (o) {
          return o.pg_id === id;
        });
        if (target) {
          canvas.bringForward(target);
          syncCanvasOrder();
          canvas.renderAll();
          saveState();
          updateLayerPanel();
        }
      });
      down.addEventListener("click", function (e) {
        e.stopPropagation();
        var id = this.parentNode.parentNode.dataset.objId;
        var target = canvas.getObjects().find(function (o) {
          return o.pg_id === id;
        });
        if (target) {
          canvas.sendBackwards(target);
          syncCanvasOrder();
          canvas.renderAll();
          saveState();
          updateLayerPanel();
        }
      });

      if (obj.pg_is_background) {
        up.disabled = true;
        down.disabled = true;
        up.style.opacity = "0.35";
        down.style.opacity = "0.35";
      }

      layerPanel.appendChild(row);
    }
  }

  function isEditableTarget(target) {
    if (!target) return false;
    var tag = (target.tagName || "").toLowerCase();
    return tag === "input" || tag === "textarea" || target.isContentEditable;
  }

  canvas.on("object:modified", function (e) {
    clampObjectToWorkspace(e.target);
    normalizeObjectScale(e.target);
    if (e.target && e.target.pg_is_background) {
      currentOffset = { x: e.target.left || 0, y: e.target.top || 0 };
    }
    syncCanvasOrder();
    if (e.target && e.target.type === "textbox") {
      syncControlsFromSelection(e.target);
    }
    canvas.renderAll();
    saveState();
    snapshotNow();
    updateLayerPanel();
  });
  canvas.on("object:moving", function (e) {
    clampObjectToWorkspace(e.target);
    if (e.target && e.target.type === "textbox") {
      updateTextBackground(e.target);
    }
  });
  canvas.on("text:changed", function (e) {
    if (e.target && e.target.type === "textbox") {
      updateTextBackground(e.target);
    }
    saveState();
    queueSnapshot();
  });
  canvas.on("object:added", function (e) {
    if (e.target && e.target !== guideRect && !e.target.pg_is_deadzone && !e.target.pg_is_guide && !e.target.pg_is_board_edge) {
      ensureObjectId(e.target);
      updateLayerPanel();
    }
  });
  canvas.on("object:removed", function (e) {
    if (e.target && e.target !== guideRect && !e.target.pg_is_deadzone && !e.target.pg_is_guide && !e.target.pg_is_board_edge) {
      if (e.target.type === "textbox") {
        removeTextBackground(e.target);
      }
      updateLayerPanel();
    }
  });
  canvas.on("selection:created", function (e) {
    var obj = (e.selected && e.selected[0]) || canvas.getActiveObject();
    if (obj && obj.type === "textbox") {
      syncControlsFromSelection(obj);
    } else if (obj && obj.pg_is_shape) {
      syncShapeControls(obj);
    }
  });
  canvas.on("selection:updated", function (e) {
    var obj = (e.selected && e.selected[0]) || canvas.getActiveObject();
    if (obj && obj.type === "textbox") {
      syncControlsFromSelection(obj);
    } else if (obj && obj.pg_is_shape) {
      syncShapeControls(obj);
    }
  });
  canvas.on("selection:cleared", function () {
    if (!layerPanel) return;
    var rows = layerPanel.querySelectorAll(".layer-row");
    for (var i = 0; i < rows.length; i++) {
      rows[i].classList.remove("active");
    }
  });

  select.addEventListener("change", function () {
    var kv = kvMap[select.value];
    setBackground(kv);
  });

  fontSelect.addEventListener("change", updateAllStyles);
  if (colorInput) {
    colorInput.addEventListener("change", function () {
      if (colorPicker) colorPicker.value = colorInput.value;
      if (colorSwatch) colorSwatch.style.background = colorInput.value;
      applyStyleToSelection();
    });
  }
  if (colorPicker) {
    colorPicker.addEventListener("input", function () {
      if (colorInput) colorInput.value = colorPicker.value;
      if (colorSwatch) colorSwatch.style.background = colorPicker.value;
      applyStyleToSelection();
    });
  }
  if (textBgHex) {
    textBgHex.addEventListener("change", function () {
      if (textBgColor) textBgColor.value = textBgHex.value;
      applyTextBackgroundToSelection();
    });
  }
  if (textBgColor) {
    textBgColor.addEventListener("input", function () {
      if (textBgHex) textBgHex.value = textBgColor.value;
      applyTextBackgroundToSelection();
    });
  }
  if (textBgOpacity) {
    textBgOpacity.addEventListener("input", function () {
      applyTextBackgroundToSelection();
    });
  }
  if (textBgRadius) {
    textBgRadius.addEventListener("change", function () {
      applyTextBackgroundToSelection();
    });
  }
  if (shapeHex) {
    shapeHex.addEventListener("change", function () {
      if (shapeColor) shapeColor.value = shapeHex.value;
      var obj = getActiveObject();
      if (obj && obj.pg_is_shape) {
        obj.pg_shape_color = shapeHex.value;
        obj.set({ fill: shapeHex.value });
        canvas.renderAll();
        saveState();
      }
    });
  }
  if (shapeColor) {
    shapeColor.addEventListener("input", function () {
      if (shapeHex) shapeHex.value = shapeColor.value;
      var obj = getActiveObject();
      if (obj && obj.pg_is_shape) {
        obj.pg_shape_color = shapeColor.value;
        obj.set({ fill: shapeColor.value });
        canvas.renderAll();
        saveState();
      }
    });
  }
  if (shapeOpacity) {
    shapeOpacity.addEventListener("input", function () {
      var obj = getActiveObject();
      if (obj && obj.pg_is_shape) {
        obj.pg_shape_opacity = parseFloat(shapeOpacity.value || "100") / 100;
        obj.set({ opacity: obj.pg_shape_opacity });
        canvas.renderAll();
        saveState();
      }
    });
  }
  if (shapeButtons && shapeButtons.length) {
    for (var i = 0; i < shapeButtons.length; i++) {
      shapeButtons[i].addEventListener("click", function (e) {
        var t = e.currentTarget.getAttribute("data-shape");
        addShape(t || "rect");
      });
    }
  }
  alignSelect.addEventListener("change", updateAllStyles);
  function applyFontSizeValue(next) {
    var obj = getActiveText();
    var size = parseInt(next || "12", 10) || 12;
    if (fontSizeSelect) fontSizeSelect.value = String(size);
    if (fontSizeCustom) fontSizeCustom.value = String(size);
    if (!obj) return;
    obj.set({ fontSize: size });
    updateTextBackground(obj);
    canvas.renderAll();
    saveState();
  }
  if (fontSizeSelect) {
    fontSizeSelect.addEventListener("change", function () {
      applyFontSizeValue(fontSizeSelect.value);
    });
  }
  if (fontSizeCustom) {
    fontSizeCustom.addEventListener("change", function () {
      applyFontSizeValue(fontSizeCustom.value);
    });
  }
  if (guideSelect) {
    guideSelect.addEventListener("change", function () {
      guideRatio = guideSelect.value || "1:1";
      applyGuide({ image_box: collectImageBox() }, { preserveText: true });
      saveState();
    });
  }

  document.addEventListener("keydown", function (e) {
    if (isEditableTarget(e.target)) return;
    if (e.code === "Space" || e.key === " ") {
      if (!isSpaceDown) {
        isSpaceDown = true;
        if (canvasWrap) canvasWrap.classList.add("panning");
      }
      e.preventDefault();
      return;
    }
    if ((e.metaKey || e.ctrlKey) && !e.shiftKey && (e.key === "z" || e.key === "Z")) {
      undo();
      e.preventDefault();
      return;
    }
    var obj = getActiveObject();
    if (!obj) return;
    if (obj.isEditing) return;
    var step = e.shiftKey ? 10 : 1;
    var handled = false;
    if (e.key === "ArrowLeft") {
      obj.set({ left: obj.left - step });
      handled = true;
    } else if (e.key === "ArrowRight") {
      obj.set({ left: obj.left + step });
      handled = true;
    } else if (e.key === "ArrowUp") {
      obj.set({ top: obj.top - step });
      handled = true;
    } else if (e.key === "ArrowDown") {
      obj.set({ top: obj.top + step });
      handled = true;
    } else if (e.key === "Delete" || e.key === "Backspace") {
      if (obj.pg_is_background) {
        return;
      }
      if (obj.type === "textbox") {
        removeTextBackground(obj);
      }
      canvas.remove(obj);
      canvas.discardActiveObject();
      handled = true;
    }
    if (handled) {
      clampObjectToWorkspace(obj);
      obj.setCoords();
      canvas.renderAll();
      if (obj.pg_is_background) {
        currentOffset = { x: obj.left || 0, y: obj.top || 0 };
      }
      syncCanvasOrder();
      saveState();
      snapshotNow();
      e.preventDefault();
    }
  });
  document.addEventListener("keyup", function (e) {
    if (e.code === "Space" || e.key === " ") {
      isSpaceDown = false;
      finishPan();
      if (canvasWrap) canvasWrap.classList.remove("panning");
      e.preventDefault();
    }
  });
  if (canvasWrap) {
    canvasWrap.addEventListener("mousedown", function (e) {
      if (!isSpaceDown) return;
      isPanDragging = true;
      panStartX = e.clientX;
      panStartY = e.clientY;
      panStartLeft = canvasWrap.scrollLeft;
      panStartTop = canvasWrap.scrollTop;
      panMode = zoomLevel > 1.001 ? "viewport" : "scroll";
      var vpt = canvas.viewportTransform || [zoomLevel, 0, 0, zoomLevel, 0, 0];
      panStartViewportX = vpt[4] || 0;
      panStartViewportY = vpt[5] || 0;
      canvas.defaultCursor = "grabbing";
      canvas.skipTargetFind = true;
      canvas.selection = false;
      e.preventDefault();
    });
  }
  window.addEventListener("mousemove", function (e) {
    if (!isPanDragging || !canvasWrap) return;
    var dx = e.clientX - panStartX;
    var dy = e.clientY - panStartY;
    if (panMode === "viewport") {
      var vpt = canvas.viewportTransform || [zoomLevel, 0, 0, zoomLevel, 0, 0];
      vpt[4] = panStartViewportX + dx;
      vpt[5] = panStartViewportY + dy;
      canvas.setViewportTransform(vpt);
      clampViewport();
      canvas.requestRenderAll();
    } else {
      canvasWrap.scrollLeft = panStartLeft - dx;
      canvasWrap.scrollTop = panStartTop - dy;
    }
  });
  window.addEventListener("mouseup", function () {
    finishPan();
  });
  window.addEventListener("resize", function () {
    if (resizeTimer) window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(function () {
      reflowWorkspaceToViewport();
    }, 120);
  });
  if (btnCenterGuide) {
    btnCenterGuide.addEventListener("click", function () {
      centerGuideInViewport();
    });
  }
  var previewDensityMode = loadPreviewDensity();
  applyPreviewDensity(previewDensityMode);
  if (btnPreviewDensity) {
    btnPreviewDensity.addEventListener("click", function () {
      previewDensityMode = previewDensityMode === "compact" ? "comfy" : "compact";
      applyPreviewDensity(previewDensityMode);
      savePreviewDensity(previewDensityMode);
    });
  }
  if (btnZoomIn) {
    btnZoomIn.addEventListener("click", function () {
      applyZoom(zoomLevel + 0.1);
    });
  }
  if (btnZoomOut) {
    btnZoomOut.addEventListener("click", function () {
      applyZoom(zoomLevel - 0.1);
    });
  }
  if (btnZoomFit) {
    btnZoomFit.addEventListener("click", function () {
      fitToScreen();
    });
  }
  if (fontScaleInput) {
    fontScaleInput.addEventListener("input", function () {
      var next = parseFloat(fontScaleInput.value || "1") || 1;
      if (fontScaleValue) fontScaleValue.textContent = next.toFixed(2) + "x";
      var ratio = next / (fontScale || 1);
      fontScale = next;
      getTextObjects().forEach(function (obj) {
        if (!obj) return;
        obj.set({ fontSize: Math.max(10, (obj.fontSize || 12) * ratio) });
      });
      canvas.renderAll();
      saveState();
    });
  }
  btnPreview.addEventListener("click", collectAndSubmit);
  if (btnExportCurrent) {
    btnExportCurrent.addEventListener("click", collectAndExportCurrent);
  }
  if (btnUndo) {
    btnUndo.addEventListener("click", function () {
      undo();
    });
  }

  document.addEventListener("submit", function (e) {
    var form = e && e.target ? e.target : null;
    var submitter = e && e.submitter ? e.submitter : null;
    var action = "";
    if (submitter && submitter.formAction) {
      action = submitter.formAction;
    } else if (form && form.action) {
      action = form.action;
    }
    if (action && action.indexOf("/export") !== -1) {
      return;
    }
    showLoader();
  });
  if (assetUploadBtn && assetUploadFile) {
    assetUploadBtn.addEventListener("click", function () {
      assetUploadFile.click();
    });
    assetUploadFile.addEventListener("change", function () {
      if (!assetUploadName) return;
      var name = assetUploadFile.files && assetUploadFile.files.length ? assetUploadFile.files[0].name : "No file selected";
      assetUploadName.textContent = name;
    });
  }
  if (btnInsertText) {
    btnInsertText.addEventListener("click", function () {
      addTextBox("", defaultTextBox);
    });
  }
  if (assetInsertButtons && assetInsertButtons.length) {
    for (var a = 0; a < assetInsertButtons.length; a++) {
      assetInsertButtons[a].addEventListener("click", function (e) {
        var btn = e.currentTarget;
        insertAssetFromUrl(btn.dataset.assetUrl, btn.dataset.insertAsset);
      });
    }
  }
  if (btnDeleteText) {
    btnDeleteText.addEventListener("click", function () {
      var obj = getActiveObject();
      if (!obj) return;
      if (obj.pg_is_background) return;
      if (obj.type === "textbox") {
        removeTextBackground(obj);
      }
      canvas.remove(obj);
      canvas.discardActiveObject();
      canvas.renderAll();
      saveState();
      snapshotNow();
    });
  }
  if (btnDuplicateText) {
    btnDuplicateText.addEventListener("click", function () {
      var obj = getActiveObject();
      if (!obj) return;
      obj.clone(function (cloned) {
        cloned.set({ left: obj.left + 12, top: obj.top + 12 });
        if (cloned.type === "textbox") {
          cloned.pg_bg_color = obj.pg_bg_color;
          cloned.pg_bg_opacity = obj.pg_bg_opacity;
          cloned.pg_bg_radius = obj.pg_bg_radius;
          cloned.pg_bg_radius_base_width = obj.pg_bg_radius_base_width;
        }
        canvas.add(cloned);
        syncCanvasOrder();
        canvas.setActiveObject(cloned);
        if (cloned.type === "textbox") {
          updateTextBackground(cloned);
        }
        canvas.renderAll();
        saveState();
        snapshotNow();
      });
    });
  }
  if (btnBringForward) {
    btnBringForward.addEventListener("click", function () {
      var obj = getActiveObject();
      if (!obj) return;
      canvas.bringForward(obj);
      syncCanvasOrder();
      canvas.renderAll();
      saveState();
      snapshotNow();
    });
  }
  if (btnSendBack) {
    btnSendBack.addEventListener("click", function () {
      var obj = getActiveObject();
      if (!obj) return;
      canvas.sendBackwards(obj);
      syncCanvasOrder();
      canvas.renderAll();
      saveState();
      snapshotNow();
    });
  }

  function applyCopySet(h, s, c) {
    var texts = [h || "", s || "", c || ""];
    var objs = getTextObjects();
    for (var i = 0; i < texts.length; i++) {
      if (i < objs.length) {
        objs[i].set({ text: texts[i] });
      } else {
        addTextBox(texts[i], defaultCopyBoxes[i] || defaultTextBox, { offsetPx: 0 });
      }
    }
    objs = getTextObjects();
    objs.forEach(function (obj) {
      updateTextBackground(obj);
    });
    canvas.renderAll();
    saveState();
    snapshotNow();
  }
  for (var i = 0; i < copyButtons.length; i++) {
    copyButtons[i].addEventListener("click", function (e) {
      var btn = e.currentTarget;
      applyCopySet(btn.dataset.headline, btn.dataset.subhead, btn.dataset.cta);
    });
  }

  updateZoomReadout();

  var saved = loadState();
  if (layoutData && layoutData.kv_asset_id && kvMap[layoutData.kv_asset_id]) {
    select.value = layoutData.kv_asset_id;
    fontSelect.value = layoutData.font_family || fontSelect.value;
    if (layoutData.text_color) {
      if (colorInput) colorInput.value = layoutData.text_color;
      if (colorPicker) colorPicker.value = layoutData.text_color;
      if (colorSwatch) colorSwatch.style.background = layoutData.text_color;
    }
    alignSelect.value = layoutData.text_align || alignSelect.value;
    if (guideSelect && layoutData.guide_ratio) {
      guideSelect.value = layoutData.guide_ratio;
    }
    guideRatio = (guideSelect && guideSelect.value) || guideRatio;
    var layoutState = {
      image_box: normalizeBox(layoutData.image_box || null),
      layers: (layoutData.text_layers || []).map(function (layer) {
        if (!layer || !layer.box) return layer;
        var b = layer.box;
        return Object.assign({}, layer, {
          box: { x: b.x, y: b.y, w: b.w, h: b.h },
          text_wrapped: layer.text_wrapped || layer.text || "",
          font_px: layer.font_px || null,
          font_base_width: layer.font_base_width || null,
          font_size_box_norm: layer.font_size_box_norm || layer.font_size_norm || null,
        });
      }),
      shapes: (layoutData.shapes || []).map(function (shape) {
        if (!shape) return shape;
        return {
          shape: shape.shape || shape.type || "rect",
          box: normalizeBox(shape.box || null),
          color: shape.color || "#ffffff",
          opacity: shape.opacity == null ? 1 : shape.opacity,
        };
      }),
      elements: (layoutData.elements || []).map(function (el) {
        if (!el) return el;
        return {
          asset_id: el.asset_id,
          src: (el.asset_id ? ("/projects/" + projectId + "/assets/" + el.asset_id) : (el.src || "")),
          box: normalizeBox(el.box || null),
          opacity: el.opacity == null ? 1 : el.opacity,
        };
      }),
    };
    setBackground(kvMap[layoutData.kv_asset_id], layoutState);
  } else if (saved && saved.kv_asset_id && kvMap[saved.kv_asset_id]) {
    select.value = saved.kv_asset_id;
    fontSelect.value = saved.font_family || fontSelect.value;
    colorInput.value = saved.text_color || colorInput.value;
    if (colorPicker && saved.text_color) colorPicker.value = saved.text_color;
    if (colorSwatch && saved.text_color) colorSwatch.style.background = saved.text_color;
    alignSelect.value = saved.text_align || alignSelect.value;
    if (guideSelect && saved.guide_ratio) {
      guideSelect.value = saved.guide_ratio;
    }
    guideRatio = (guideSelect && guideSelect.value) || guideRatio;
    if (fontScaleInput && saved.font_scale) {
      fontScale = parseFloat(saved.font_scale) || fontScale;
      fontScaleInput.value = fontScale;
      if (fontScaleValue) fontScaleValue.textContent = fontScale.toFixed(2) + "x";
    }
    setBackground(kvMap[saved.kv_asset_id], saved);
  } else if (select.value) {
    guideRatio = (guideSelect && guideSelect.value) || guideRatio;
    setBackground(kvMap[select.value]);
  } else if (kvs.length) {
    select.value = kvs[0].id;
    guideRatio = (guideSelect && guideSelect.value) || guideRatio;
    setBackground(kvMap[select.value]);
  }
    setupPreviewBulkSelect();
    return true;
  }

  if (window.fabric && startEditor()) {
    return;
  }

  var sources = [
    "https://cdn.jsdelivr.net/npm/fabric@4.6.0/dist/fabric.min.js",
    "https://unpkg.com/fabric@4.6.0/dist/fabric.min.js",
    "https://cdnjs.cloudflare.com/ajax/libs/fabric.js/4.6.0/fabric.min.js",
  ];
  var idx = 0;

  function loadNext() {
    if (idx >= sources.length) {
      console.error("Failed to load Fabric.js");
      return;
    }
    var script = document.createElement("script");
    script.src = sources[idx];
    idx += 1;
    script.onload = function () {
      if (!startEditor()) {
        loadNext();
      }
    };
    script.onerror = function () {
      loadNext();
    };
    document.head.appendChild(script);
  }

  loadNext();
})();
