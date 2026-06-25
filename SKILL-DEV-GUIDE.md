# Skill 开发行为手册

基于 ZYX skill v4.8 开发经验总结。目标：单人/小团队，用 AI 辅助，产出可维护、可重复运行的 skill。

---

## 一、文档设计原则

### 1.1 文档分层：索引 + 模块

**错误做法：** 一个 70 行的 SKILL.md 塞满所有规则、流程、技术细节。AI 上下文溢出，每次都重读全文。

**正确做法：** 三层结构

```
SKILL.md          → 精简索引（<50行）：核心规则 + 命令一览 + 模块索引
modules/
  check-report.md → 单模块完整流程 + 精确脚本命令
  continue.md     → 同上
  diagnose.md     → 同上
  project.md      → 同上
```

SKILL.md 只回答"有什么模块、怎么找到它们"，不回答"怎么做"。

### 1.2 模块 MD 必须包含精确脚本命令

**错误：** "运行 vasp_check.py 检查任务状态"

**正确：**
```bash
python scripts/vasp_check.py [项目] [子任务] --timeout 10
```

AI 不需要去读代码推测参数，直接照抄命令即可。

### 1.3 文档与代码必须同步

修改脚本后，检查对应模块 MD 是否需要更新。在每个模块 MD 头部标注对应脚本：`> 对应脚本: scripts/vasp_check.py`

### 1.4 旧文档归档不要删除

改为 `_archived_xxx.md`，保留历史参考。

---

## 二、代码架构原则

### 2.1 单一职责拆分

一个文件超 300 行考虑拆分。

```
vasp_check.py (18K) → outcar_analyzer.py + file_transfer.py + vasp_check.py(编排)
```

### 2.2 配置集中化

创建 `config.py`，所有路径/常量从它导入。换环境只改一个文件。

### 2.3 共享数据层

`project_store.py` 作为 `load_projects/save_projects` 的唯一实现。

### 2.4 SSH 连接复用

`ssh_manager.py`：同一 `{host,port,user}` 复用连接，finally 中 close_all()。

### 2.5 统一编排器

3+ 独立脚本时创建 `zyx.py`，用 subprocess 调用现有脚本，不重复实现逻辑。编排器负责步骤顺序、状态传递、异常降级。

---

## 三、交互设计原则

### 3.1 用 flag 替代 input()

```python
parser.add_argument("--yes", "-y", action="store_true")
```

subagent 环境下 input() 永远返回空字符串。

### 3.2 dry-run 优先

任何写操作必须先支持 --dry-run 预览。

### 3.3 人工步骤明确标注

无法自动化的步骤在输出中提示：
```
[!] 需手动: vaspkit → 4 → 402 → 3
```

---

## 四、安全与稳健性

### 4.1 Shell 注入防护

所有传给 exec_command() 的路径用 shlex.quote() 包裹。

### 4.2 禁止删除操作

safe_ops.py 不提供任何删除函数。

### 4.3 文件锁保护

prs.save() 在 Windows 上加 try/except PermissionError + fallback 文件名。

### 4.4 错误显式化

禁止 try/except 吞没错误后返回空列表。应 print + raise 或返回 error dict。

### 4.5 零字节防御

用 `test -s` 而非 `test -f` 检查文件非空。

---

## 五、测试与验证

### 5.1 每次改动后验证全部导入

```bash
python -c "import all_modules; print('OK')"
```

### 5.2 真实运行测试

即使没完整数据，也要 --dry-run 验证 SSH/路径/错误分支。

### 5.3 端到端流程测试

发布前跑完整 workflow，记录所有输出异常。

---

## 六、Git 与版本管理

### 6.1 版本号约定

```
v4.0   — 大版本（架构重构）
v4.0.1 — 小修复
v4.5   — 功能完善
```

### 6.2 每次可工作状态就 commit

push 可攒，commit 不能攒。

### 6.3 消息格式

```
v4.5 — 简短标题

- 具体改动 1
- 具体改动 2
```

---

## 七、AI 协作要点

### 7.1 精确提示词

不写"帮我优化"，写"给 safe_ops.py 所有远程命令加 shlex.quote()，不改函数签名"。

### 7.2 分批执行

大任务分 Phase，每 Phase 独立提示词 + 验证标准。

### 7.3 先计划再执行

让 AI 输出修改计划，确认后再动手。

### 7.4 代码审查

改完用另一个视角（人工或 AI）做审查，对照文档检查一致性。

---

## 八、常见陷阱速查

| 陷阱 | 现象 | 修复 |
|------|------|------|
| 文档代码不一致 | AI 按文档操作但脚本行为不同 | 模块 MD 标注对应脚本 |
| subprocess 错误被吞 | workflow silent fail | 检查 returncode，加 try/except |
| 中文 + PowerShell | `-c "..."` 乱码 | 用文件方式 |
| f-string 换行 | 文件写入时被展开 | `\\n` 转义 |
| argparse 子命令参数 | `unrecognized` | `--yes` 紧跟子命令 |
| BOM 污染 JSON | json.load 报错 | 用 Python json.dump |
| bjobs 9 字符限制 | JobName 截断 | ≤9 字符 [A-Za-z0-9_] |
