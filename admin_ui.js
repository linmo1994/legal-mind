(function (global) {
  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (ch) {
      return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch];
    });
  }

  function ensure(id, html) {
    let el = document.getElementById(id);
    if (!el) {
      document.body.insertAdjacentHTML("beforeend", html);
      el = document.getElementById(id);
    }
    return el;
  }

  function ensureShell() {
    ensure("adminDrawer",
      '<div id="adminDrawer" class="drawer-root" hidden>' +
        '<div class="drawer-backdrop" data-close="drawer"></div>' +
        '<div class="drawer-panel" role="dialog" aria-modal="true" aria-labelledby="drawerTitle">' +
          '<div class="drawer-header"><h2 id="drawerTitle"></h2><button type="button" class="btn-ghost" data-close="drawer">关闭</button></div>' +
          '<div class="drawer-body" id="drawerBody"></div>' +
          '<div class="drawer-footer" id="drawerFooter"></div>' +
        "</div></div>");
    ensure("adminModal",
      '<div id="adminModal" class="modal-root" hidden>' +
        '<div class="modal-backdrop" data-close="modal"></div>' +
        '<div class="modal-dialog" role="dialog" aria-modal="true">' +
          "<h3 id=\"modalTitle\"></h3><p id=\"modalMessage\" class=\"muted\"></p>" +
          '<div class="modal-actions">' +
            '<button type="button" class="btn-ghost" data-close="modal">取消</button>' +
            '<button type="button" class="btn-primary" id="modalOk">确定</button>' +
          "</div></div></div>");
    ensure("adminToasts", '<div id="adminToasts" class="toast-stack"></div>');
  }

  function closeDrawer() {
    document.getElementById("adminDrawer").hidden = true;
    document.body.style.overflow = "";
  }

  function openDrawer(opts) {
    ensureShell();
    document.getElementById("drawerTitle").textContent = opts.title || "";
    document.getElementById("drawerBody").innerHTML = opts.body || "";
    document.getElementById("drawerFooter").innerHTML = opts.footer || "";
    document.getElementById("adminDrawer").hidden = false;
    document.body.style.overflow = "hidden";
    if (typeof opts.onReady === "function") opts.onReady();
  }

  function toast(message, ok) {
    ensureShell();
    const el = document.createElement("div");
    el.className = "toast" + (ok === false ? " err" : "");
    el.textContent = message;
    document.getElementById("adminToasts").appendChild(el);
    setTimeout(function () { el.remove(); }, 2800);
  }

  function confirmAction(opts) {
    ensureShell();
    return new Promise(function (resolve) {
      document.getElementById("modalTitle").textContent = opts.title || "请确认";
      document.getElementById("modalMessage").textContent = opts.message || "";
      const okBtn = document.getElementById("modalOk");
      okBtn.textContent = opts.okText || "确定";
      okBtn.className = opts.danger ? "btn-danger-outline" : "btn-primary";
      const root = document.getElementById("adminModal");
      function finish(yes) {
        root.hidden = true;
        root.removeEventListener("click", onClick);
        document.removeEventListener("keydown", onKey);
        resolve(yes);
      }
      function onClick(ev) {
        if (ev.target.id === "modalOk") finish(true);
        else if (ev.target.getAttribute("data-close") === "modal") finish(false);
      }
      function onKey(ev) {
        if (ev.key === "Escape") finish(false);
      }
      root.addEventListener("click", onClick);
      document.addEventListener("keydown", onKey);
      root.hidden = false;
    });
  }

  document.addEventListener("click", function (ev) {
    if (ev.target && ev.target.getAttribute("data-close") === "drawer") closeDrawer();
  });
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape") {
      const drawer = document.getElementById("adminDrawer");
      if (drawer && !drawer.hidden) closeDrawer();
    }
  });

  async function apiBase() {
    const cfg = await (await fetch("config.json?t=" + Date.now())).json();
    const host = (!cfg.mcp_server.host || cfg.mcp_server.host === "localhost") ? "127.0.0.1" : cfg.mcp_server.host;
    return "http://" + host + ":" + cfg.mcp_server.port;
  }

  global.AdminUI = { esc, openDrawer, closeDrawer, toast, confirm: confirmAction, confirmAction: confirmAction, apiBase };
})(window);
