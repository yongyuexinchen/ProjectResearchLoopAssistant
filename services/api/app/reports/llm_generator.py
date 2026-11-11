from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMReportValidation:
    accepted: bool
    normalized: dict[str, Any] | None = None
    messages: list[str] = field(default_factory=list)


MAX_EXECUTIVE_SUMMARY_LENGTH = 2000
MAX_SECTION_HEADING_LENGTH = 120
MAX_SECTION_BODY_LENGTH = 4000
MAX_REPORT_SECTIONS = 8


def _coerce_report_payload(payload: Any) -> Any:
    """兼容模型直接返回单个 section 的常见偏差。

    约束仍由后续校验执行；这里只把“一个 section + 可能的 summary”包装成
    报告结构，避免整段可用解读因为顶层少了一层 sections 而被丢弃。
    """

    if not isinstance(payload, dict):
        return payload
    if isinstance(payload.get("sections"), list):
        return payload
    section = payload.get("section")
    if isinstance(section, dict):
        section = dict(section)
    elif {"heading", "body"}.issubset(payload.keys()):
        section = {
            "heading": payload.get("heading"),
            "body": payload.get("body"),
            "evidence_refs": payload.get("evidence_refs", []),
        }
    else:
        return payload
    if not payload.get("executive_summary"):
        body = section.get("body")
        payload = {**payload, "executive_summary": body if isinstance(body, str) else ""}
    return {**payload, "sections": [section]}


def validate_llm_report_sections(payload: Any, *, allowed_evidence_refs: set[str]) -> LLMReportValidation:
    """校验 LLM 报告增强片段，只允许引用既有 EvidenceItem.id。

    LLM 段落只是 advisory：它可以改善表达和解读，但必须被 evidence refs 约束，
    不能凭空新增证据，也不能影响确定性 verifier 的状态与结论。
    """

    messages: list[str] = []
    payload = _coerce_report_payload(payload)
    if not isinstance(payload, dict):
        return LLMReportValidation(False, messages=["payload must be an object"])

    executive_summary = _required_string(
        payload.get("executive_summary"),
        "executive_summary",
        messages,
        max_length=MAX_EXECUTIVE_SUMMARY_LENGTH,
    )

    sections_value = payload.get("sections")
    if not isinstance(sections_value, list):
        messages.append("sections must be a list")
        sections_value = []
    elif len(sections_value) > MAX_REPORT_SECTIONS:
        messages.append(f"sections must include at most {MAX_REPORT_SECTIONS} items")

    normalized_sections: list[dict[str, Any]] = []
    for index, section in enumerate(sections_value):
        if not isinstance(section, dict):
            messages.append(f"sections[{index}] must be an object")
            continue

        heading = _required_string(
            section.get("heading"),
            f"sections[{index}].heading",
            messages,
            max_length=MAX_SECTION_HEADING_LENGTH,
        )
        body = _required_string(
            section.get("body"),
            f"sections[{index}].body",
            messages,
            max_length=MAX_SECTION_BODY_LENGTH,
        )
        refs_value = section.get("evidence_refs")
        if not isinstance(refs_value, list):
            messages.append(f"sections[{index}].evidence_refs must be a list")
            refs_value = []

        normalized_refs: list[str] = []
        for ref_index, ref in enumerate(refs_value):
            clean_ref = _clean_string(ref) if isinstance(ref, str) else ""
            if not clean_ref:
                messages.append(f"sections[{index}].evidence_refs[{ref_index}] must be a non-empty string")
                continue
            if clean_ref not in allowed_evidence_refs:
                messages.append(f"unknown evidence ref: {clean_ref}")
                continue
            normalized_refs.append(clean_ref)

        if not normalized_refs:
            messages.append(f"sections[{index}].evidence_refs must include at least one known evidence ref")

        if heading and body and normalized_refs:
            normalized_sections.append(
                {
                    "heading": heading,
                    "body": body,
                    "evidence_refs": normalized_refs,
                }
            )

    if not normalized_sections:
        messages.append("sections must include at least one evidence-backed section")

    accepted = not messages
    normalized = {"executive_summary": executive_summary, "sections": normalized_sections} if accepted else None
    return LLMReportValidation(accepted=accepted, normalized=normalized, messages=messages)


def render_llm_sections_markdown(base_markdown: str, normalized: dict[str, Any]) -> str:
    """兼容旧调用：没有章节计划时，把所有模型内容追加到报告末尾。"""

    return merge_llm_report_markdown(base_markdown, normalized)


def merge_llm_report_markdown(
    base_markdown: str,
    normalized: dict[str, Any],
    *,
    planned_headings: list[str] | tuple[str, ...] = (),
) -> str:
    """把模型补充内容合并进对应章节。

    模型段落仍然只是 advisory：不会删除或覆盖确定性正文，只在匹配章节末尾
    增加「模型补充解读」。无法匹配章节计划的内容放入「智能报告增强」，
    确保没有内容被静默丢弃。
    """

    planned = {
        _heading_key(heading): heading
        for heading in planned_headings
        if _clean_string(heading)
    }
    executive_summary = _clean_string(normalized.get("executive_summary"))
    seen_bodies = {_body_key(executive_summary)} if executive_summary else set()
    matched: dict[str, list[dict[str, Any]]] = {}
    unmatched: list[dict[str, Any]] = []
    for section in normalized.get("sections", []):
        if not isinstance(section, dict):
            continue
        heading = _clean_string(section.get("heading"))
        body = _clean_string(section.get("body"))
        refs = [_clean_string(ref) for ref in section.get("evidence_refs", [])]
        refs = [ref for ref in refs if ref]
        if not heading or not body or not refs:
            continue
        body_key = _body_key(body)
        if body_key in seen_bodies:
            continue
        seen_bodies.add(body_key)
        target = planned.get(_heading_key(heading))
        if target:
            matched.setdefault(target, []).append({"heading": heading, "body": body, "refs": refs})
        else:
            unmatched.append({"heading": heading, "body": body, "refs": refs})

    blocks = _split_markdown_blocks(base_markdown)
    output: list[str] = []
    summary_inserted = False
    for heading, lines in blocks:
        output.extend(lines)
        supplements: list[dict[str, Any]] = []
        if heading == "执行摘要" and executive_summary:
            supplements.append({"heading": "执行摘要", "body": executive_summary, "refs": []})
            summary_inserted = True
        supplements.extend(matched.get(heading or "", []))
        for supplement in supplements:
            output.extend(["", "### 模型补充解读", "", supplement["body"]])
            if supplement["refs"]:
                output.extend(["", f"证据引用：{', '.join(f'`{ref}`' for ref in supplement['refs'])}"])
        output.append("")

    if unmatched or (executive_summary and not summary_inserted):
        output.extend(["", "## 智能报告增强", ""])
        if executive_summary and not summary_inserted:
            output.extend([executive_summary, ""])
        for section in unmatched:
            output.extend(
                [
                    f"### {section['heading']}",
                    "",
                    section["body"],
                    "",
                    f"证据引用：{', '.join(f'`{ref}`' for ref in section['refs'])}",
                    "",
                ]
            )

    return "\n".join(output).rstrip() + "\n"


def _split_markdown_blocks(markdown: str) -> list[tuple[str | None, list[str]]]:
    blocks: list[tuple[str | None, list[str]]] = []
    heading: str | None = None
    lines: list[str] = []
    for line in markdown.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        if line.startswith("## "):
            if lines:
                blocks.append((heading, _strip_trailing_blank(lines)))
                lines = []
            heading = line[3:].strip()
        lines.append(line)
    if lines:
        blocks.append((heading, _strip_trailing_blank(lines)))
    return blocks


def _strip_trailing_blank(lines: list[str]) -> list[str]:
    result = list(lines)
    while result and not result[-1].strip():
        result.pop()
    return result


def _heading_key(value: str) -> str:
    cleaned = _clean_string(value).lower().lstrip("#").strip()
    cleaned = cleaned.replace("：", "").replace(":", "").replace(" ", "").replace("　", "")
    return cleaned


def _body_key(value: str) -> str:
    return "".join(_clean_string(value).split()).lower()


def _clean_string(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("\r\n", "\n").replace("\r", "\n").strip()


def _required_string(value: Any, field_name: str, messages: list[str], *, max_length: int) -> str:
    if not isinstance(value, str):
        messages.append(f"{field_name} must be a non-empty string")
        return ""

    cleaned = _clean_string(value)
    if not cleaned:
        messages.append(f"{field_name} must be a non-empty string")
        return ""
    if len(cleaned) > max_length:
        messages.append(f"{field_name} must be at most {max_length} characters")
        return ""
    return cleaned
