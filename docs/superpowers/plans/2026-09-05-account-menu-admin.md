# 账号下拉收纳「管理后台」Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 壳层顶栏去掉独立「管理后台」按钮，改由用户名下拉提供「管理后台 / 联系我们 / 分隔 / 退出」；删除首页 `adminTab`。

**Architecture:** 复用 `index.html` 现有 `navUserDropdown`；`syncShellNav` 用 `canOpenAdmin()` 控制管理项显隐；首页去掉管理入口后仅保留历史记录 + 标题布局。

**Tech Stack:** 现有静态 HTML/CSS/JS（`index.html` / `index.css` / `home.*`）。

**Spec:** `docs/superpowers/specs/2026-09-05-account-menu-admin-design.md`

## Global Constraints

- 不自动 commit（除非用户要求）
- 无权限隐藏「管理后台」（不显示禁用项）
- 菜单顺序：管理后台 → 联系我们 → 分隔线 → 退出
- 不改管理后台内部页、联系我们弹窗文案、logout API

## File map

| File | Responsibility |
|------|----------------|
| `index.html` | 顶栏 DOM + 下拉项 + `syncShellNav` / 点击绑定 |
| `index.css` | 下拉分隔线与退出强调色 |
| `home.html` | 删除 `adminTab` |
| `home.js` | 删除 `syncAdminEntry` / admin 点击 / 仅供其用的 `canOpenAdmin` |
| `home.css` | 删除 `.admin-tab*`；保留 `.history-tab` 样式 |

---

### Task 1: 壳层下拉加入管理后台并移除顶栏按钮

**Files:**
- Modify: `index.html`
- Modify: `index.css`

- [ ] **Step 1: 替换顶栏导航结构**

将：

```html
<button type="button" id="navLoginBtn" hidden>登录</button>
<button type="button" id="navAdminBtn" hidden>管理后台</button>
<div id="navUserMenu" class="nav-user-menu" hidden>
  ...
  <div id="navUserDropdown" class="nav-user-dropdown" hidden role="menu">
    <button type="button" id="navContactBtn" role="menuitem">联系我们</button>
    <button type="button" id="navLogoutBtn" role="menuitem">退出</button>
  </div>
</div>
```

改为：

```html
<button type="button" id="navLoginBtn" hidden>登录</button>
<div id="navUserMenu" class="nav-user-menu" hidden>
  <button type="button" id="navUserBtn" class="nav-user-btn" aria-haspopup="true" aria-expanded="false">
    <span id="navUserLabel" class="nav-user-name"></span>
    <span class="nav-user-caret" aria-hidden="true">▾</span>
  </button>
  <div id="navUserDropdown" class="nav-user-dropdown" hidden role="menu">
    <button type="button" id="navAdminMenuBtn" role="menuitem" hidden>管理后台</button>
    <button type="button" id="navContactBtn" role="menuitem">联系我们</button>
    <div class="nav-user-dropdown-sep" role="separator" aria-hidden="true"></div>
    <button type="button" id="navLogoutBtn" class="nav-user-logout" role="menuitem">退出</button>
  </div>
</div>
```

- [ ] **Step 2: 更新 `syncShellNav`**

移除对 `navAdminBtn` 的引用；改为：

```javascript
function syncShellNav() {
  const loginBtn = document.getElementById('navLoginBtn');
  const userMenu = document.getElementById('navUserMenu');
  const userLabel = document.getElementById('navUserLabel');
  const adminMenuBtn = document.getElementById('navAdminMenuBtn');
  const loggedIn = !!(window.LegalMindAuth && LegalMindAuth.getToken());
  loginBtn.hidden = loggedIn;
  if (adminMenuBtn) adminMenuBtn.hidden = !(loggedIn && canOpenAdmin());
  if (loggedIn) {
    const s = LegalMindAuth.getSession();
    const name = (s && s.user && (s.user.display_name || s.user.username)) || '已登录';
    userLabel.textContent = name;
    userMenu.hidden = false;
  } else {
    userLabel.textContent = '';
    userMenu.hidden = true;
    closeUserMenu();
  }
}
```

- [ ] **Step 3: 绑定管理项点击；删除旧 `navAdminBtn` 处理器**

```javascript
document.getElementById('navAdminMenuBtn').onclick = function (e) {
  e.stopPropagation();
  closeUserMenu();
  loadPage('admin.html');
};
```

删除原 `document.getElementById('navAdminBtn').onclick = ...`。

- [ ] **Step 4: CSS — 分隔线与退出色**

在 `index.css` 的 `.nav-user-dropdown` 样式区增加：

```css
.nav-user-dropdown-sep {
  height: 1px;
  margin: 4px 6px;
  background: #e5e7eb;
}

.nav-user-dropdown button.nav-user-logout {
  color: #b91c1c;
}

.nav-user-dropdown button.nav-user-logout:hover {
  background: #fef2f2;
  color: #991b1b;
}
```

- [ ] **Step 5: 手工检查** — 登录有权限账号，确认顶栏无独立管理按钮、下拉顺序正确。

---

### Task 2: 删除首页 adminTab

**Files:**
- Modify: `home.html`
- Modify: `home.js`
- Modify: `home.css`

- [ ] **Step 1: `home.html`** — 删除整个 `#adminTab` 按钮块（约 24–30 行），保留 `#historyTab` 与标题区。布局仍用三列 grid，右侧留空以保持标题居中。

- [ ] **Step 2: `home.js`**

删除：
- `function canOpenAdmin() { ... }`（若仅被 admin 入口使用）
- `function syncAdminEntry() { ... }`
- `DOMContentLoaded`（或初始化）里对 `adminTab` 的 `onclick`、`syncAdminEntry()`、以及 `fetchMe().then(syncAdminEntry...)` 中的 `syncAdminEntry` 调用

保留 `fetchMe` 若仍被案件列表等其它逻辑需要；仅去掉 admin 同步。

示例：登录分支改为只加载案件列表：

```javascript
if (window.LegalMindAuth && LegalMindAuth.getToken()) {
  LegalMindAuth.fetchMe().then(function () {
    loadHomeCaseOptions().catch(function (e) {
      console.warn('加载案件列表失败', e);
    });
  }).catch(function () {
    loadHomeCaseOptions().catch(function (e) {
      console.warn('加载案件列表失败', e);
    });
  });
} else {
  // 原有未登录分支（若原先在 else 里调 syncAdminEntry，一并删掉）
}
```

（实现时以当前 `home.js` 初始化块为准，保证不破坏案件下拉与历史入口。）

- [ ] **Step 3: `home.css`** — 从共享选择器中去掉 `.admin-tab`：

将 `.history-tab, .admin-tab { ... }` 改为仅 `.history-tab { ... }`（属性原样保留）。  
删除独立规则：`.admin-tab`、`.admin-tab[hidden]`、以及 hover/active/svg/text/media 中所有 `.admin-tab` 分支。  
注释「与右侧管理后台对等」改为「标题行左侧历史入口」之类。

- [ ] **Step 4: 冒烟** — 经 `index.html` 打开首页，确认无首页管理按钮；下拉仍可进管理后台。

---

### Task 3: 验收收尾

- [ ] 对照 spec §5 清单：有权限 / 无权限 / 未登录 / 联系我们 / 退出。
- [ ] 强刷 `index.html`（注意 `index.css?v=...` 如需可 bump 版本参数）。
- [ ] Commit only if user asks。

---

## Spec coverage

| Spec | Task |
|------|------|
| 顶栏无独立管理按钮 | 1 |
| 下拉顺序与分隔、退出强调 | 1 |
| 无权限隐藏管理项 | 1 |
| 删除首页 adminTab | 2 |
| 联系/退出行为不变 | 1（不改现有 handler 逻辑） |

## Self-review

- 无 TBD；`navAdminMenuBtn` id 全计划一致。
- 避免残留对 `navAdminBtn` / `adminTab` 的引用（实现后可 `rg` 确认）。
