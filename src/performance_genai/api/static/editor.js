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
  var colorInput = document.getElementById("color-input");
  var fontScaleInput = document.getElementById("font-scale");
  var fontScaleValue = document.getElementById("font-scale-value");
  var alignSelect = document.getElementById("align-select");
  var guideSelect = document.getElementById("guide-select");
  var btnPreview = document.getElementById("btn-preview");
  var btnInsertText = document.getElementById("btn-insert-text");
  var copyButtons = document.querySelectorAll(".use-copy-set");

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

  function getTextObjects() {
    return canvas.getObjects().filter(function (obj) {
      return obj && obj.type === "textbox";
    });
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
    if (!obj) return;
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
    obj.set({
      fontFamily: fontSelect.value,
      fill: colorInput.value,
      textAlign: alignSelect.value,
    });
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
    canvas.renderAll();
    saveState();
    return obj;
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
        getTextObjects().forEach(function (obj) {
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
      label.textContent = kv.label || kv.id;
      if (bgImg) {
        log("Image element size: " + bgImg.clientWidth + "x" + bgImg.clientHeight);
      }
      log("Canvas size: " + canvas.getWidth() + "x" + canvas.getHeight());
    };
    probe.onerror = function () {
      log("Image onerror fired for " + kv.url);
      label.textContent = "Failed to load image";
    };
    probe.src = kv.url;
  }

  function updateAllStyles() {
    getTextObjects().forEach(function (obj) {
      applyTextStyles(obj);
    });
    canvas.renderAll();
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
      text_color: colorInput.value,
      text_align: alignSelect.value,
      font_scale: fontScale,
      guide_ratio: guideRatio,
      layers: collectTextLayers(),
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

  canvas.on("object:modified", function (e) {
    normalizeObjectScale(e.target);
    canvas.renderAll();
    saveState();
  });
  canvas.on("text:changed", function (e) {
    saveState();
  });

  select.addEventListener("change", function () {
    var kv = kvMap[select.value];
    setBackground(kv);
  });

  fontSelect.addEventListener("change", updateAllStyles);
  colorInput.addEventListener("input", updateAllStyles);
  alignSelect.addEventListener("change", updateAllStyles);
  if (guideSelect) {
    guideSelect.addEventListener("change", function () {
      guideRatio = guideSelect.value || "1:1";
      applyGuide(null, { preserveText: true });
      saveState();
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
  if (btnInsertText) {
    btnInsertText.addEventListener("click", function () {
      addTextBox("", defaultTextBox);
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
