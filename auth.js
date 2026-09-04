/**
 * Client auth helper for LegalMind RBAC.
 */
(function (global) {
  const KEY = "legalmind_auth";

  function read() {
    try {
      return JSON.parse(localStorage.getItem(KEY) || "null");
    } catch (e) {
      return null;
    }
  }

  function write(data) {
    if (!data) localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, JSON.stringify(data));
  }

  async function mcpBase() {
    const cfg = await (await fetch("config.json?t=" + Date.now())).json();
    const host = (!cfg.mcp_server.host || cfg.mcp_server.host === "localhost")
      ? "127.0.0.1" : cfg.mcp_server.host;
    return "http://" + host + ":" + cfg.mcp_server.port;
  }

  const Auth = {
    getToken: function () {
      const s = read();
      return s && s.token ? s.token : null;
    },
    getSession: function () { return read(); },
    setSession: function (payload) { write(payload); },
    clearSession: function () { write(null); },
    authHeaders: function (extra) {
      const h = Object.assign({ "Content-Type": "application/json" }, extra || {});
      const t = Auth.getToken();
      if (t) h.Authorization = "Bearer " + t;
      return h;
    },
    hasPerm: function (code) {
      const s = read();
      const list = (s && s.firm_permissions) || [];
      return list.indexOf(code) !== -1;
    },
    requireLogin: function (redirect) {
      if (Auth.getToken()) return true;
      const target = redirect || ("login.html?next=" + encodeURIComponent(location.pathname.split("/").pop() || "home.html"));
      if (window.parent && window.parent !== window && window.parent.loadPage) {
        window.parent.loadPage(target);
      } else {
        location.href = target;
      }
      return false;
    },
    mcpBase: mcpBase,
    fetchMe: async function (caseId) {
      const base = await mcpBase();
      const q = caseId != null ? ("?case_id=" + encodeURIComponent(caseId)) : "";
      const resp = await fetch(base + "/api/auth/me" + q, { headers: Auth.authHeaders() });
      if (resp.status === 401) {
        Auth.clearSession();
        return null;
      }
      if (!resp.ok) throw new Error("me failed " + resp.status);
      const data = await resp.json();
      const cur = read() || {};
      write(Object.assign({}, cur, {
        token: cur.token,
        user: data.user,
        firm_roles: data.firm_roles,
        firm_permissions: data.firm_permissions
      }));
      return data;
    },
    login: async function (username, password) {
      const base = await mcpBase();
      const resp = await fetch(base + "/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: username, password: password })
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || "登录失败");
      write(data);
      return data;
    },
    logout: async function () {
      try {
        const base = await mcpBase();
        await fetch(base + "/api/auth/logout", {
          method: "POST",
          headers: Auth.authHeaders()
        });
      } catch (e) {}
      Auth.clearSession();
    },
    getCaseId: function () {
      const s = read();
      return s && s.case_id != null ? s.case_id : null;
    },
    setCaseId: function (caseId) {
      const s = read() || {};
      s.case_id = caseId;
      write(s);
    }
  };

  global.LegalMindAuth = Auth;
})(window);
