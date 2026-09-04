(function () {
  const current = document.body.getAttribute("data-admin-page") || "";
  const allItems = [
    { id: "hub", href: "admin.html", label: "概览", perm: "page.admin" },
    { id: "users", href: "admin_users.html", label: "用户", perm: "cap.user_manage" },
    { id: "roles", href: "admin_roles.html", label: "角色", perm: "cap.role_manage" },
    { id: "perms", href: "admin_perms.html", label: "功能", perm: "cap.perm_manage" },
    { id: "cases", href: "admin_cases.html", label: "案件", perm: "cap.case_manage" },
    { id: "vectorize", href: "vectorize.html", label: "文档向量化", perm: "cap.vectorize" },
    { id: "skills", href: "admin_skills.html", label: "技能制作", perm: "cap.skill_manage" },
    { id: "mcp", href: "admin_mcp.html", label: "MCP 配置", perm: "cap.mcp_manage" }
  ];

  function go(href, event) {
    if (window.parent && window.parent.loadPage) {
      event.preventDefault();
      window.parent.loadPage(href);
    }
  }

  function has(code) {
    if (!window.LegalMindAuth) return true;
    return LegalMindAuth.hasPerm(code) || LegalMindAuth.hasPerm("page.admin");
  }

  if (window.LegalMindAuth && !LegalMindAuth.getToken()) {
    LegalMindAuth.requireLogin("login.html?next=admin.html");
    return;
  }

  const items = allItems.filter(function (it) {
    if (!window.LegalMindAuth) return true;
    if (it.id === "hub") return LegalMindAuth.hasPerm("page.admin") || LegalMindAuth.hasPerm("cap.case_manage") || LegalMindAuth.hasPerm("cap.user_manage");
    return LegalMindAuth.hasPerm(it.perm);
  });

  const nav = document.createElement("nav");
  nav.className = "admin-subnav";
  nav.setAttribute("aria-label", "管理功能");
  items.forEach(function (it) {
    const a = document.createElement("a");
    a.href = it.href;
    a.textContent = it.label;
    if (it.id === current) {
      a.className = "active";
      a.setAttribute("aria-current", "page");
    }
    a.addEventListener("click", function (e) { go(it.href, e); });
    nav.appendChild(a);
  });

  const mount = document.getElementById("adminSubnav");
  if (mount) {
    mount.replaceWith(nav);
  } else {
    const wrap = document.querySelector(".admin-wrap");
    const h1 = wrap && wrap.querySelector("h1");
    if (h1) wrap.insertBefore(nav, h1);
  }
})();
