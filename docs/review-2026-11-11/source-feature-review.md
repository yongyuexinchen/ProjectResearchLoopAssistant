# 新增源码图功能独立评审

评审日期：2026-11-11。对象：`codex/source-flow-reports` 未提交工作区。依据：`自动源码流程图方案.md` 和 `2026-11-11-source-flow-reports.md`。本文件是初审记录；实现者正在处理下列问题，最终复查结果另行更新。

范围为 `source_flow/source_common/source_python/source_javascript/source_snapshot`、架构图保存/重画、Mermaid 输出和前端源码导航。报告正文、在线报告和 PDF 模块尚在实现，未在本轮得出完成性结论。没有连接真实数据库、调用模型、执行输入仓库代码，也没有改动产品代码。复现通过临时目录中的独立文本样例调用 `build_source_flow`，未重跑既有全面测试。

## Critical

无已确认的 Critical 问题。

## Important

### I1：JS 对象字面量方法错误注册为外层词法函数

初审位置：`services/api/app/architecture/source_javascript.py:85`、`services/api/app/architecture/source_javascript.py:112`。

```typescript
const obj = { work() { return 1; } };
function main() { return work(); }
```

实际：`main` 的 L2 裸 `work()` 得到 `target_id`，指向对象方法。预期：对象成员不建立外层 `work` 绑定，裸调用应保持未解析。原因是 `method_definition` 与函数声明共用 `scope.bind`，而对象字面量未建立成员作用域。

影响：可能从不存在的全局/局部调用生成确定性边，违背“不按同名猜测”。建议仅将类方法放入类成员表，对象方法保留独立导航记录，不向外层词法作用域声明名称。

### I2：Python star import 已记号，但未实际阻断不确定全局绑定

初审位置：`services/api/app/architecture/source_python.py:92`、`services/api/app/architecture/source_common.py:32`。

```python
def work(): return 1
from plugin import *
def main(): return work()
```

实际：L3 `work()` 解析到原模块的 `work`。预期：star import 可能覆盖该名称；外部导出内容不可知，应保持未解析。`bindings["*"] = None` 从未被名称查询消费。

影响：对动态导入给出错误确定目标；源码图、函数导航和随后复制的报告都会固化该错误。建议在名称查询时区分明确局部绑定与受 star import 污染的上层绑定，宁可保守未解析。

### I3：Python 越过顶层包的相对导入错误连到仓库根模块

初审位置：`services/api/app/architecture/source_flow.py:77`。

文件：

```text
pkg/__init__.py  # 空
target.py       # def work(): return 1
pkg/a.py
```

`pkg/a.py`：

```python
from .. import target
def main(): return target.work()
```

实际：L2 解析到仓库根的 `target.py:work`。预期：当 `pkg` 是顶层包时，`..` 已越过包边界；根目录是源码扫描边界，并不自动成为外层 Python 包。应未解析。当前仅比较目录深度，等号边界被放过，未验证相对导入需要的包上下文。

影响：把无效或无法证明有效的相对导入描述为确定性调用。建议先建立可证明的包链，缺乏包上下文时保守中止。

### I4：Python 模块解析的歧义祖先被子模块 fallback 绕过

初审位置：`services/api/app/architecture/source_flow.py:159`、`services/api/app/architecture/source_flow.py:164`。

文件：`pkg.py` 内容为 `x=1`；`pkg/__init__.py` 空；`pkg/helper.py` 内容为 `def work(): return 1`；`a.py` 为：

```python
import pkg.helper
def main(): return pkg.helper.work()
```

实际：首次解析 `pkg` 遇到 `pkg.py` 和 `pkg/__init__.py` 两个候选，返回空；调用解析仍继续拼接 `pkg.helper`，最终解析到 `pkg/helper.py:work`。预期：按当前解析器明确声明的“歧义不猜测”策略，中间歧义应传播，不应被 fallback 抹掉。如果要采用 Python 具体导入优先级，需明确实现并验证该规则，不能既把父模块标为歧义又假定其为包。

影响：复杂仓库/重复源码根中的同名包可产生貌似确定的错误边。建议区分“缺少显式再导出”与“父模块不存在/有歧义”，仅前者允许向子模块继续查找。

### I5：仅凭装饰器方法名确认 HTTP 入口，前端过度声称“入口注册语法”

初审位置：`services/api/app/architecture/source_python.py:65`；前端 `apps/web/components/source-navigator.tsx:34`。

```python
decorators = {}
@decorators.get("cache")
def work(): return 1
```

实际：`work.entrypoint` 为 `http_decorator`、`confidence="syntax"`；UI 显示“入口注册语法”。预期：只能证明“装饰器使用了名为 get 的方法”，不能证明 HTTP 路由注册。`@decorators.get` 也可能是缓存或插件装饰器。

影响：错误入口会优先占用入口邻域画布预算，并误导教程式阅读。建议降为候选，精确写“HTTP 风格装饰器语法候选”；只有已验证路由接收者/注册形式才使用确定注册标签。导出的 `GET` 等名称也应使用同样的声明强度。

## Minor

### M1：匿名 default 箭头函数有导航节点，却没有导出绑定

初审位置：`services/api/app/architecture/source_javascript.py:237`。

`helper.ts`：

```typescript
export default () => 1;
```

`a.ts`：

```typescript
import work from "./helper";
function main() { return work(); }
```

实际：匿名箭头被索引为 `default` 函数，但导出表未包含它；L2 `work()` 保持未解析。预期：这个直接且无歧义的默认导出可解析到本地声明。

影响限于漏边；界面仍诚实显示未解析，不是错误确定性事实，因此列为 Minor。方案明确覆盖箭头函数与相对导入，建议补足此常见组合。

## 本轮交流中已修复，待最终窄范围复核

- Python 方法里的 `def inner(self)` 把普通参数当成外层实例；应保持未解析。
- JS 方法里的普通嵌套函数错误继承 `this`；静态方法的 `this` 错连实例成员；应保持未解析。箭头函数仍可继承词法 `this`。
- Python `match case work`、`del work` 未阻断原声明绑定。
- JS `({ work } = other)`、`for (work of items)` 未阻断原声明绑定。
- 另在途原有修复包括：main guard 仅标记 guard 内直接引用、导入模块成员重赋值、等价路径拼法去重、单文件超限标记。未将实现者已补充的反例重复登记为新的剩余问题。

## 独立验证已通过的部分

1. 快照重画：由临时源文件生成图，保存快照，修改源文件，再用 `SimpleNamespace` 调用 `regenerate_diagram`。保存的 `graph_json.details` 未改变，Mermaid 未读入新函数。无需数据库。
2. 形状校验：将调用位置改成负数/不完整结构，重画在修改输出前抛出 `ValueError`。
3. 新路径过滤：源码根本身位于临时目录的 `.worktrees/repo`，正常 `src/tmp.py` 与 `src/next-utils.ts` 被解析；仓库内部 `.next-review/`、`.tmp/`、`.worktrees/`、`.superpowers/` 文件均被跳过。未观察到相近正常名称或工作树根被整体误伤。
4. 源码 HTML/语法转义经代码复核：导航使用 React 文本节点，未见将摘录传入 HTML 执行的路径；Mermaid 标签编码语法字符，渲染器采用严格安全设置与关闭 HTML 标签。未进行本轮浏览器交互可访问性全测。
5. 模块职责清晰：通用预算/绑定记录、Python、JS/TS、快照校验和画布生成各有单独模块。显示所有已解析函数明细，同时限制画布节点/边并解释遗漏，符合方案的图与明细分离要求。

## Spec 符合性结论（初审）

基本架构符合批准方案：两类静态语法解析、不执行输入代码、真实位置及源内容 hash、有限预算、未知调用保留、保存 details、历史图仅由快照重画、前端搜索与逐段导航。上述 Important 说明“未知不猜测”及“确定入口与候选分开”尚未完整落实，因此初审不建议视为全部验收通过。报告模块需另行审阅。

## 代码质量结论（初审）

整体模块边界与接口可维护，快照隔离和展示转义有明确实现。主要薄弱点是把词法绑定、类成员、对象成员和包解析状态放入过于宽泛的模型：若不显式区分未知、缺失、歧义和接收者种类，就容易在局部补丁后继续出现假阳性。建议用本轮小反例形成少量针对性回归，并在本轮修复后做窄范围复核；无需在解析器扩展期间反复执行全面测试。
