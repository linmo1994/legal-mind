# 引用链接与法条预览 Implementation Plan

> **For agentic workers:** Use executing-plans or implement inline.

**Goal:** 多轮助手答：正文内联可点引用 + 底部列表；点击 KbFilePreview 预览法规/类案。

**Spec:** `docs/superpowers/specs/2026-09-06-citation-links-preview-design.md`

- [x] Task 1: linkify + renderAssistantAnswerWithCitations + openCitationPreview
- [x] Task 2: orchestrate / addMessage / addCombinedMessage / restoreHistory；CSS；cache-bust `?v=20260906cite1`
- [x] Task 3: `node --check` OK；待手工冒烟

不自动 commit。
