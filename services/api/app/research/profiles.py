from __future__ import annotations

from dataclasses import dataclass


DEFAULT_RESEARCH_PROFILE = "quick_onboarding"


@dataclass(frozen=True)
class ReportSectionSpec:
    """报告章节计划。

    heading 是最终 Markdown 的二级标题；question 说明这一节要回答的问题，
    既用于报告正文提示，也作为 LLM 报告增强的章节约束。
    """

    heading: str
    question: str


@dataclass(frozen=True)
class ResearchProfile:
    key: str
    label: str
    description: str
    audience: str
    core_question: str
    checklist: list[str]
    quality_weights: dict[str, float]
    verifier_checks: list[str]
    section_plan: list[ReportSectionSpec]
    required_evidence_types: list[str]
    focus_points: list[str]
    deliverable: str
    analysis_directives: list[str]

    @property
    def report_sections(self) -> list[str]:
        return [section.heading for section in self.section_plan]


PROFILE_REGISTRY: dict[str, ResearchProfile] = {
    "quick_onboarding": ResearchProfile(
        key="quick_onboarding",
        label="快速接手",
        description="帮助新人理解项目用途、启动方式、入口文件、核心模块和继续阅读路径。",
        audience="刚接手项目、需要尽快跑起来并读懂主流程的新成员",
        core_question="这个项目是做什么的？我该从哪里开始、按什么顺序读、怎么确认它能跑起来？",
        checklist=[
            "识别项目用途",
            "识别启动或主要入口",
            "识别依赖文件",
            "识别配置线索",
            "提供后续阅读路径",
            "列出无法判断的问题",
        ],
        quality_weights={
            "structure_completeness": 0.24,
            "evidence_coverage": 0.20,
            "codebase_coverage": 0.24,
            "risk_transparency": 0.10,
            "question_resolution": 0.08,
            "recommendation_confidence": 0.14,
        },
        verifier_checks=["has_entrypoint", "has_dependency_clues", "has_reading_path"],
        section_plan=[
            ReportSectionSpec("工程接手指南", "这次接手应该按哪几步完成，先做什么后做什么？"),
            ReportSectionSpec("启动与运行线索", "依赖、配置、入口和资料中的启动步骤分别在哪里？"),
            ReportSectionSpec("架构地图", "代码由哪些模块组成，模块之间大概是什么关系？"),
            ReportSectionSpec("新人接手路径", "第一次阅读应该按什么顺序打开哪些文件，理由是什么？"),
            ReportSectionSpec("30 分钟阅读路线", "时间有限时先看什么、看到什么程度、如何验证已经看懂？"),
            ReportSectionSpec("后续阅读路径", "完成第一次接手后，接下来应该深入哪些模块和材料？"),
            ReportSectionSpec("上手前必须确认的事项", "哪些缺失信息会直接影响接手判断，需要先问清楚？"),
        ],
        required_evidence_types=["source", "codebase", "readme"],
        focus_points=["项目定位与用途", "启动方式与依赖", "入口与核心模块", "最小验证路径", "接手风险"],
        deliverable="一份能在 30 分钟内完成首次启动和阅读的接手路线",
        analysis_directives=[
            "先确认项目用途和启动路径，再给阅读顺序。",
            "把可启动性拆成依赖、配置、入口、测试四类证据，缺哪类就明确说缺哪类。",
            "资料没有写出的启动命令不要补写，标为待确认并给出确认方式。",
        ],
    ),
    "architecture_understanding": ResearchProfile(
        key="architecture_understanding",
        label="架构理解",
        description="梳理模块关系、数据流、边界、外部依赖和扩展点。",
        audience="技术负责人、架构师或需要评估系统边界的资深工程师",
        core_question="系统由哪些部分组成、如何协作，边界和扩展点在哪里？",
        checklist=[
            "识别模块或目录边界",
            "识别主要入口和主流程线索",
            "识别外部依赖或集成点",
            "识别结构线索",
            "说明扩展点和耦合风险",
        ],
        quality_weights={
            "structure_completeness": 0.25,
            "evidence_coverage": 0.25,
            "codebase_coverage": 0.25,
            "risk_transparency": 0.10,
            "question_resolution": 0.05,
            "recommendation_confidence": 0.10,
        },
        verifier_checks=["has_module_boundaries", "has_entrypoint", "has_architecture_clues"],
        section_plan=[
            ReportSectionSpec("系统定位与边界", "系统在业务和技术上处于什么位置，哪些部分属于系统内部？"),
            ReportSectionSpec("模块边界", "有哪些顶层模块，各自的职责边界和依赖方向是什么？"),
            ReportSectionSpec("主流程与数据流", "一次典型请求或任务如何从入口流经核心模块并产生结果？"),
            ReportSectionSpec("外部依赖与集成", "系统依赖哪些框架、数据库、外部服务或配置？"),
            ReportSectionSpec("扩展点", "新增功能或替换组件时，应该改哪里、从哪里接入最稳？"),
            ReportSectionSpec("架构风险与验证缺口", "哪些架构判断只是静态推断，如何验证，风险集中在哪？"),
        ],
        required_evidence_types=["codebase", "dependency", "entrypoint"],
        focus_points=["系统定位与外部边界", "模块职责划分", "主流程与数据流", "依赖与集成点", "扩展点与耦合", "架构假设的验证缺口"],
        deliverable="一张可讨论的模块边界图、主流程假设和扩展风险清单",
        analysis_directives=[
            "严格区分扫描事实和静态推断，主流程只能标注为推断。",
            "不要声称看到了真实运行时调用链；说明验证缺口和验证方法。",
            "重点关注耦合点：入口、配置集中度、共享数据层和外部集成。",
        ],
    ),
    "extension_evaluation": ResearchProfile(
        key="extension_evaluation",
        label="二开评估",
        description="判断维护成本、改造风险、测试与配置复杂度。",
        audience="准备二次开发、集成或长期维护该项目的研发负责人",
        core_question="能不能改、改哪里、成本多大、怎么降低回归风险？",
        checklist=[
            "识别测试线索",
            "识别配置复杂度",
            "识别依赖和框架版本",
            "列出改造风险和缓解建议",
            "给出证据化二开判断",
        ],
        quality_weights={
            "structure_completeness": 0.12,
            "evidence_coverage": 0.24,
            "codebase_coverage": 0.16,
            "risk_transparency": 0.24,
            "question_resolution": 0.14,
            "recommendation_confidence": 0.10,
        },
        verifier_checks=["has_test_clues", "has_risk_register", "has_mitigation"],
        section_plan=[
            ReportSectionSpec("二开范围与改造面", "这次二开可能改动哪些入口、模块、配置和依赖？"),
            ReportSectionSpec("二开可行性", "在现有证据下，这个项目适合直接改、先做 POC，还是暂缓？"),
            ReportSectionSpec("改造风险", "改动会带来哪些兼容、回归、数据和协作风险，如何缓解？"),
            ReportSectionSpec("测试与配置复杂度", "现有测试能提供多少保护，配置和依赖会带来多少改造成本？"),
            ReportSectionSpec("分阶段落地建议", "如何把二开拆成 POC、回归和放量三个阶段推进？"),
            ReportSectionSpec("二开前必须补齐的证据", "正式开工前还缺哪些测试、文档或运行信息？"),
        ],
        required_evidence_types=["codebase", "test", "config"],
        focus_points=["改造范围", "测试保护", "配置与依赖约束", "兼容与回归风险", "分期落地"],
        deliverable="一份带风险与测试前提的二开可行性判断和分期建议",
        analysis_directives=[
            "没有测试保护时必须降低结论强度，明确写出回归成本。",
            "区分新增模块和修改核心流程，不要把新增说成低风险改造。",
            "给出可执行的分期方案：POC 验证点、回归范围、放量条件。",
        ],
    ),
    "teaching_breakdown": ResearchProfile(
        key="teaching_breakdown",
        label="教学拆解",
        description="拆成学习路径、章节、关键代码、难点和练习任务。",
        audience="课程设计者、讲师或需要把项目转为教学案例的工程师",
        core_question="这个项目适合讲什么、按什么顺序讲、难点在哪、学生练什么？",
        checklist=[
            "识别适合讲解的章节顺序",
            "列出关键代码文件",
            "说明学习难点和前置知识",
            "给出练习或验证任务",
            "标注教学材料风险",
        ],
        quality_weights={
            "structure_completeness": 0.25,
            "evidence_coverage": 0.20,
            "codebase_coverage": 0.15,
            "risk_transparency": 0.10,
            "question_resolution": 0.08,
            "recommendation_confidence": 0.22,
        },
        verifier_checks=["has_key_files", "has_learning_path", "has_exercises"],
        section_plan=[
            ReportSectionSpec("教学目标与受众", "这门课面向谁，学完后应该能做什么？"),
            ReportSectionSpec("课程章节建议", "课程分成哪几章，每章讲什么、对应哪些文件？"),
            ReportSectionSpec("关键代码讲解顺序", "课堂上应该按什么顺序带学生读代码？"),
            ReportSectionSpec("学习难点与前置知识", "学生最容易卡在哪里，需要提前补什么？"),
            ReportSectionSpec("练习任务", "每章配套什么可验证的练习，如何判断学生做对了？"),
            ReportSectionSpec("教学材料缺口", "要把它变成课程，还缺哪些背景、示例和测试材料？"),
        ],
        required_evidence_types=["codebase", "entrypoint", "test"],
        focus_points=["项目导入素材", "章节拆分", "关键代码讲解顺序", "前置知识与难点", "练习与验收", "教学材料缺口"],
        deliverable="一份可直接排课的章节大纲、代码讲解顺序和练习任务",
        analysis_directives=[
            "每一章都必须能落到具体文件或模块，不要只给抽象教学法。",
            "练习任务必须有可验证结果：能运行、能改测试或能画出结构。",
            "不要虚构课程时长、学生水平和教学效果；资料不足时写入教学材料缺口。",
        ],
    ),
    "delivery_acceptance": ResearchProfile(
        key="delivery_acceptance",
        label="交付验收",
        description="检查完整性、可启动性、文档缺口和待确认项。",
        audience="验收方、项目经理或准备接手交付物的团队负责人",
        core_question="交付物是否完整、能否启动、文档和运维是否足够、还有哪些待确认项？",
        checklist=[
            "识别项目完整性线索",
            "识别启动或配置文档",
            "识别缺失文档或缺口",
            "列出待确认问题",
            "给出交付可接手结论",
        ],
        quality_weights={
            "structure_completeness": 0.14,
            "evidence_coverage": 0.24,
            "codebase_coverage": 0.12,
            "risk_transparency": 0.22,
            "question_resolution": 0.18,
            "recommendation_confidence": 0.10,
        },
        verifier_checks=["has_runbook_clues", "has_open_questions", "has_delivery_readiness_summary"],
        section_plan=[
            ReportSectionSpec("交付范围", "本次交付包含哪些代码、资料和运行资产？"),
            ReportSectionSpec("交付完整性", "代码、依赖、配置、测试和文档是否齐全？"),
            ReportSectionSpec("可启动性", "拿到交付物的人能否按资料完成一次启动？"),
            ReportSectionSpec("文档与运维缺口", "README、部署说明、环境配置和运维信息缺什么？"),
            ReportSectionSpec("验收问题清单", "验收会上必须确认的问题有哪些？"),
            ReportSectionSpec("验收结论", "这批交付是通过、有条件通过，还是不通过？"),
        ],
        required_evidence_types=["source", "readme", "config"],
        focus_points=["交付范围", "完整性", "可启动性", "文档与运维", "验收问题"],
        deliverable="一份可直接用于验收会议的核对清单和结论",
        analysis_directives=[
            "以核对清单为主，每一项都给出通过、缺失或无法判断。",
            "缺一项就说明它会如何影响启动、维护或验收，不要笼统说“需完善”。",
            "最终结论只能使用“通过 / 有条件通过 / 不通过”，并列出条件。",
        ],
    ),
}


def list_research_profiles() -> list[ResearchProfile]:
    return list(PROFILE_REGISTRY.values())


def get_research_profile(key: str | None) -> ResearchProfile:
    return PROFILE_REGISTRY.get(key or DEFAULT_RESEARCH_PROFILE) or PROFILE_REGISTRY[DEFAULT_RESEARCH_PROFILE]


def research_profile_exists(key: str) -> bool:
    return key in PROFILE_REGISTRY
