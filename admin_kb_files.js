/**
 * In-page file preview for knowledge-base admin pages.
 * Usage: const preview = KbFilePreview.create({ getBase, api, authHeaders, esc });
 *        preview.open(fileId, fallbackName);
 *        preview.open(fileId, fallbackName, { article: "第六十四条" });
 */
(function (global) {
  function fileExt(name) {
    const s = String(name || "");
    const i = s.lastIndexOf(".");
    return i >= 0 ? s.slice(i + 1).toLowerCase() : "";
  }

  var CN_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9
  };
  var ARTICLE_RE = /第[一二三四五六七八九十百千零〇\d]+条/;

  function cnToInt(s) {
    s = String(s || "").trim();
    if (!s) return null;
    if (/^\d+$/.test(s)) return parseInt(s, 10);
    if (s === "十") return 10;
    if (s === "百") return 100;
    var total = 0;
    var num = 0;
    for (var i = 0; i < s.length; i++) {
      var ch = s.charAt(i);
      if (CN_DIGITS[ch] != null) {
        num = CN_DIGITS[ch];
        continue;
      }
      if (ch === "十") {
        total += (num || 1) * 10;
        num = 0;
        continue;
      }
      if (ch === "百") {
        total += (num || 1) * 100;
        num = 0;
        continue;
      }
      if (ch === "千") {
        total += (num || 1) * 1000;
        num = 0;
        continue;
      }
      return null;
    }
    total += num;
    return total > 0 || s === "零" || s === "〇" ? total : null;
  }

  function intToCn(n) {
    if (n <= 0) return String(n);
    var digits = "零一二三四五六七八九";
    if (n < 10) return digits.charAt(n);
    if (n === 10) return "十";
    if (n < 20) return "十" + digits.charAt(n % 10);
    if (n < 100) {
      var tens = Math.floor(n / 10);
      var ones = n % 10;
      return digits.charAt(tens) + "十" + (ones ? digits.charAt(ones) : "");
    }
    if (n < 1000) {
      var hundreds = Math.floor(n / 100);
      var rest = n % 100;
      var head = digits.charAt(hundreds) + "百";
      if (rest === 0) return head;
      if (rest < 10) return head + "零" + digits.charAt(rest);
      if (rest < 20) {
        var rOnes = rest % 10;
        return head + "一十" + (rOnes ? digits.charAt(rOnes) : "");
      }
      return head + intToCn(rest);
    }
    return String(n);
  }

  /** Arabic/Chinese variants of the same article for highlight matching. */
  function normalizeArticleForms(article) {
    var raw = String(article || "").trim();
    if (!raw) return [];
    var m = raw.match(ARTICLE_RE);
    if (!m) return [raw];
    var core = m[0];
    var inner = core.slice(1, -1);
    var forms = [];
    var seen = {};
    function add(s) {
      if (s && !seen[s]) {
        seen[s] = 1;
        forms.push(s);
      }
    }
    add(core);
    var n = /^\d+$/.test(inner) ? parseInt(inner, 10) : cnToInt(inner);
    if (n != null && n > 0) {
      add("第" + n + "条");
      add("第" + intToCn(n) + "条");
    }
    return forms;
  }

  /**
   * Escape text and wrap the earliest matching article form in <mark>.
   * @returns {{ html: string, markId: string|null }}
   */
  function highlightArticleInText(text, article, escFn) {
    var esc = escFn || function (v) { return String(v == null ? "" : v); };
    var raw = String(text == null ? "" : text);
    var forms = normalizeArticleForms(article);
    if (!forms.length) return { html: esc(raw), markId: null };
    var bestIdx = -1;
    var bestForm = null;
    for (var i = 0; i < forms.length; i++) {
      var form = forms[i];
      var idx = raw.indexOf(form);
      if (idx >= 0 && (bestIdx < 0 || idx < bestIdx)) {
        bestIdx = idx;
        bestForm = form;
      }
    }
    if (bestIdx < 0 || !bestForm) return { html: esc(raw), markId: null };
    var markId = "kbArticleMark";
    var before = raw.slice(0, bestIdx);
    var match = raw.slice(bestIdx, bestIdx + bestForm.length);
    var after = raw.slice(bestIdx + bestForm.length);
    return {
      html:
        esc(before) +
        '<mark id="' + markId + '" class="kb-article-mark">' + esc(match) + "</mark>" +
        esc(after),
      markId: markId
    };
  }

  function create(deps) {
    const getBase = deps.getBase;
    const api = deps.api;
    const authHeaders = deps.authHeaders;
    const esc = deps.esc || function (v) { return String(v == null ? "" : v); };
    const rootId = deps.rootId || "kbFileViewer";

    function ensure() {
      let root = document.getElementById(rootId);
      if (root) return root;
      root = document.createElement("div");
      root.id = rootId;
      root.className = "file-viewer-root";
      root.hidden = true;
      root.innerHTML =
        '<div class="file-viewer-backdrop" data-close-viewer="1"></div>' +
        '<div class="file-viewer-panel" role="dialog" aria-modal="true">' +
          '<div class="file-viewer-header">' +
            '<div class="file-viewer-heading">' +
              '<h3 id="' + rootId + 'Title">文件预览</h3>' +
              '<p class="file-viewer-hint" id="' + rootId + 'Hint" hidden></p>' +
            "</div>" +
            '<div class="file-viewer-actions">' +
              '<a class="btn-ghost" id="' + rootId + 'Download" target="_blank" rel="noopener">下载</a>' +
              '<button type="button" class="btn-ghost" data-close-viewer="1">关闭</button>' +
            "</div>" +
          "</div>" +
          '<div class="file-viewer-body" id="' + rootId + 'Body"></div>' +
        "</div>";
      document.body.appendChild(root);
      root.addEventListener("click", function (e) {
        if (e.target && e.target.getAttribute && e.target.getAttribute("data-close-viewer")) {
          close();
        }
      });
      document.addEventListener("keydown", function (e) {
        if (e.key === "Escape" && root && !root.hidden) close();
      });
      return root;
    }

    function setHint(article) {
      const hint = document.getElementById(rootId + "Hint");
      if (!hint) return;
      const a = String(article || "").trim();
      if (!a) {
        hint.hidden = true;
        hint.textContent = "";
        return;
      }
      hint.hidden = false;
      hint.textContent = "请在文内查找：" + a;
    }

    function renderPreText(bodyEl, text, article, prefixHtml) {
      const pre = document.createElement("pre");
      if (article) {
        const hl = highlightArticleInText(text, article, esc);
        pre.innerHTML = hl.html;
        bodyEl.innerHTML = "";
        if (prefixHtml) bodyEl.insertAdjacentHTML("beforeend", prefixHtml);
        bodyEl.appendChild(pre);
        if (hl.markId) {
          const mark = document.getElementById(hl.markId);
          if (mark && typeof mark.scrollIntoView === "function") {
            setTimeout(function () {
              mark.scrollIntoView({ block: "center", behavior: "smooth" });
            }, 40);
          }
        }
      } else {
        pre.textContent = text;
        bodyEl.innerHTML = "";
        if (prefixHtml) bodyEl.insertAdjacentHTML("beforeend", prefixHtml);
        bodyEl.appendChild(pre);
      }
    }

    function close() {
      const root = document.getElementById(rootId);
      if (!root) return;
      root.hidden = true;
      const body = document.getElementById(rootId + "Body");
      if (body) body.innerHTML = "";
      setHint("");
    }

    async function open(fileId, fallbackName, options) {
      if (!fileId) throw new Error("无关联文件");
      options = options || {};
      const article = String(options.article || "").trim();
      const base = getBase();
      const root = ensure();
      const title = document.getElementById(rootId + "Title");
      const body = document.getElementById(rootId + "Body");
      const dl = document.getElementById(rootId + "Download");
      title.textContent = "加载中…";
      setHint("");
      body.innerHTML = '<p class="file-viewer-fallback">正在加载文件…</p>';
      dl.href = base + "/api/files/" + encodeURIComponent(fileId) + "/download";
      root.hidden = false;

      let info = {};
      try {
        info = await api("/api/files/" + encodeURIComponent(fileId));
      } catch (e) {
        info = { original_name: fallbackName || fileId };
      }
      const name = info.original_name || fallbackName || fileId;
      const mime = String(info.mime_type || "").toLowerCase();
      const ext = fileExt(name);
      title.textContent = name;
      dl.download = name;
      const previewUrl = base + "/api/files/" + encodeURIComponent(fileId) + "/preview";

      if (mime.indexOf("image/") === 0 || ["png", "jpg", "jpeg", "gif", "webp", "svg"].indexOf(ext) >= 0) {
        body.innerHTML = '<img alt="' + esc(name) + '" src="' + previewUrl + '">';
        return;
      }
      if (mime === "application/pdf" || ext === "pdf") {
        if (article) setHint(article);
        body.innerHTML = '<iframe title="' + esc(name) + '" src="' + previewUrl + '"></iframe>';
        return;
      }
      if (mime.indexOf("text/") === 0 || ["txt", "md", "csv", "log", "json", "html", "htm"].indexOf(ext) >= 0) {
        if (info.text_content) {
          renderPreText(body, info.text_content, article);
          return;
        }
        try {
          const resp = await fetch(previewUrl, { headers: authHeaders() });
          const text = await resp.text();
          renderPreText(body, text, article);
        } catch (e) {
          body.innerHTML =
            '<div class="file-viewer-fallback">文本预览失败，请下载后查看。<br><a href="' +
            previewUrl + '" target="_blank" rel="noopener">打开原文件</a></div>';
        }
        return;
      }
      // Word / other: prefer extracted text from upload-time parse
      if (info.text_content && String(info.text_content).trim()) {
        renderPreText(
          body,
          info.text_content,
          article,
          '<p class="file-viewer-fallback" style="padding:12px 16px 0;text-align:left;">已提取文本预览（原格式请下载查看）</p>'
        );
        return;
      }
      if (article) setHint(article);
      body.innerHTML =
        '<div class="file-viewer-fallback">' +
          "<p>该类型暂无提取文本，无法页内预览（如扫描件 PDF / 部分 Word）。</p>" +
          '<p><a class="btn-primary" style="display:inline-block;margin-top:8px;padding:8px 14px;text-decoration:none;" href="' +
            esc(dl.href) + '" target="_blank" rel="noopener">下载文件</a></p>' +
        "</div>";
    }

    return { open: open, close: close };
  }

  global.KbFilePreview = {
    create: create,
    fileExt: fileExt,
    normalizeArticleForms: normalizeArticleForms,
    highlightArticleInText: highlightArticleInText
  };

  /**
   * Upload modal: drag/drop + file list, then onSubmit(files).
   * Usage:
   *   const modal = KbUploadModal.create({
   *     title, hint, accept, maxFiles, maxBytes, esc,
   *     onSubmit: async (files, ctx) => { ... ctx.setStatus(...); }
   *   });
   *   modal.open();
   */
  function createUploadModal(opts) {
    const esc = opts.esc || function (v) { return String(v == null ? "" : v); };
    const rootId = opts.rootId || "kbUploadModal";
    const maxFiles = opts.maxFiles != null ? opts.maxFiles : 20;
    const maxBytes = opts.maxBytes != null ? opts.maxBytes : 50 * 1024 * 1024;
    const accept = opts.accept || ".pdf,.doc,.docx,.txt,.md,text/plain,application/pdf";
    const title = opts.title || "添加要上传的文件";
    const hint = opts.hint || "支持 pdf、docx、doc、txt、markdown 等文档，上传后将解析正文并入库向量化。";
    let files = [];
    let submitting = false;

    function formatSize(n) {
      if (n == null || isNaN(n)) return "";
      if (n < 1024) return n + " B";
      if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
      return (n / (1024 * 1024)).toFixed(1) + " MB";
    }

    function allowedExt(name) {
      const ext = fileExt(name);
      return ["pdf", "doc", "docx", "txt", "md"].indexOf(ext) >= 0;
    }

    function ensure() {
      let root = document.getElementById(rootId);
      if (root) return root;
      root = document.createElement("div");
      root.id = rootId;
      root.className = "kb-upload-root";
      root.hidden = true;
      root.innerHTML =
        '<div class="kb-upload-backdrop" data-kb-upload-close="1"></div>' +
        '<div class="kb-upload-panel" role="dialog" aria-modal="true" aria-labelledby="' + rootId + 'Title">' +
          '<div class="kb-upload-header">' +
            '<div>' +
              '<h3 id="' + rootId + 'Title">' + esc(title) + "</h3>" +
              '<p class="kb-upload-hint" id="' + rootId + 'Hint">' + esc(hint) + "</p>" +
            "</div>" +
            '<button type="button" class="kb-upload-x" data-kb-upload-close="1" aria-label="关闭">×</button>' +
          "</div>" +
          '<div class="kb-upload-body">' +
            '<div class="kb-upload-drop" id="' + rootId + 'Drop" tabindex="0">' +
              '<div class="kb-upload-icon" aria-hidden="true">' +
                '<svg width="44" height="44" viewBox="0 0 48 48" fill="none">' +
                  '<rect x="10" y="6" width="28" height="36" rx="4" stroke="currentColor" stroke-width="2"/>' +
                  '<path d="M18 18h12M18 24h12M18 30h8" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>' +
                  '<circle cx="34" cy="34" r="9" fill="#1a4a6e"/>' +
                  '<path d="M34 30v8M30 34h8" stroke="#fff" stroke-width="2" stroke-linecap="round"/>' +
                "</svg>" +
              "</div>" +
              '<p class="kb-upload-drop-text">将文件拖拽至此处，或 <button type="button" class="kb-upload-link" id="' + rootId + 'Pick">点击添加</button></p>' +
              '<p class="kb-upload-limits" id="' + rootId + 'Limits"></p>' +
              '<input type="file" id="' + rootId + 'Input" multiple hidden accept="' + esc(accept) + '">' +
            "</div>" +
            '<ul class="kb-upload-list" id="' + rootId + 'List" hidden></ul>' +
            '<p class="kb-upload-status muted" id="' + rootId + 'Status"></p>' +
          "</div>" +
          '<div class="kb-upload-footer">' +
            '<button type="button" class="btn-ghost" data-kb-upload-close="1">取消</button>' +
            '<button type="button" class="btn-primary" id="' + rootId + 'Submit">立即上传</button>' +
          "</div>" +
        "</div>";
      document.body.appendChild(root);

      const drop = document.getElementById(rootId + "Drop");
      const input = document.getElementById(rootId + "Input");
      const pick = document.getElementById(rootId + "Pick");
      const submit = document.getElementById(rootId + "Submit");
      const limits = document.getElementById(rootId + "Limits");
      limits.textContent =
        "单次最多 " + maxFiles + " 个文件，单文件不超过 " + formatSize(maxBytes);

      root.addEventListener("click", function (e) {
        if (e.target && e.target.getAttribute && e.target.getAttribute("data-kb-upload-close") && !submitting) {
          close();
        }
      });
      document.addEventListener("keydown", function (e) {
        if (e.key === "Escape" && root && !root.hidden && !submitting) close();
      });
      pick.addEventListener("click", function (e) {
        e.stopPropagation();
        input.click();
      });
      drop.addEventListener("click", function (e) {
        if (e.target === pick || (e.target.closest && e.target.closest("#" + rootId + "Pick"))) return;
        if (e.target.closest && e.target.closest(".kb-upload-list")) return;
        input.click();
      });
      drop.addEventListener("dragenter", function (e) { e.preventDefault(); drop.classList.add("is-drag"); });
      drop.addEventListener("dragover", function (e) { e.preventDefault(); drop.classList.add("is-drag"); });
      drop.addEventListener("dragleave", function (e) {
        if (!drop.contains(e.relatedTarget)) drop.classList.remove("is-drag");
      });
      drop.addEventListener("drop", function (e) {
        e.preventDefault();
        drop.classList.remove("is-drag");
        addFiles(e.dataTransfer && e.dataTransfer.files);
      });
      input.addEventListener("change", function () {
        addFiles(input.files);
        input.value = "";
      });
      submit.addEventListener("click", function () { submitFiles(); });
      return root;
    }

    function setStatus(text) {
      const el = document.getElementById(rootId + "Status");
      if (el) el.textContent = text || "";
    }

    function renderList() {
      const list = document.getElementById(rootId + "List");
      if (!list) return;
      list.hidden = files.length === 0;
      list.innerHTML = files.map(function (f, i) {
        return '<li>' +
          '<span class="kb-upload-fname">' + esc(f.name) + "</span>" +
          '<span class="kb-upload-fmeta">' + esc(formatSize(f.size)) + "</span>" +
          '<button type="button" class="kb-upload-remove" data-rm="' + i + '"' +
            (submitting ? " disabled" : "") + ">移除</button>" +
          "</li>";
      }).join("");
      list.querySelectorAll("[data-rm]").forEach(function (btn) {
        btn.addEventListener("click", function (e) {
          e.stopPropagation();
          if (submitting) return;
          const idx = Number(btn.getAttribute("data-rm"));
          files.splice(idx, 1);
          renderList();
        });
      });
    }

    function addFiles(fileList) {
      if (!fileList || !fileList.length) return;
      const errors = [];
      Array.prototype.forEach.call(fileList, function (f) {
        if (!allowedExt(f.name)) {
          errors.push(f.name + "：格式不支持");
          return;
        }
        if (f.size > maxBytes) {
          errors.push(f.name + "：超过 " + formatSize(maxBytes));
          return;
        }
        const dup = files.some(function (x) {
          return x.name === f.name && x.size === f.size && x.lastModified === f.lastModified;
        });
        if (dup) return;
        if (files.length >= maxFiles) {
          errors.push("已达单次上限 " + maxFiles + " 个");
          return;
        }
        files.push(f);
      });
      renderList();
      if (errors.length) setStatus(errors.slice(0, 3).join("；"));
      else setStatus(files.length ? ("已选 " + files.length + " 个文件") : "");
    }

    function setBusy(busy) {
      submitting = !!busy;
      const submit = document.getElementById(rootId + "Submit");
      const pick = document.getElementById(rootId + "Pick");
      if (submit) {
        submit.disabled = busy;
        submit.textContent = busy ? "上传中…" : "立即上传";
      }
      if (pick) pick.disabled = busy;
      renderList();
    }

    async function submitFiles() {
      if (submitting) return;
      if (!files.length) {
        setStatus("请先添加文件");
        return;
      }
      if (typeof opts.onSubmit !== "function") return;
      setBusy(true);
      try {
        await opts.onSubmit(files.slice(), {
          setStatus: setStatus,
          close: close
        });
        files = [];
        renderList();
        close();
      } catch (e) {
        setStatus(e && e.message ? e.message : String(e));
      } finally {
        setBusy(false);
      }
    }

    function open() {
      ensure();
      files = [];
      renderList();
      setStatus("");
      setBusy(false);
      document.getElementById(rootId).hidden = false;
    }

    function close() {
      const root = document.getElementById(rootId);
      if (root) root.hidden = true;
      files = [];
      renderList();
      setStatus("");
      setBusy(false);
    }

    return { open: open, close: close, setStatus: setStatus };
  }

  global.KbUploadModal = { create: createUploadModal };
})(window);
