"""Traditional Skill packages: skills/<id>/SKILL.md with YAML front matter."""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple


FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


def parse_skill_markdown(text: str) -> Tuple[Dict[str, Any], str]:
    match = FRONT_MATTER_RE.match(text.strip() + ("\n" if not text.endswith("\n") else ""))
    if not match:
        return {}, text
    raw, body = match.group(1), match.group(2).strip()
    meta: Dict[str, Any] = {"applies_to": []}
    current_list = None
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("- ") and current_list:
            meta[current_list].append(stripped[2:].strip())
            continue
        if ":" in stripped:
            key, val = stripped.split(":", 1)
            key = key.strip()
            val = val.strip()
            if val == "":
                current_list = key
                meta[key] = []
            else:
                current_list = None
                meta[key] = val
    if isinstance(meta.get("applies_to"), str):
        meta["applies_to"] = [meta["applies_to"]]
    return meta, body


def _dump_skill_markdown(name: str, description: str, applies_to: List[str], body: str) -> str:
    lines = ["---", f"name: {name}", f"description: {description}", "applies_to:"]
    for item in applies_to or []:
        lines.append(f"  - {item}")
    lines.append("---")
    lines.append("")
    lines.append(body.rstrip())
    lines.append("")
    return "\n".join(lines)


class SkillService:
    def __init__(self, root_dir: str):
        self.root_dir = root_dir
        os.makedirs(self.root_dir, exist_ok=True)

    def _dir(self, skill_id: str) -> str:
        safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", skill_id).strip("-").lower()
        if not safe:
            raise ValueError("invalid skill id")
        return os.path.join(self.root_dir, safe)

    def _read(self, skill_id: str) -> Dict[str, Any]:
        path = os.path.join(self._dir(skill_id), "SKILL.md")
        if not os.path.isfile(path):
            raise FileNotFoundError(skill_id)
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        meta, body = parse_skill_markdown(text)
        return {
            "id": skill_id,
            "name": meta.get("name") or skill_id,
            "description": meta.get("description") or "",
            "applies_to": meta.get("applies_to") or [],
            "body": body,
        }

    def list_skills(self) -> List[Dict[str, Any]]:
        items = []
        if not os.path.isdir(self.root_dir):
            return items
        for name in sorted(os.listdir(self.root_dir)):
            path = os.path.join(self.root_dir, name, "SKILL.md")
            if os.path.isfile(path):
                try:
                    items.append(self._read(name))
                except Exception:
                    continue
        return items

    def get(self, skill_id: str) -> Dict[str, Any]:
        return self._read(skill_id)

    def create(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        skill_id = payload.get("id") or payload.get("name") or "skill"
        target = self._dir(skill_id)
        os.makedirs(target, exist_ok=True)
        md = _dump_skill_markdown(
            payload.get("name") or skill_id,
            payload.get("description") or "",
            payload.get("applies_to") or [],
            payload.get("body") or "",
        )
        with open(os.path.join(target, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(md)
        return self._read(os.path.basename(target))

    def update(self, skill_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        current = self._read(skill_id)
        current.update({k: v for k, v in payload.items() if v is not None and k != "id"})
        md = _dump_skill_markdown(
            current.get("name") or skill_id,
            current.get("description") or "",
            current.get("applies_to") or [],
            current.get("body") or "",
        )
        with open(os.path.join(self._dir(skill_id), "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(md)
        return self._read(skill_id)

    def delete(self, skill_id: str) -> None:
        import shutil
        target = self._dir(skill_id)
        if not os.path.isdir(target):
            raise FileNotFoundError(skill_id)
        shutil.rmtree(target)

    def match(self, user_text: str, limit: int = 3) -> List[Dict[str, Any]]:
        text = user_text or ""
        scored = []
        for skill in self.list_skills():
            blob = f"{skill.get('name','')} {skill.get('description','')} {skill.get('id','')}"
            tokens = [t for t in re.split(r"[\s,，、；;|/]+", blob) if t]
            score = sum(1 for token in tokens if token and token in text)
            if skill.get("name") and skill["name"] in text:
                score += 2
            if score > 0:
                scored.append((score, skill))
        scored.sort(key=lambda x: -x[0])
        return [s for _, s in scored[:limit]]


SKILL_PRIORITY_MARKER = "【Skill优先于MCP提示词】"


def skill_priority_instruction(skills: Optional[List[Dict[str, Any]]] = None) -> str:
    lines = [
        SKILL_PRIORITY_MARKER,
        "系统同时提供 Skill（技能包，后台「技能制作」）和 MCP 提示词模版（prompts/list，原样保留）。",
        "若 Skill 与 MCP 提示词都能解决同一问题，必须优先使用 Skill：按该 Skill 正文执行，输出 llm_generated_result、direct_answer 或 workflow_step。",
        "禁止在已有对应 Skill 时输出 invoke_prompt，或再去调用 prompts/get。",
        "仅当没有匹配的 Skill 时，才使用 MCP 提示词（如 gen_legal_doc_guide、contract_review_guide、judge_work_guide）。",
        "常见对应关系（左侧 Skill 优先）：法律文书生成指南 ↔ gen_legal_doc_guide；合同审查指南 ↔ contract_review_guide；法官断案指南 ↔ judge_work_guide。",
        "当前可用 Skill：",
    ]
    items = skills or []
    if not items:
        lines.append("- （暂无 Skill）")
    for skill in items:
        lines.append(
            f"- 《{skill.get('name')}》（{skill.get('id')}）：{skill.get('description')}"
        )
    return "\n".join(lines)


def ensure_skill_priority_in_prompt(
    system_prompt: str, skills: Optional[List[Dict[str, Any]]] = None
) -> str:
    text = system_prompt or ""
    if SKILL_PRIORITY_MARKER in text:
        text = text[: text.index(SKILL_PRIORITY_MARKER)].rstrip()
    return (text + "\n\n" + skill_priority_instruction(skills)).strip() + "\n"
