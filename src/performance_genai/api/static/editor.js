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

  var projectId = (document.body && document.body.dataset && document.body.dataset.projectId) || "default";
  var stateKey = "pg_editor_state_" + projectId;
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

  var select = document.getElementById("kv-select");
  var label = document.getElementById("kv-label");
  var bgImg = document.getElementById("kv-bg");
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

  var colorPicker = document.getElementById("color-picker");
  var colorInput = document.getElementById("color-input");
  var colorSwatch = document.getElementById("color-swatch");
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
      // Fabric wraps the canvas in a .canvas-container div. We want that wrapper
      // to overlay the background <img>, not take up extra vertical space below it.
      canvas.wrapperEl.style.position = "absolute";
      canvas.wrapperEl.style.left = "0px";
      canvas.wrapperEl.style.top = "0px";
      canvas.wrapperEl.style.zIndex = "2";
      canvas.wrapperEl.style.background = "transparent";
    }
    if (bgImg) {
      bgImg.style.position = "relative";
      bgImg.style.zIndex = "1";
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
  var currentOffset = { x: 0, y: 0 };
  var guideRatio = (guideSelect && guideSelect.value) || "1:1";
  var guideBounds = null;
  var guideRect = null;

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

  function getTextObjects() {
    return canvas.getObjects().filter(function (obj) {
      return obj && obj.type === "textbox";
    });
  }

  function getElementObjects() {
    return canvas.getObjects().filter(function (obj) {
      return obj && obj.type === "image" && obj.pg_asset_id;
    });
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

  function getGuideBounds() {
    if (guideBounds && guideBounds.width && guideBounds.height) return guideBounds;
    return { left: 0, top: 0, width: canvasSize.w, height: canvasSize.h };
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
  }

  function applyStyleToSelection() {
    var obj = getActiveText();
    if (!obj) return;
    applyTextStyles(obj);
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
    ensureObjectId(obj);
    canvas.add(obj);
    return obj;
  }

  function resetTextBoxes(state) {
    canvas.getObjects().forEach(function (obj) {
      if (obj && obj.type === "textbox") canvas.remove(obj);
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
        fontSizePx: layer.font_size_norm ? layer.font_size_norm * base.height : null,
      };
      createText(layer.text || "", box, opts);
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
    state.elements.forEach(function (el) {
      if (!el || !el.src) return;
      fabric.Image.fromURL(el.src, function (img) {
        img.set({
          left: el.left || 0,
          top: el.top || 0,
          scaleX: el.scaleX || 1,
          scaleY: el.scaleY || 1,
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
      canvas.setActiveObject(img);
      canvas.renderAll();
      saveState();
      snapshotNow();
    }, { crossOrigin: "anonymous" });
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
      canvas.add(guideRect);
    } else {
      guideRect.set({
        left: bounds.left,
        top: bounds.top,
        width: bounds.width,
        height: bounds.height,
      });
    }
    canvas.sendToBack(guideRect);
  }

  function snapshotNow() {
    if (historyLock) return;
    var json = canvas.toDatalessJSON(["pg_asset_id", "pg_src", "pg_id"]);
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
      if (guideRect) {
        canvas.add(guideRect);
        canvas.sendToBack(guideRect);
      }
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
    var canvasW = Math.max(imageSize.w, guideW);
    var canvasH = Math.max(imageSize.h, guideH);
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
    if (bgImg) {
      bgImg.style.position = "absolute";
      bgImg.style.left = nextOffset.x + "px";
      bgImg.style.top = nextOffset.y + "px";
      bgImg.style.width = imageSize.w + "px";
      bgImg.style.height = imageSize.h + "px";
    }

    if (opts && opts.preserveText) {
      var dx = nextOffset.x - currentOffset.x;
      var dy = nextOffset.y - currentOffset.y;
      if (dx || dy) {
        canvas.getObjects().forEach(function (obj) {
          if (!obj || obj === guideRect) return;
          obj.set({ left: obj.left + dx, top: obj.top + dy });
        });
      }
    } else {
      resetTextBoxes(state);
    }

    updateGuideRect(nextGuide);
    currentOffset = nextOffset;
    canvas.renderAll();
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

    var probe = new Image();
    probe.onload = function () {
      log("Image loaded: " + probe.width + "x" + probe.height);
      var maxDim = 900;
      var scale = Math.min(maxDim / probe.width, maxDim / probe.height, 1);
      var cw = Math.round(probe.width * scale);
      var ch = Math.round(probe.height * scale);
      if (bgImg) {
        bgImg.src = kv.url;
        bgImg.width = cw;
        bgImg.height = ch;
      }
      imageSize = { w: cw, h: ch };
      applyGuide(state);
      restoreElements(state);
      label.textContent = kv.label || kv.id;
      if (bgImg) {
        log("Image element size: " + bgImg.clientWidth + "x" + bgImg.clientHeight);
      }
      log("Canvas size: " + canvas.getWidth() + "x" + canvas.getHeight());
      snapshotNow();
    };
    probe.onerror = function () {
      log("Image onerror fired for " + kv.url);
      label.textContent = "Failed to load image";
    };
    probe.src = kv.url;
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
    var rect = obj.getBoundingRect(true);
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

  function collectTextLayers() {
    var layers = [];
    var objs = getTextObjects();
    var base = getGuideBounds();
    for (var i = 0; i < objs.length; i++) {
      var obj = objs[i];
      var rect = obj.getBoundingRect(true);
      layers.push({
        text: obj.text || "",
        box: {
          x: clamp01((rect.left - base.left) / base.width),
          y: clamp01((rect.top - base.top) / base.height),
          w: clamp01(rect.width / base.width),
          h: clamp01(rect.height / base.height),
        },
        font_size_norm: (obj.fontSize || 12) / base.height,
        font_family: obj.fontFamily || fontSelect.value,
        color: obj.fill || colorInput.value,
        align: obj.textAlign || alignSelect.value,
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
      var rect = obj.getBoundingRect(true);
      elements.push({
        asset_id: obj.pg_asset_id || "",
        src: obj.pg_src || "",
        box: {
          x: clamp01((rect.left - base.left) / base.width),
          y: clamp01((rect.top - base.top) / base.height),
          w: clamp01(rect.width / base.width),
          h: clamp01(rect.height / base.height),
        },
        opacity: obj.opacity == null ? 1 : obj.opacity,
      });
    }
    return elements;
  }

  function collectImageBox() {
    var base = getGuideBounds();
    if (!base || !base.width || !base.height) {
      return null;
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
    setHidden("form-kv", select.value);
    setHidden("form-font", fontSelect.value);
    setHidden("form-color", colorInput.value);
    setHidden("form-align", alignSelect.value);
    setHidden("form-font-scale", fontScale.toFixed(3));
    setHidden("form-text-layers", JSON.stringify(collectTextLayers()));
    setHidden("form-elements", JSON.stringify(collectElements()));
    var imageBox = collectImageBox();
    if (imageBox) {
      setHidden("form-image-box", JSON.stringify(imageBox));
    }
    var form = document.getElementById("preview-form");
    if (form) form.submit();
  }

  function saveState() {
    var state = {
      kv_asset_id: select.value,
      font_family: fontSelect.value,
      text_color: colorInput ? colorInput.value : "#ffffff",
      text_align: alignSelect.value,
      font_scale: fontScale,
      guide_ratio: guideRatio,
      layers: collectTextLayers(),
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

  function updateLayerPanel() {
    if (!layerPanel) return;
    var objs = canvas.getObjects().filter(function (obj) {
      return obj && obj !== guideRect;
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
      if (obj.type === "textbox") {
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
          if (guideRect) canvas.sendToBack(guideRect);
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
          if (guideRect) canvas.sendToBack(guideRect);
          canvas.renderAll();
          saveState();
          updateLayerPanel();
        }
      });

      layerPanel.appendChild(row);
    }
  }

  function isEditableTarget(target) {
    if (!target) return false;
    var tag = (target.tagName || "").toLowerCase();
    return tag === "input" || tag === "textarea" || target.isContentEditable;
  }

  canvas.on("object:modified", function (e) {
    normalizeObjectScale(e.target);
    if (e.target && e.target.type === "textbox") {
      syncControlsFromSelection(e.target);
    }
    canvas.renderAll();
    saveState();
    snapshotNow();
    updateLayerPanel();
  });
  canvas.on("text:changed", function (e) {
    saveState();
    queueSnapshot();
  });
  canvas.on("object:added", function (e) {
    if (e.target && e.target !== guideRect) {
      ensureObjectId(e.target);
      updateLayerPanel();
    }
  });
  canvas.on("object:removed", function (e) {
    if (e.target && e.target !== guideRect) {
      updateLayerPanel();
    }
  });
  canvas.on("selection:created", function (e) {
    var obj = (e.selected && e.selected[0]) || canvas.getActiveObject();
    if (obj && obj.type === "textbox") {
      syncControlsFromSelection(obj);
    }
  });
  canvas.on("selection:updated", function (e) {
    var obj = (e.selected && e.selected[0]) || canvas.getActiveObject();
    if (obj && obj.type === "textbox") {
      syncControlsFromSelection(obj);
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
  alignSelect.addEventListener("change", updateAllStyles);
  function applyFontSizeValue(next) {
    var obj = getActiveText();
    var size = parseInt(next || "12", 10) || 12;
    if (fontSizeSelect) fontSizeSelect.value = String(size);
    if (fontSizeCustom) fontSizeCustom.value = String(size);
    if (!obj) return;
    obj.set({ fontSize: size });
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
      applyGuide(null, { preserveText: true });
      saveState();
    });
  }

  document.addEventListener("keydown", function (e) {
    if (isEditableTarget(e.target)) return;
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
      canvas.remove(obj);
      canvas.discardActiveObject();
      handled = true;
    }
    if (handled) {
      obj.setCoords();
      canvas.renderAll();
      saveState();
      snapshotNow();
      e.preventDefault();
    }
  });
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
  if (btnUndo) {
    btnUndo.addEventListener("click", function () {
      undo();
    });
  }
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
        canvas.add(cloned);
        canvas.setActiveObject(cloned);
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
      if (guideRect) canvas.sendToBack(guideRect);
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
      if (guideRect) canvas.sendToBack(guideRect);
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

  var saved = loadState();
  if (saved && saved.kv_asset_id && kvMap[saved.kv_asset_id]) {
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
