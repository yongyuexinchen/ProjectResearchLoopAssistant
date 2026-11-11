import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import test from 'node:test';
import ts from 'typescript';

const nativeRequire = createRequire(import.meta.url);

// Execute the real report page and API helper with only the network/navigation boundary replaced.
async function historicalReportPage() {
  const requests = [];
  const project = { id: 'project-a', name: 'Project A' };
  const report = {
    id: 'report-old', project_id: project.id, run_id: 'run-old', status: 'draft', title: 'Old report',
    verifier_result_json: { passed: true, risk_level: 'low', summary: 'Ready', checks: [], blocking_reasons: [], warning_reasons: [] },
  };
  const fetch = async (url, init = {}) => {
    requests.push({ url, ...init });
    let body = report;
    if (url.endsWith('/projects/project-a')) body = project;
    if (url.endsWith('/markdown')) body = { markdown: 'Saved report' };
    return { ok: true, json: async () => body };
  };
  const loaded = new Map();
  const load = path => {
    if (loaded.has(path)) return loaded.get(path);
    const source = readFileSync(new URL(path, import.meta.url), 'utf8');
    const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 } }).outputText;
    const module = { exports: {} };
    const require = name => {
      if (name === '@/lib/api') return load('../lib/api.ts');
      if (name === '@/lib/labels') return load('../lib/labels.ts');
      if (name === 'next/navigation') return { redirect: () => { throw new Error('REDIRECT'); } };
      if (name === 'next/link') return { __esModule: true, default: () => null };
      if (name.startsWith('@/components/')) return new Proxy({}, { get: () => () => null });
      return nativeRequire(name);
    };
    vm.runInNewContext(code, { module, exports: module.exports, require, process, fetch, URLSearchParams, FormData });
    loaded.set(path, module.exports);
    return module.exports;
  };
  const page = load('../app/projects/[id]/report/page.tsx').default;
  const tree = await page({ params: Promise.resolve({ id: project.id }), searchParams: Promise.resolve({ report_id: report.id }) });
  return { tree, requests };
}

function elements(node) {
  if (Array.isArray(node)) return node.flatMap(elements);
  if (!node || typeof node !== 'object') return [];
  return [node, ...elements(node.props?.children)];
}

function text(node) {
  if (Array.isArray(node)) return node.map(text).join('');
  if (node && typeof node === 'object') return text(node.props?.children);
  return String(node ?? '');
}

for (const [label, endpoint] of [['重新生成调研报告', '/reports'], ['生成智能调研报告', '/reports/intelligent']]) {
  test(`historical ${label} sends the displayed report run to ${endpoint}`, async () => {
    const { tree, requests } = await historicalReportPage();
    const form = elements(tree).find(element => element.type === 'form' && text(element).includes(label));
    assert.ok(form);
    await assert.rejects(form.props.action(new FormData()), /REDIRECT/);
    const submitted = requests.find(request => request.method === 'POST' && request.url.endsWith(endpoint));
    assert.equal(JSON.parse(submitted?.body || '{}').run_id, 'run-old');
  });
}
