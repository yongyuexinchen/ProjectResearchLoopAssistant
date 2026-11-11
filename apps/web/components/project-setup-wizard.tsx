"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { researchTemplates, templateGoal, type ResearchTemplateKey } from "@/lib/research-templates";
import { detectSourceType, sourceTypeMismatch, type SourceType } from "@/lib/source-detect";
import type { LlmProfile, RunEnqueue } from "@/types/project";
import "./project-setup-wizard.css";

type SourceDraft = { id: number; source_type: SourceType; uri: string };
type Readiness =
  | { status: "loading" }
  | { status: "error" }
  | { status: "loaded"; profiles: Array<Pick<LlmProfile, "task_type" | "model" | "configured" | "enabled">>; provider: { configured: boolean; model: string } };

const steps = [
  { title: "项目目标", caption: "告诉我们要研究什么" },
  { title: "添加资料", caption: "代码、文档或网页" },
  { title: "调研方式", caption: "选择关注的方向" },
  { title: "确认并启动", caption: "其余交给 Loop" },
];

const sourceOptions: Array<{ value: SourceType; label: string; placeholder: string; hint: string }> = [
  { value: "local_directory", label: "本地项目目录", placeholder: "例如 E:\\projects\\my-project", hint: "填写运行服务所在电脑可访问的目录完整路径，自动扫描代码与文档。" },
  { value: "github_repo", label: "GitHub 仓库", placeholder: "https://github.com/owner/repository", hint: "填写公开仓库的主页地址，暂不支持私有仓库、分支页或文件页。" },
  { value: "web_url", label: "网页链接", placeholder: "https://example.com/docs", hint: "填写 http:// 或 https:// 开头的网页地址。" },
  { value: "local_file", label: "本地文档文件", placeholder: "例如 E:\\docs\\README.md", hint: "填写运行服务所在电脑可访问的文件完整路径；这里无需上传文件。" },
];

const taskLabels = [
  { key: "analyzer", label: "智能分析" },
  { key: "verifier", label: "智能复核" },
  { key: "report", label: "报告生成" },
];

function sourceError(source: SourceDraft): string | null {
  const value = source.uri.trim();
  if (!value) return "请填写资料的路径或链接。";
  const mismatch = sourceTypeMismatch(source.source_type, value);
  if (mismatch) return mismatch;
  if (source.source_type === "local_directory" || source.source_type === "local_file") return null;
  try {
    const url = new URL(value);
    if (!["http:", "https:"].includes(url.protocol) || !url.hostname || url.username || url.password) {
      return "请填写有效的 http:// 或 https:// 链接，不要在链接中包含账号或密钥。";
    }
    if (source.source_type === "github_repo") {
      const segments = url.pathname.split("/").filter(Boolean);
      if (url.protocol !== "https:" || url.hostname.toLowerCase() !== "github.com" || url.port || segments.length !== 2 || url.search || url.hash) {
        return "请填写 https://github.com/用户名/仓库名 格式的仓库主页地址。";
      }
    }
    return null;
  } catch {
    return "链接格式不正确，请填写完整的网页或仓库地址。";
  }
}

function apiErrorMessage(body: unknown, status: number): string {
  const fallback = `启动失败（${status}），请稍后重试。`;
  if (typeof body === "string") return body || fallback;
  if (!body || typeof body !== "object") return fallback;
  const detail = "detail" in body ? body.detail : "message" in body ? body.message : null;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const labels: Record<string, string> = { name: "项目名称", topic: "调研主题", sources: "资料", uri: "路径或链接", source_type: "资料类型", max_turns: "最大轮数", research_profile: "调研模板" };
    const messages = detail.map((entry: unknown) => {
      if (typeof entry === "string") return entry;
      if (!entry || typeof entry !== "object" || !("msg" in entry)) return "请检查填写的信息。";
      const location = "loc" in entry && Array.isArray(entry.loc)
        ? entry.loc.filter((part: unknown) => part !== "body").map((part: unknown) => typeof part === "number" ? `第 ${part + 1} 项` : labels[String(part)] ?? String(part)).join(" · ")
        : "";
      return `${location ? `${location}：` : ""}${String(entry.msg)}`;
    });
    return messages.join("；") || fallback;
  }
  return fallback;
}

export function ProjectSetupWizard() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [name, setName] = useState("");
  const [topic, setTopic] = useState("");
  const [sources, setSources] = useState<SourceDraft[]>([{ id: 1, source_type: "local_directory", uri: "" }]);
  const [profile, setProfile] = useState<ResearchTemplateKey>("quick_onboarding");
  const [goal, setGoal] = useState("");
  const [maxTurns, setMaxTurns] = useState("6");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [readiness, setReadiness] = useState<Readiness>({ status: "loading" });
  const [readinessVersion, setReadinessVersion] = useState(0);
  const nextSourceId = useRef(2);
  const submitLock = useRef(false);
  const headingRef = useRef<HTMLHeadingElement>(null);

  const selectedTemplate = researchTemplates.find((template) => template.key === profile) ?? researchTemplates[0];
  const taskModels = taskLabels.map((task) => {
    if (readiness.status !== "loaded") return { ...task, model: null };
    // Match the backend: the newest enabled task profile takes precedence over the environment provider.
    const activeProfile = readiness.profiles.find((item) => item.task_type === task.key && item.enabled);
    const model = activeProfile
      ? (activeProfile.configured ? activeProfile.model : null)
      : (readiness.provider.configured ? readiness.provider.model : null);
    return { ...task, model };
  });
  const hasModel = taskModels.some((item) => !!item.model);
  const hasAllModels = taskModels.every((item) => !!item.model);

  useEffect(() => {
    const controller = new AbortController();
    setReadiness({ status: "loading" });
    async function checkProfiles() {
      try {
        const [response, providerResponse] = await Promise.all([
          fetch("/api/llm/profiles", { cache: "no-store", signal: controller.signal }),
          fetch("/api/llm/provider", { cache: "no-store", signal: controller.signal }),
        ]);
        if (!response.ok || !providerResponse.ok) throw new Error("读取模型配置失败");
        const [body, providerBody]: [unknown, unknown] = await Promise.all([response.json(), providerResponse.json()]);
        if (!Array.isArray(body)) throw new Error("模型配置格式不正确");
        if (!providerBody || typeof providerBody !== "object" || !("configured" in providerBody)) throw new Error("模型配置格式不正确");
        const safeProfiles = body.filter((item): item is LlmProfile => !!item && typeof item === "object")
          .map((item) => ({ task_type: item.task_type, model: item.model, configured: item.configured === true, enabled: item.enabled === true }));
        const providerModel = "model" in providerBody && typeof providerBody.model === "string" ? providerBody.model : "";
        setReadiness({ status: "loaded", profiles: safeProfiles, provider: { configured: providerBody.configured === true, model: providerModel } });
      } catch {
        if (!controller.signal.aborted) setReadiness({ status: "error" });
      }
    }
    void checkProfiles();
    return () => controller.abort();
  }, [readinessVersion]);

  useEffect(() => {
    headingRef.current?.focus({ preventScroll: true });
  }, [step]);

  function clearError(key: string) {
    setErrors((current) => {
      const next = { ...current };
      delete next[key];
      return next;
    });
    setSubmitError(null);
  }

  function validateStep(index: number): Record<string, string> {
    const next: Record<string, string> = {};
    if (index === 0) {
      if (!name.trim()) next.name = "请给调研项目起一个名称。";
      else if (name.trim().length > 160) next.name = "项目名称不能超过 160 个字符。";
      if (!topic.trim()) next.topic = "请描述你希望研究的项目或问题。";
    }
    if (index === 1) {
      if (!sources.length) next.sources = "请至少添加一项资料，让调研有据可查。";
      sources.forEach((source) => {
        const message = sourceError(source);
        if (message) next[`source:${source.id}`] = message;
      });
    }
    if (index === 2 && (!Number.isInteger(Number(maxTurns)) || Number(maxTurns) < 1 || Number(maxTurns) > 20)) {
      next.max_turns = "最大轮数需要是 1 到 20 之间的整数。";
      setAdvancedOpen(true);
    }
    return next;
  }

  function goToStep(index: number) {
    setStep(index);
    setErrors({});
    setSubmitError(null);
  }

  function updateSource(id: number, patch: Partial<SourceDraft>) {
    setSources((current) => current.map((source) => source.id === id ? { ...source, ...patch } : source));
    clearError(`source:${id}`);
    clearError("sources");
  }

  function updateSourceUri(source: SourceDraft, uri: string) {
    const detected = detectSourceType(uri);
    let sourceType = source.source_type;
    if (detected) {
      const keepLocalKind = detected === "local_directory" && sourceType.startsWith("local_");
      if (!keepLocalKind) sourceType = detected;
    }
    updateSource(source.id, { uri, source_type: sourceType });
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitLock.current) return;
    setSubmitError(null);
    if (step < 3) {
      const nextErrors = validateStep(step);
      setErrors(nextErrors);
      if (Object.keys(nextErrors).length) return;
      setStep((current) => current + 1);
      return;
    }
    for (let index = 0; index < 3; index += 1) {
      const nextErrors = validateStep(index);
      if (Object.keys(nextErrors).length) {
        setErrors(nextErrors);
        setStep(index);
        return;
      }
    }
    submitLock.current = true;
    setIsSubmitting(true);
    try {
      const response = await fetch("/api/projects/setup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: name.trim(),
          topic: topic.trim(),
          analysis_goal: templateGoal(profile, goal),
          research_profile: profile,
          max_turns: Number(maxTurns),
          sources: sources.map(({ source_type, uri }) => ({ source_type, uri: uri.trim() })),
        }),
      });
      const rawBody = await response.text();
      let body: unknown;
      try { body = JSON.parse(rawBody); } catch { body = rawBody; }
      if (!response.ok) throw new Error(apiErrorMessage(body, response.status));
      const result = body as RunEnqueue | null;
      if (!result?.run?.id || !result.run.project_id) throw new Error("服务未返回运行信息，请稍后到项目列表查看。");
      router.push(`/projects/${encodeURIComponent(result.run.project_id)}/run?run_id=${encodeURIComponent(result.run.id)}`);
      router.refresh();
    } catch (caught) {
      setSubmitError(caught instanceof TypeError ? "连接失败，请检查服务是否启动后重试。" : caught instanceof Error ? caught.message : "启动失败，请稍后重试。");
      submitLock.current = false;
      setIsSubmitting(false);
    }
  }

  function modelStatus() {
    if (readiness.status === "loading") return "正在检查模型配置…";
    if (readiness.status === "error") return "模型状态暂时无法确认";
    return hasAllModels ? "模型已就绪" : hasModel ? "部分模型已就绪" : "规则分析模式";
  }

  return (
    <div className="setup-wizard">
      <header className="setup-header">
        <div>
          <span className="setup-eyebrow">开始一次新的调研</span>
          <h1>配置一次，自动完成调研</h1>
          <p>告诉 Loop 研究什么、从哪里找资料。启动后即可查看进度与结果。</p>
        </div>
        <Link className="setup-exit" href="/projects">返回项目列表 <span aria-hidden="true">↗</span></Link>
      </header>

      <ol className="setup-stepper" aria-label="调研配置步骤">
        {steps.map((item, index) => (
          <li key={item.title} className={`setup-step ${index === step ? "is-current" : ""} ${index < step ? "is-complete" : ""}`} aria-current={index === step ? "step" : undefined}>
            <span className="setup-step-number" aria-hidden="true">{index < step ? "✓" : index + 1}</span>
            <span><strong>{item.title}</strong><small>{item.caption}</small></span>
          </li>
        ))}
      </ol>

      <div className="setup-layout">
        <form className="setup-card" onSubmit={handleSubmit} noValidate aria-busy={isSubmitting}>
          <div className="setup-card-heading">
            <span className="setup-kicker">第 {step + 1} 步 / 共 4 步</span>
            <h2 ref={headingRef} tabIndex={-1}>{["先确定这次调研的目标", "把调研需要的资料加进来", "选择适合你的调研方式", "准备好了，开始自动调研"][step]}</h2>
            <p>{["一个清晰的主题，会让分析和最终报告更贴近你的需要。", "可以组合多种资料。Loop 会先采集资料，再围绕目标进行分析。", "模板会决定重点关注的问题；没有特别要求时，保留默认设置即可。", "确认以下配置后，Loop 将自动采集、分析、验证并生成报告。"][step]}</p>
          </div>

          <div className="setup-step-content">
            {step === 0 ? (
              <div className="setup-fields">
                <label className="setup-field" htmlFor="setup-name">
                  <span>项目名称 <em>必填</em></span>
                  <input id="setup-name" className="input" value={name} maxLength={160} autoComplete="off" placeholder="例如：客服智能体项目调研" aria-required="true" aria-invalid={!!errors.name} aria-describedby={errors.name ? "setup-name-error" : undefined} onChange={(event) => { setName(event.target.value); clearError("name"); }} />
                  {errors.name ? <small className="setup-error" id="setup-name-error">{errors.name}</small> : <small>取一个容易辨认的名称，方便之后继续查看。</small>}
                </label>
                <label className="setup-field" htmlFor="setup-topic">
                  <span>调研主题 <em>必填</em></span>
                  <textarea id="setup-topic" className="textarea" value={topic} rows={5} placeholder="例如：理解这个项目的整体架构、主要功能和启动方式，评估是否适合继续开发。" aria-required="true" aria-invalid={!!errors.topic} aria-describedby={errors.topic ? "setup-topic-error" : undefined} onChange={(event) => { setTopic(event.target.value); clearError("topic"); }} />
                  {errors.topic ? <small className="setup-error" id="setup-topic-error">{errors.topic}</small> : <small>描述你想理解的内容，以及这次调研要帮助你做出的判断。</small>}
                </label>
              </div>
            ) : null}

            {step === 1 ? (
              <div className="setup-fields">
                <div className="setup-source-list">
                  {sources.map((source, index) => {
                    const option = sourceOptions.find((item) => item.value === source.source_type)!;
                    const errorKey = `source:${source.id}`;
                    return (
                      <div className="setup-source" key={source.id}>
                        <div className="setup-source-heading"><strong>资料 {index + 1}</strong><button className="setup-text-button setup-remove" type="button" aria-label={`移除资料 ${index + 1}`} onClick={() => { setSources((current) => current.filter((item) => item.id !== source.id)); clearError(errorKey); }}>移除</button></div>
                        <div className="setup-source-inputs">
                          <label className="setup-field" htmlFor={`source-type-${source.id}`}>
                            <span>资料类型</span>
                            <select className="select" id={`source-type-${source.id}`} value={source.source_type} onChange={(event) => updateSource(source.id, { source_type: event.target.value as SourceType })}>{sourceOptions.map((item) => <option value={item.value} key={item.value}>{item.label}</option>)}</select>
                          </label>
                          <label className="setup-field" htmlFor={`source-uri-${source.id}`}>
                            <span>{source.source_type.startsWith("local_") ? "完整路径" : "链接地址"} <em>必填</em></span>
                            <input className="input" id={`source-uri-${source.id}`} value={source.uri} placeholder={option.placeholder} autoComplete="off" spellCheck={false} aria-required="true" aria-invalid={!!errors[errorKey]} aria-describedby={`source-hint-${source.id}`} onChange={(event) => updateSourceUri(source, event.target.value)} />
                          </label>
                        </div>
                        <p className={errors[errorKey] ? "setup-error" : "setup-source-hint"} id={`source-hint-${source.id}`}>{errors[errorKey] ?? option.hint}</p>
                      </div>
                    );
                  })}
                  {!sources.length ? <div className="setup-empty">还没有资料，添加一个项目目录或链接开始吧。</div> : null}
                </div>
                {errors.sources ? <p className="setup-error" role="alert">{errors.sources}</p> : null}
                <button className="setup-add-source" type="button" onClick={() => { const id = nextSourceId.current++; setSources((current) => [...current, { id, source_type: "local_directory", uri: "" }]); clearError("sources"); }}><span aria-hidden="true">＋</span> 添加一项资料</button>
                <p className="setup-note">请使用运行服务的电脑上可以访问的路径。系统会在启动前统一检查文件和目录是否存在。</p>
              </div>
            ) : null}

            {step === 2 ? (
              <div className="setup-fields">
                <fieldset className="setup-templates">
                  <legend>这次更关注什么？</legend>
                  <div className="setup-template-grid">
                    {researchTemplates.map((template) => (
                      <label className={`setup-template ${profile === template.key ? "is-selected" : ""}`} key={template.key}>
                        <input type="radio" name="research_profile" value={template.key} checked={profile === template.key} onChange={() => { setProfile(template.key); setSubmitError(null); }} />
                        <span><strong>{template.label}</strong><small>{template.description}</small></span>
                      </label>
                    ))}
                  </div>
                </fieldset>
                <section className="setup-template-brief" aria-live="polite">
                  <div className="setup-template-brief-head">
                    <strong>{selectedTemplate.label}报告会这样组织</strong>
                    <span>{selectedTemplate.deliverable}</span>
                  </div>
                  <p className="setup-template-question">核心问题：{selectedTemplate.coreQuestion}</p>
                  <ol className="setup-template-outline">
                    {selectedTemplate.reportOutline.map((item, index) => (
                      <li key={item}><span aria-hidden="true">{index + 1}</span>{item}</li>
                    ))}
                  </ol>
                  <p className="setup-template-focus">重点：{selectedTemplate.focusPoints.join(" · ")}</p>
                </section>
                <label className="setup-field" htmlFor="setup-goal"><span>补充你的关注点 <em>选填</em></span><textarea className="textarea setup-goal" id="setup-goal" value={goal} rows={3} placeholder="例如：重点关注模型调用流程、知识库检索和部署配置。" onChange={(event) => { setGoal(event.target.value); setSubmitError(null); }} /></label>
                <section className={`setup-model-status ${readiness.status === "loaded" && hasModel ? "is-ready" : "is-fallback"}`} aria-label="模型就绪状态" aria-live="polite">
                  <div className="setup-model-title"><strong><span className="setup-status-dot" aria-hidden="true" />{modelStatus()}</strong><button className="setup-text-button" type="button" disabled={readiness.status === "loading"} onClick={() => setReadinessVersion((current) => current + 1)}>重新检查</button></div>
                  {readiness.status === "loading" ? <p>仅读取配置状态，不会发起模型调用。</p> : readiness.status === "error" ? <p>暂时无法读取模型配置。仍可继续启动；没有可用模型的步骤会使用规则分析（确定性回退）。</p> : hasModel ? <><p>{hasAllModels ? "已找到可用的模型配置，启动后将自动进行模型分析、复核与报告生成。" : "部分任务已有可用模型，其余任务会使用规则分析（确定性回退）。"}本次检查只读取配置，不调用模型。</p><ul className="setup-model-tasks">{taskModels.map((task) => <li key={task.key}><span>{task.label}</span><strong>{task.model || "规则分析"}</strong></li>)}</ul></> : <p>尚无已配置且启用的模型档位，环境中的默认模型也未就绪。本次将使用规则分析（确定性回退），可以体验资料采集、分析与报告流程；如需模型分析，请先完成模型设置。</p>}
                  <Link className="setup-model-link" href="/settings/llm" target="_blank" rel="noopener noreferrer">打开模型设置 <span aria-hidden="true">↗</span><span className="setup-sr-only">（在新标签页打开）</span></Link>
                </section>
                <details className="setup-advanced" open={advancedOpen} onToggle={(event) => setAdvancedOpen(event.currentTarget.open)}><summary>高级设置 <span>可保留默认值</span></summary><label className="setup-field" htmlFor="setup-turns"><span>最大分析轮数</span><input className="input" id="setup-turns" type="number" min={1} max={20} step={1} value={maxTurns} aria-invalid={!!errors.max_turns} aria-describedby="setup-turns-hint" onChange={(event) => { setMaxTurns(event.target.value); clearError("max_turns"); }} /><small id="setup-turns-hint" className={errors.max_turns ? "setup-error" : ""}>{errors.max_turns ?? "默认 6 轮，可设置 1–20 轮；达到完成条件时会提前结束。"}</small></label></details>
              </div>
            ) : null}

            {step === 3 ? (
              <div className="setup-fields">
                <section className="setup-review-block"><div className="setup-review-title"><h3>项目目标</h3><button className="setup-text-button" type="button" disabled={isSubmitting} onClick={() => goToStep(0)}>修改</button></div><strong className="setup-review-name">{name}</strong><p className="setup-review-topic">{topic}</p></section>
                <section className="setup-review-block"><div className="setup-review-title"><h3>调研资料 <span>{sources.length} 项</span></h3><button className="setup-text-button" type="button" disabled={isSubmitting} onClick={() => goToStep(1)}>修改</button></div><ul className="setup-review-sources">{sources.map((source) => <li key={source.id}><span>{sourceOptions.find((item) => item.value === source.source_type)?.label}</span><p>{source.uri}</p></li>)}</ul></section>
                <section className="setup-review-block"><div className="setup-review-title"><h3>调研方式</h3><button className="setup-text-button" type="button" disabled={isSubmitting} onClick={() => goToStep(2)}>修改</button></div><div className="setup-review-tags"><span>{selectedTemplate.label}</span><span>最多 {maxTurns} 轮</span><span className={hasModel ? "is-ready" : "is-fallback"}>{modelStatus()}</span></div><p className="setup-review-topic">{goal.trim() || selectedTemplate.description}</p><p className="setup-review-outline"><strong>核心问题：</strong>{selectedTemplate.coreQuestion}</p><p className="setup-review-outline"><strong>报告结构：</strong>{selectedTemplate.reportOutline.join(" → ")}</p>{!hasModel ? <p className="setup-review-warning">{readiness.status === "loaded" ? "当前将使用规则分析（确定性回退），不调用模型。" : "模型状态尚未确认；没有可用模型的步骤会使用规则分析（确定性回退）。"}</p> : null}</section>
                <div className="setup-launch-preview"><strong>启动后将自动进行</strong><ol><li><span>1</span>采集资料</li><li><span>2</span>分析与验证</li><li><span>3</span>生成架构图</li><li><span>4</span>生成报告</li></ol><p>自动进入运行页面，你可以实时查看进度，并在完成后阅读调研结果。仅有文档资料时会明确提示跳过架构图。</p></div>
              </div>
            ) : null}
          </div>

          {submitError ? <div className="setup-submit-error" role="alert"><strong>暂时无法启动调研</strong><p>{submitError}</p><span>请检查配置后重试；你的填写内容已保留。</span></div> : null}

          <footer className="setup-footer">
            <span>{step === 3 ? "点击启动后创建项目并开始调研" : "填写内容会在步骤间保留"}</span>
            <div className="setup-footer-actions">{step > 0 ? <button className="button button-secondary" type="button" disabled={isSubmitting} onClick={() => goToStep(step - 1)}>上一步</button> : null}<button className="button setup-primary" type="submit" disabled={isSubmitting}>{isSubmitting ? <><span className="setup-spinner" aria-hidden="true" />正在创建并启动…</> : step === 3 ? <>启动自动调研 <span aria-hidden="true">↗</span></> : <>下一步 <span aria-hidden="true">→</span></>}</button></div>
          </footer>
        </form>

        <aside className="setup-aside">
          <div className="setup-aside-icon" aria-hidden="true">✦</div>
          <span className="setup-eyebrow">从资料到答案</span>
          <h2>让调研自己跑起来</h2>
          <p>不必逐个操作工作台。完成配置后，Loop 会接着做完整个流程。</p>
          <ul className="setup-deliverables"><li><span aria-hidden="true">✓</span><div><strong>有依据的分析</strong><small>从资料中提取事实，记录证据与发现。</small></div></li><li><span aria-hidden="true">✓</span><div><strong>看得见的进展</strong><small>跟踪每个阶段，了解当前正在做什么。</small></div></li><li><span aria-hidden="true">✓</span><div><strong>可以继续追问的结果</strong><small>汇总架构、风险、建议与待确认问题。</small></div></li></ul>
          <div className="setup-aside-tip"><strong>{["主题可以这样写", "建议优先添加项目目录", "按你的目的选择模板", "启动前最后确认"][step]}</strong><p>{["“我刚接手这个项目，想弄清楚它解决什么问题、从哪里启动，以及哪些模块最重要。”", "完整的项目目录或 GitHub 仓库可以帮助 Loop 关联代码、依赖、入口和文档。", "想上手项目选“快速接手”，想看模块关系选“架构理解”。每种模板都会保留证据和风险。", "确认路径在运行服务的电脑上可以访问，并检查模型状态是否符合你的预期。"][step]}</p></div>
        </aside>
      </div>
    </div>
  );
}
