(function () {
  const current = document.body.getAttribute("data-admin-page") || "";

  const groups = [
    {
      id: "overview",
      label: "概览",
      defaultId: "hub",
      anyPerm: ["page.admin", "cap.case_manage", "cap.user_manage", "cap.skill_manage", "cap.mcp_manage", "cap.vectorize"],
      items: [
        { id: "hub", href: "admin.html", label: "总览", perm: null }
      ]
    },
    {
      id: "rbac",
      label: "权限管理",
      defaultId: "users",
      anyPerm: ["cap.user_manage", "cap.role_manage", "cap.perm_manage"],
      items: [
        { id: "users", href: "admin_users.html", label: "用户", perm: "cap.user_manage" },
        { id: "roles", href: "admin_roles.html", label: "角色", perm: "cap.role_manage" },
        { id: "perms", href: "admin_perms.html", label: "功能", perm: "cap.perm_manage" }
      ]
    },
    {
      id: "cases",
      label: "案件管理",
      defaultId: "cases",
      anyPerm: ["cap.case_manage", "cap.case_assign"],
      items: [
        { id: "cases", href: "admin_cases.html", label: "案件", perm: "cap.case_manage" },
        { id: "clients", href: "admin_clients.html", label: "客户", perm: "cap.case_manage" }
      ]
    },
    {
      id: "knowledge",
      label: "知识库管理",
      defaultId: "kb-laws",
      anyPerm: ["cap.vectorize"],
      items: [
        { id: "kb-laws", href: "admin_kb_laws.html", label: "法规库", perm: "cap.vectorize" },
        { id: "kb-cases", href: "admin_kb_cases.html", label: "裁判案例库", perm: "cap.vectorize" },
        { id: "kb-templates", href: "admin_kb_templates.html", label: "要素文书", perm: "cap.vectorize" },
        { id: "vectorize", href: "vectorize.html", label: "向量调试", perm: "cap.vectorize" }
      ]
    },
    {
      id: "tools",
      label: "工具管理",
      defaultId: "skills",
      anyPerm: ["cap.skill_manage", "cap.mcp_manage"],
      items: [
        { id: "skills", href: "admin_skills.html", label: "技能", perm: "cap.skill_manage" },
        { id: "mcp", href: "admin_mcp.html", label: "MCP", perm: "cap.mcp_manage" }
      ]
    }
  ];

  function go(href, event) {
    if (window.parent && window.parent.loadPage) {
      event.preventDefault();
      window.parent.loadPage(href);
    }
  }

  function hasPerm(code) {
    if (!window.LegalMindAuth) return true;
    if (!code) {
      return LegalMindAuth.hasPerm("page.admin")
        || LegalMindAuth.hasPerm("cap.case_manage")
        || LegalMindAuth.hasPerm("cap.user_manage")
        || LegalMindAuth.hasPerm("cap.skill_manage")
        || LegalMindAuth.hasPerm("cap.vectorize");
    }
    return LegalMindAuth.hasPerm(code) || LegalMindAuth.hasPerm("page.admin");
  }

  function canSeeGroup(group) {
    if (!window.LegalMindAuth) return true;
    return (group.anyPerm || []).some(hasPerm);
  }

  function visibleItems(group) {
    return group.items.filter(function (it) {
      if (it.id === "hub") return canSeeGroup(group);
      return hasPerm(it.perm);
    });
  }

  function defaultItem(group, items) {
    const preferred = items.find(function (it) { return it.id === group.defaultId; });
    return preferred || items[0] || null;
  }

  function groupForPage(pageId) {
    for (let i = 0; i < groups.length; i++) {
      const g = groups[i];
      if (g.items.some(function (it) { return it.id === pageId; })) return g;
    }
    return groups[0];
  }

  if (window.LegalMindAuth && !LegalMindAuth.getToken()) {
    LegalMindAuth.requireLogin("login.html?next=admin.html");
    return;
  }

  const visibleGroups = groups.filter(function (g) {
    return canSeeGroup(g) && visibleItems(g).length > 0;
  });
  if (!visibleGroups.length) return;

  const activeGroup = groupForPage(current) || visibleGroups[0];
  const activeItems = visibleItems(activeGroup);

  const nav = document.createElement("nav");
  nav.className = "admin-subnav admin-subnav--levels";
  nav.setAttribute("aria-label", "管理功能");

  const primary = document.createElement("div");
  primary.className = "admin-nav-primary";
  primary.setAttribute("role", "tablist");
  primary.setAttribute("aria-label", "一级菜单");

  visibleGroups.forEach(function (group) {
    const items = visibleItems(group);
    const def = defaultItem(group, items);
    const btn = document.createElement("a");
    btn.href = def ? def.href : "#";
    btn.className = "admin-nav-primary-item" + (group.id === activeGroup.id ? " active" : "");
    btn.textContent = group.label;
    btn.setAttribute("role", "tab");
    btn.setAttribute("aria-selected", group.id === activeGroup.id ? "true" : "false");
    if (group.id === activeGroup.id) {
      btn.setAttribute("aria-current", "page");
    }
    btn.addEventListener("click", function (e) {
      if (!def) {
        e.preventDefault();
        return;
      }
      if (group.id === activeGroup.id && current === def.id) {
        e.preventDefault();
        return;
      }
      go(def.href, e);
    });
    primary.appendChild(btn);
  });
  nav.appendChild(primary);

  if (activeGroup.id !== "overview" && activeItems.length) {
    const secondary = document.createElement("div");
    secondary.className = "admin-nav-secondary";
    secondary.setAttribute("aria-label", activeGroup.label + "二级菜单");

    activeItems.forEach(function (it) {
      const a = document.createElement("a");
      a.href = it.href;
      a.textContent = it.label;
      if (it.id === current) {
        a.className = "active";
        a.setAttribute("aria-current", "page");
      }
      a.addEventListener("click", function (e) { go(it.href, e); });
      secondary.appendChild(a);
    });
    nav.appendChild(secondary);
  }

  const mount = document.getElementById("adminSubnav");
  if (mount) {
    mount.replaceWith(nav);
  } else {
    const wrap = document.querySelector(".admin-wrap");
    const h1 = wrap && wrap.querySelector("h1");
    if (h1) wrap.insertBefore(nav, h1);
  }
})();
