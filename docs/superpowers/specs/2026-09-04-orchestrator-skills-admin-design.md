# LegalMind 一主多辅、Skill 包与管理后台设计

Date: 2026-09-04  
Status: approved direction (user: MCP-native orchestration, Skill files not MCP prompts, Word export, admin menu; aux agents may call each other under limits)

## Problem

The current app is a single DeepSeek agent plus MCP resources/tools. The product now needs:

1. One orchestrator agent and three specialist agents (text analysis, statute/case retrieval, document writing).
2. Word download when a document is finished in a multi-turn chat.
3. A homepage entry to an admin menu: vectorization, skill authoring, MCP settings.

MCP prompt templates (`prompts/list`, `gen_legal_doc_guide`, `contract_review_guide`, `judge_work_guide`) stay unchanged.

## Goals

- Orchestrator routes work; it does not write long legal prose or dump statutes itself.
- Specialists may **call each other in a controlled graph**, e.g. text analysis requests retrieval then analyzes the returned statutes/cases.
- Skills are traditional Skill packages on disk (`SKILL.md`), not MCP prompts.
- Finished 文书 is a downloadable `.docx` (Word-compatible; not legacy binary `.doc`).
- Admin: vectorize (existing page), skill CRUD, MCP/LLM config form.

## Non-goals (this slice)

- LangChain / LangGraph.
- Changing or migrating existing MCP prompt templates.
- Binary `.doc` (OLE) generation.
- Multi-model routing (all agents use the same DeepSeek endpoint).
- Auth/roles beyond a simple admin entry (no login in this slice).

## Architecture

Keep the existing HTTP MCP server and browser client. Add a server-side orchestration API.

```
User  →  Web client  →  POST /api/orchestrate
                              │
                              ▼
                        Orchestrator agent
                         (route + plan)
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
        text_analysis   legal_retrieval   doc_writing
              │               ▲               │
              └──── subcall ──┘               │
                                              ▼
                                         python-docx
                                         /api/files/.../download
```

### Why not LangGraph here

The stack already has MCP JSON-RPC, session APIs, and a client JSON protocol. A thin orchestrator plus specialist prompts reuses DeepSeek and MCP tools. LangGraph would add a second runtime next to `mcp_client.js` without unlocking the three specialists.

### Agent roles

| Agent | Does | Must not |
|-------|------|----------|
| `orchestrator` | Classify intent, produce a **plan** (ordered steps + allowed subcalls), choose skills to inject | Long-form drafting, raw corpus dump |
| `text_analysis` | Facts, issues, evidence gaps, legal characterization | Invent statutes; may **subcall** retrieval |
| `legal_retrieval` | MCP `legal://law_regulation`, `legal://similar_cases`, vector search | Write pleadings |
| `doc_writing` | Fill structure, produce 文书 text, trigger `.docx` | Skip required facts; may **subcall** analysis and/or retrieval once each |

### Auxiliary-to-auxiliary calls (required)

Specialists are not isolated silos. Typical flow: **analysis needs retrieval**.

**Allowed edges (acyclic):**

- `text_analysis` → `legal_retrieval` (default for “结合法规类案分析”)
- `doc_writing` → `text_analysis` (optional, if facts not yet structured)
- `doc_writing` → `legal_retrieval` (optional, cite-check before final draft)

**Forbidden:**

- `legal_retrieval` → any other agent (retrieval is a leaf; it only uses MCP/tools)
- `orchestrator` as a callee of specialists (no bounce-back to main mid-subcall)
- Cycles: analysis → retrieval → analysis in the same request
- Depth greater than **2** (orchestrator is depth 0; first specialist 1; one nested specialist 2)

**Who decides the graph:**

1. Orchestrator emits a plan, e.g. `{ "steps": [ { "agent": "text_analysis", "allow_subcalls": ["legal_retrieval"] } ] }`.
2. If a specialist needs data it does not have, it returns a structured **subcall request** (`need_agent` + `query`). The server runs that agent, then **resumes** the caller with the sub-result in context. The specialist does not HTTP-call the LLM stack itself.

This keeps one Python call stack (`run_agent` with `depth` and `visited` set) instead of agents freely spawning unbounded work.

**Idempotency:** the same `legal_retrieval` query in one orchestration request is cached in-memory so analysis and writing do not double-hit MCP.

## Skills (traditional Skill, not MCP prompts)

Directory: `skills/<skill_id>/SKILL.md`

Front matter (YAML in markdown):

- `name`, `description` (when to load), `applies_to`: list among `orchestrator` \| `text_analysis` \| `legal_retrieval` \| `doc_writing`

Body: procedures, checklists, output shape.

Orchestrator matches user text + `description`, injects at most **N=3** skill bodies into the chosen specialist(s). MCP `prompts/get` is never used to store or edit these files.

Admin “技能制作” = list/create/edit/delete these directories only.

## Word export

When `doc_writing` finishes with `status: complete` and non-empty body:

1. Server builds a `.docx` via `python-docx` (title + paragraphs; simple formatting).
2. File is stored through existing `FileService` / `uploads`.
3. Orchestrate response includes `artifact: { filename, file_id, download_url, mime }`.
4. Chat UI shows a download control. MIME: `application/vnd.openxmlformats-officedocument.wordprocessingml.document`. Filename ends with `.docx`. UI copy may say “Word 文档”.

Multi-turn: incomplete drafts stay text-only; download appears only when the writer marks complete (or user explicitly asks to export current draft).

## Admin UI

- Homepage (in `index.html` chrome and/or `home.html` header, opposite 历史记录): **管理后台**.
- `admin.html`: three entries — 文档向量化 (`vectorize.html`), 技能制作 (`admin_skills.html`), MCP 配置 (`admin_mcp.html`).
- Vectorize page behavior unchanged aside from a back link to admin.
- MCP 配置: form for `mcp_server.host/port`, `llm.api_url/model/timeout/max_retries/temperature/max_tokens`; API key write-only (placeholder, never echo full key). Saves `config.json`. Does not edit `system_prompt` in this slice unless a dedicated textarea is already trivial; prefer not to expose the huge prompt in v1.

## Client integration

Existing MCP handshake, sessions, and resource/tool JSON protocol remain for the current chat path.

New path: chat send may call `/api/orchestrate` with `{ session_id, messages, user_text }`. Response `{ visible_text, agent, plan, artifact?, pending_question? }`.

If orchestrator returns `ask_user`, the client shows `pending_question` and does not run specialists.

Fallback: if orchestrate fails, keep current single-agent MCP client path so the app does not go dark.

## APIs (server)

- `POST /api/orchestrate` — body: session + messages; runs plan + subcalls; returns text + optional artifact.
- `GET /api/skills` `POST /api/skills` `PUT /api/skills/:id` `DELETE /api/skills/:id` — Skill file CRUD.
- `GET /api/admin/mcp-config` `PUT /api/admin/mcp-config` — config.json subset (no full key in GET).

Orchestrate internally uses existing MCP resource/tool handlers (in-process), not a second HTTP hop to itself, to avoid deadlock on the threading server.

## Error handling

- Subcall failure: caller receives `{ error }` and must answer without fabricated law, stating retrieval failed.
- Depth/cycle violation: 400-level orchestration error, user-visible “任务编排失败”.
- Docx failure: still return text; omit artifact; log server error.
- Config save validation: port integer, URL prefix `http`.

## Testing

- Unit: plan parser; `allow_subcalls` / depth / cycle; retrieval cache key; skill front-matter parse; config redaction.
- Integration: analysis plan with subcall to retrieval (mock MCP resource read); writer complete → file exists and download path 200.
- No change to existing `prompts/list` fixture counts.

## Risks

- `mcp_server.py` is already large; new modules live under `server/agents/` and `server/skill_service.py`, wired from the HTTP handler only.
- Orchestrator JSON must be strictly parsed (same delimiter discipline as today’s client protocol, e.g. a dedicated `==ORCH==` or JSON-only mode with low temperature).
