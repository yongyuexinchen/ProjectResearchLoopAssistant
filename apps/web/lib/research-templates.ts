// 与后端 services/api/app/research/profiles.py 的受众、核心问题、交付物和章节计划保持一致。
export type ResearchTemplateKey =
  | "quick_onboarding"
  | "architecture_understanding"
  | "extension_evaluation"
  | "teaching_breakdown"
  | "delivery_acceptance";

export type ResearchTemplate = {
  key: ResearchTemplateKey;
  label: string;
  description: string;
  audience: string;
  coreQuestion: string;
  deliverable: string;
  reportOutline: string[];
  focusPoints: string[];
};

export const researchTemplates: ResearchTemplate[] = [
  {
    key: "quick_onboarding",
    label: "快速接手",
    description: "帮新人快速理解项目用途、启动方式、入口文件、核心模块和继续阅读路径。",
    audience: "刚接手项目、需要尽快跑起来的新成员",
    coreQuestion: "这个项目是做什么的？我该从哪里开始、按什么顺序读、怎么确认它能跑起来？",
    deliverable: "30 分钟接手路线 + 启动与阅读顺序",
    reportOutline: [
      "项目速览：是什么、为什么做、有什么特点",
      "工程接手指南",
      "启动与运行线索",
      "架构地图",
      "新人接手路径",
      "30 分钟阅读路线",
      "后续阅读路径",
      "上手前必须确认的事项",
    ],
    focusPoints: ["项目定位与用途", "启动方式与依赖", "入口与核心模块", "最小验证路径", "接手风险"],
  },
  {
    key: "architecture_understanding",
    label: "架构理解",
    description: "面向技术负责人，梳理模块关系、数据流、外部依赖、边界和扩展点。",
    audience: "技术负责人、架构师或需要评估系统边界的资深工程师",
    coreQuestion: "系统由哪些部分组成、如何协作，边界和扩展点在哪里？",
    deliverable: "模块边界、主流程假设、扩展与风险清单",
    reportOutline: [
      "项目速览：是什么、为什么做、有什么特点",
      "系统定位与边界",
      "模块边界",
      "主流程与数据流",
      "外部依赖与集成",
      "扩展点",
      "架构风险与验证缺口",
    ],
    focusPoints: ["系统定位与外部边界", "模块职责划分", "主流程与数据流", "依赖与集成点", "扩展点与耦合"],
  },
  {
    key: "extension_evaluation",
    label: "二开评估",
    description: "判断项目是否适合继续开发、改造或集成，关注维护成本和改造风险。",
    audience: "准备二次开发、集成或长期维护该项目的研发负责人",
    coreQuestion: "能不能改、改哪里、成本多大、怎么降低回归风险？",
    deliverable: "二开可行性判断 + 分期落地建议",
    reportOutline: [
      "项目速览：是什么、为什么做、有什么特点",
      "二开范围与改造面",
      "二开可行性",
      "改造风险",
      "测试与配置复杂度",
      "分阶段落地建议",
      "二开前必须补齐的证据",
    ],
    focusPoints: ["改造范围", "测试保护", "配置与依赖约束", "兼容与回归风险", "分期落地"],
  },
  {
    key: "teaching_breakdown",
    label: "教学拆解",
    description: "把项目拆成学习路径、章节结构、关键代码和难点提示。",
    audience: "课程设计者、讲师或需要把项目转为教学案例的工程师",
    coreQuestion: "这个项目适合讲什么、按什么顺序讲、难点在哪、学生练什么？",
    deliverable: "章节大纲 + 代码讲解顺序 + 练习任务",
    reportOutline: [
      "项目速览：是什么、为什么做、有什么特点",
      "教学目标与受众",
      "课程章节建议",
      "关键代码讲解顺序",
      "学习难点与前置知识",
      "练习任务",
      "教学材料缺口",
    ],
    focusPoints: ["项目导入素材", "章节拆分", "关键代码讲解顺序", "前置知识与难点", "练习与验收"],
  },
  {
    key: "delivery_acceptance",
    label: "交付验收",
    description: "检查交付项目是否完整、可启动、可维护，并列出待确认问题。",
    audience: "验收方、项目经理或准备接手交付物的团队负责人",
    coreQuestion: "交付物完整吗、能启动吗、文档够吗、还有哪些待确认项？",
    deliverable: "验收核对清单 + 通过条件",
    reportOutline: [
      "项目速览：是什么、为什么做、有什么特点",
      "交付范围",
      "交付完整性",
      "可启动性",
      "文档与运维缺口",
      "验收问题清单",
      "验收结论",
    ],
    focusPoints: ["交付范围", "完整性", "可启动性", "文档与运维", "验收问题"],
  },
];

export function templateGoal(templateKey: string, userGoal: string): string {
  const template = researchTemplates.find((item) => item.key === templateKey) ?? researchTemplates[0];
  const trimmed = userGoal.trim();
  return trimmed || template.description;
}
