"""按调研方式补充确定性的发现、风险和建议。

这一步不调用模型：即使模型不可用，五类调研也能得到不同的问题清单和结论骨架。
所有新增条目都必须引用已有证据，避免把档位指令写成尚未验证的事实。
"""

from __future__ import annotations

from typing import Any

from app.reports.project_brief import ProjectBrief, module_role, top_level_modules
from app.tools.code_scan_tools import infer_entrypoints, is_valid_entrypoint_path


def build_profile_artifacts(
    *,
    profile_key: str,
    project: dict[str, Any],
    brief: ProjectBrief,
    inventory: dict[str, Any],
    refs: dict[str, list[str]],
    existing_risk_titles: set[str],
) -> dict[str, list[dict[str, Any]]]:
    findings: list[dict[str, Any]] = []
    risks: list[dict[str, Any]] = []
    recommendations: list[dict[str, Any]] = []

    codebase_maps = as_list(inventory.get("codebase_maps"))
    snapshots = as_list(inventory.get("snapshots"))
    entrypoints = entrypoints_for(codebase_maps)
    dependencies = collect(codebase_maps, "dependency_files")
    configs = collect(codebase_maps, "config_files")
    tests = collect(codebase_maps, "test_files")
    modules = all_modules(codebase_maps)
    codebase_ref = first_ref(refs.get("codebase"))
    readme_ref = first_ref(refs.get("readme")) or first_ref(refs.get("snapshot")) or codebase_ref
    primary_ref = readme_ref or codebase_ref

    if not primary_ref:
        return {"findings": findings, "risks": risks, "recommendations": recommendations}

    if brief.positioning is not None:
        findings.append(
            finding(
                title=f"项目定位：{shorten(brief.positioning.text, 70)}",
                summary=brief.positioning.text,
                category="project_positioning",
                confidence=85 if brief.positioning.basis == "资料原文" else 60,
                evidence_ref=readme_ref or codebase_ref or primary_ref,
                metadata={
                    "profile": profile_key,
                    "basis": brief.positioning.basis,
                    "source": brief.positioning.source,
                },
            )
        )

    if profile_key == "quick_onboarding":
        if entrypoints:
            findings.append(
                finding(
                    title="接手入口已定位",
                    summary=f"建议从 {', '.join(entrypoints[:4])} 开始，先确认启动参数和主流程调用。",
                    category="onboarding",
                    confidence=82,
                    evidence_ref=codebase_ref or primary_ref,
                    metadata={"profile": profile_key},
                )
            )
        if readme_ref and first_text(readme_excerpt(codebase_maps)):
            findings.append(
                finding(
                    title="已具备项目说明材料",
                    summary="README 提供了项目用途或启动线索，可作为第一次接手的入口材料。",
                    category="reading_path",
                    confidence=80,
                    evidence_ref=readme_ref,
                    metadata={"profile": profile_key},
                )
            )
        if not first_text(readme_excerpt(codebase_maps)):
            risks.append(
                risk(
                    title="缺少 README，接手成本不可控",
                    summary="没有项目说明材料，新人无法从资料确认用途、启动方式和运行前提。",
                    severity="medium",
                    mitigation="先向项目方索取 README 或启动说明，再安排交接。",
                    evidence_ref=codebase_ref or primary_ref,
                    existing=existing_risk_titles,
                    metadata={"profile": profile_key},
                )
            )
        recommendations.append(
            recommendation(
                summary="按 30 分钟接手路线完成第一次启动和阅读",
                rationale="快速接手档位优先建立可运行认知，再按模块深入，避免一开始陷入实现细节。",
                confidence=82,
                next_steps=[
                    "读 README 的简介与启动说明。",
                    f"打开入口 {', '.join(entrypoints[:3]) if entrypoints else '并确认启动入口'}，只追一次主流程。",
                    "运行一个测试或做一次最小请求，记录失败点。",
                ],
                metadata={"profile": profile_key},
            )
        )

    elif profile_key == "architecture_understanding":
        if modules:
            findings.append(
                finding(
                    title="模块边界线索",
                    summary="顶层模块：" + "、".join(f"{name}({count})" for name, count in modules[:6]) + "。",
                    category="architecture",
                    confidence=78,
                    evidence_ref=codebase_ref or primary_ref,
                    metadata={"profile": profile_key, "modules": [name for name, _ in modules[:6]]},
                )
            )
        if entrypoints and (dependencies or configs):
            findings.append(
                finding(
                    title="入口与装配线索",
                    summary=(
                        f"入口 {', '.join(entrypoints[:3])} 通过 "
                        f"{', '.join([*dependencies[:2], *configs[:2]])} 完成配置与依赖装配。"
                    ),
                    category="architecture",
                    confidence=76,
                    evidence_ref=codebase_ref or primary_ref,
                    metadata={"profile": profile_key},
                )
            )
        if codebase_maps:
            risks.append(
                risk(
                    title="主流程未经过运行时验证",
                    summary="当前主流程和数据流来自静态依赖推断，没有日志或追踪证明真实调用链。",
                    severity="medium",
                    mitigation="用一次真实请求或启动日志抽样验证入口到核心模块的调用链。",
                    evidence_ref=codebase_ref or primary_ref,
                    existing=existing_risk_titles,
                    metadata={"profile": profile_key},
                )
            )
        recommendations.append(
            recommendation(
                summary="先验证主流程，再评估扩展点",
                rationale="架构理解档位的结论是静态推断，只有经过一次运行时验证后才能作为改造依据。",
                confidence=76,
                next_steps=[
                    "打开入口和配置，画出入参、配置和依赖关系。",
                    "用一次真实请求或启动日志验证主流程。",
                    "再按模块边界评估扩展点和耦合风险。",
                ],
                metadata={"profile": profile_key},
            )
        )

    elif profile_key == "extension_evaluation":
        if modules:
            findings.append(
                finding(
                    title="候选改造面",
                    summary=(
                        "候选模块：" + "、".join(name for name, _ in modules[:5])
                        + f"；入口 {', '.join(entrypoints[:3]) if entrypoints else '未识别'}。"
                    ),
                    category="extension",
                    confidence=74,
                    evidence_ref=codebase_ref or primary_ref,
                    metadata={"profile": profile_key},
                )
            )
        if tests:
            findings.append(
                finding(
                    title="已有测试保护线索",
                    summary=f"发现 {len(tests)} 个测试文件，可作为二开回归的起点；覆盖率仍需人工确认。",
                    category="extension",
                    confidence=78,
                    evidence_ref=codebase_ref or primary_ref,
                    metadata={"profile": profile_key},
                )
            )
        else:
            risks.append(
                risk(
                    title="缺少测试保护，二开回归成本高",
                    summary="没有自动化测试，任何改动都只能依赖手工回归，难以判断是否破坏现有行为。",
                    severity="high",
                    mitigation="先补一条可重复运行的 smoke test，再开始改核心路径。",
                    evidence_ref=codebase_ref or primary_ref,
                    existing=existing_risk_titles,
                    metadata={"profile": profile_key},
                )
            )
        risks.append(
            risk(
                title="改造影响面无法从静态扫描确认",
                summary="当前只能看到目录和依赖，无法确认模块间的真实调用、共享状态和外部副作用。",
                severity="medium",
                mitigation="先用 POC 隔离验证，再逐步扩大改动范围。",
                evidence_ref=codebase_ref or primary_ref,
                existing=existing_risk_titles,
                metadata={"profile": profile_key},
            )
        )
        recommendations.append(
            recommendation(
                summary="按 POC → 回归 → 放量三阶段推进二开",
                rationale="缺少运行时验证时，分期可以把风险限制在最小改动面内。",
                confidence=72 if not tests else 80,
                next_steps=[
                    "选择一个模块做隔离 POC，不碰共享数据层。",
                    "补 1-3 个回归用例，确认旧行为不变。",
                    "补日志、监控和回滚方案后再放量。",
                ],
                metadata={"profile": profile_key},
            )
        )

    elif profile_key == "teaching_breakdown":
        if modules or entrypoints:
            mainline = "、".join(name for name, _ in modules[:4]) or "入口到核心模块"
            findings.append(
                finding(
                    title="教学主线已形成",
                    summary=f"可以按“项目导入 → 运行入口 → {mainline} → 测试/改造”组织课程。",
                    category="learning_path",
                    confidence=80,
                    evidence_ref=codebase_ref or primary_ref,
                    metadata={"profile": profile_key},
                )
            )
        if entrypoints:
            findings.append(
                finding(
                    title="关键代码样例已定位",
                    summary=f"优先用 {', '.join(entrypoints[:3])} 作为课堂讲解入口。",
                    category="teaching",
                    confidence=80,
                    evidence_ref=codebase_ref or primary_ref,
                    metadata={"profile": profile_key},
                )
            )
        if tests:
            findings.append(
                finding(
                    title="练习与验证素材已具备",
                    summary=f"发现 {len(tests)} 个测试文件，可作为练习的预期行为和判分依据。",
                    category="practice_exercise",
                    confidence=78,
                    evidence_ref=codebase_ref or primary_ref,
                    metadata={"profile": profile_key},
                )
            )
        recommendations.append(
            recommendation(
                summary="按章节顺序授课，并用可运行练习收束",
                rationale="教学拆解档位需要先建立全貌，再按模块讲解，最后用测试或小改动验证学习效果。",
                confidence=80,
                next_steps=[
                    "用项目速览做课程导入：是什么、为什么、有什么特点。",
                    "按入口 → 模块 → 测试的顺序安排讲解。",
                    "每章配一个可验证练习，并说明判分标准。",
                ],
                metadata={"profile": profile_key},
            )
        )

    elif profile_key == "delivery_acceptance":
        missing = delivery_missing(codebase_maps, snapshots)
        findings.append(
            finding(
                title="交付完整性快照",
                summary=(
                    f"已具备：{'、'.join(delivery_present(codebase_maps, snapshots)) or '无'}；"
                    f"缺口：{'、'.join(missing) or '未发现结构性缺口'}。"
                ),
                category="delivery_readiness",
                confidence=84,
                evidence_ref=codebase_ref or primary_ref,
                metadata={"profile": profile_key, "missing": missing},
            )
        )
        risk_specs = [
            (
                "readme",
                "缺少 README/交付说明",
                "接手方无法确认项目用途、启动方式和运行前提。",
                "high",
                "交付前补齐 README：用途、依赖、配置、启动和验收步骤。",
            ),
            (
                "entrypoint",
                "缺少可核对入口文件",
                "无法证明交付物存在可启动入口，验收只能停留在文档层面。",
                "high",
                "补充入口文件或明确启动命令，并现场演示一次启动。",
            ),
            (
                "dependency",
                "缺少依赖清单",
                "无法核对安装步骤和版本兼容性，部署环境可能无法复现。",
                "medium",
                "补充依赖清单或锁文件，并固定版本。",
            ),
            (
                "config",
                "缺少运行配置",
                "环境变量和默认值不明确，接手方容易在配置阶段卡住。",
                "medium",
                "提供配置样例和环境变量说明，敏感值用占位符。",
            ),
        ]
        for key, title, summary, severity, mitigation in risk_specs:
            if key in missing:
                risks.append(
                    risk(
                        title=title,
                        summary=summary,
                        severity=severity,
                        mitigation=mitigation,
                        evidence_ref=codebase_ref or primary_ref,
                        existing=existing_risk_titles,
                        metadata={"profile": profile_key},
                    )
                )
        recommendations.append(
            recommendation(
                summary="按验收清单逐项确认后再签字",
                rationale="交付验收档位的核心是完整性、可启动性和文档缺口，不能用分析结论替代验收动作。",
                confidence=84,
                next_steps=[
                    "对照「交付完整性」核对代码、依赖、配置、测试和文档。",
                    "在干净环境按 README 实际启动一次。",
                    "把文档与运维缺口写入验收条件，明确责任人和截止时间。",
                ],
                metadata={"profile": profile_key},
            )
        )

    return {
        "findings": findings,
        "risks": [item for item in risks if item],
        "recommendations": recommendations,
    }


def finding(
    *,
    title: str,
    summary: str,
    category: str,
    confidence: int,
    evidence_ref: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    return {
        "title": title,
        "summary": summary,
        "category": category,
        "impact_level": "medium",
        "confidence": confidence,
        "evidence_refs": [evidence_ref],
        "metadata": metadata,
    }


def risk(
    *,
    title: str,
    summary: str,
    severity: str,
    mitigation: str,
    evidence_ref: str,
    existing: set[str],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    if title in existing:
        return {}
    existing.add(title)
    return {
        "title": title,
        "summary": summary,
        "severity": severity,
        "mitigation": mitigation,
        "evidence_refs": [evidence_ref],
        "metadata": metadata,
    }


def recommendation(
    *,
    summary: str,
    rationale: str,
    confidence: int,
    next_steps: list[str],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    return {
        "summary": summary,
        "rationale": rationale,
        "confidence": confidence,
        "next_steps": next_steps,
        "metadata": metadata,
    }


def delivery_present(codebase_maps: list[Any], snapshots: list[Any]) -> list[str]:
    present = []
    if snapshots:
        present.append("采集快照")
    if first_text(readme_excerpt(codebase_maps)):
        present.append("README")
    if collect(codebase_maps, "entrypoint_files"):
        present.append("入口文件")
    if collect(codebase_maps, "dependency_files"):
        present.append("依赖清单")
    if collect(codebase_maps, "config_files"):
        present.append("运行配置")
    if collect(codebase_maps, "test_files"):
        present.append("测试")
    return present


def delivery_missing(codebase_maps: list[Any], snapshots: list[Any]) -> list[str]:
    missing = []
    if not first_text(readme_excerpt(codebase_maps)):
        missing.append("readme")
    if codebase_maps and not collect(codebase_maps, "entrypoint_files"):
        missing.append("entrypoint")
    if codebase_maps and not collect(codebase_maps, "dependency_files"):
        missing.append("dependency")
    if codebase_maps and not collect(codebase_maps, "config_files"):
        missing.append("config")
    if not codebase_maps:
        missing.extend(["entrypoint", "dependency", "config"])
    return missing


def collect(codebase_maps: list[Any], key: str) -> list[str]:
    values: list[str] = []
    for codebase_map in codebase_maps:
        values.extend(
            str(value)
            for value in as_list(value_of(codebase_map, key, []))
            if str(value).strip()
        )
    return values


def entrypoints_for(codebase_maps: list[Any]) -> list[str]:
    values = [
        path
        for path in collect(codebase_maps, "entrypoint_files")
        if is_valid_entrypoint_path(path)
    ]
    if values:
        return unique(values)
    inferred: list[str] = []
    for codebase_map in codebase_maps:
        paths = {
            str(value_of(item, "path", item))
            for item in as_list(value_of(codebase_map, "file_tree", []))
            if value_of(item, "kind", "file") == "file"
        }
        inferred.extend(
            path
            for path in infer_entrypoints(paths, as_list(value_of(codebase_map, "tech_stack", [])))
            if is_valid_entrypoint_path(path)
        )
    return unique(inferred)


def readme_excerpt(codebase_maps: list[Any]) -> list[str]:
    return [str(value_of(codebase_map, "readme_excerpt", "")) for codebase_map in codebase_maps]


def all_modules(codebase_maps: list[Any]) -> list[tuple[str, int]]:
    modules: dict[str, int] = {}
    for codebase_map in codebase_maps:
        for name, count in top_level_modules(value_of(codebase_map, "file_tree", []), code_only=True):
            modules[name] = modules.get(name, 0) + count
    return sorted(modules.items(), key=lambda pair: (-pair[1], pair[0]))


def first_ref(values: Any) -> str:
    for value in as_list(values):
        if str(value).strip():
            return str(value)
    return ""


def unique(values: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in as_list(values):
        item = str(value).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def first_text(values: Any) -> str:
    for value in values:
        if str(value).strip():
            return str(value)
    return ""


def shorten(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, (str, bytes, dict)):
        return [value]
    try:
        return list(value)
    except TypeError:
        return [value]


def value_of(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)
