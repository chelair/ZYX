---
name: zyx
description: 通过SSH连接到超算服务器，定位项目并读取最新VASP计算结果文件，执行收敛性与合理性检验，并生成结构化的检验报告。
runAs: subagent
effort: high
---

# ZYX VASP 工作流自动化

通过 SSH 连接超算服务器，自动完成 VASP 计算结果检查与报告。

## 核心规则

- ⛔ **绝对禁止**删除服务器上的任何文件(包括目录)
- ✅ 只允许：创建新目录 + 创建新文件 + 读取文件内容
- ✅ 复制文件使用 `cp -n`（no-clobber）
- ✅ 创建目录使用 `mkdir <dir>`（不加 `-p`）
- ✅ 写入新文件使用临时文件 + fsync + rename（原子提交）
- ✅ 每个操作必须先执行 `--dry-run` 预览，用户确认后再实际执行
- ✅ 提交作业前展示完整预览等待用户确认

## 模块索引

每个模块对应一个详细流程文件，**必须严格按照模块说明执行**：

| 模块 | 文件 | 用途 |
|------|------|------|
| 检查报告 | `modules/check-report.md` | SSH 检查任务状态 → 下载结果 → 生成 PPT 报告 |
| 续算 | `modules/continue.md` | 创建 conN/ 续算目录 → 生成 INCAR → 提交作业 |
| 诊断 | `modules/diagnose.md` | VASP 输出异常诊断与修复建议 |
| 项目管理 | `modules/project.md` | 添加/扫描/管理 VASP 计算项目 |

## 命令一览

| 命令 | 用途 | 详见 |
|------|------|------|
| `@zyx check [项目] [子任务]` | 检查 Run 子任务 | `modules/check-report.md` |
| `@zyx report` | 生成汇总 PPT | `modules/check-report.md` |
| `@zyx continue <项目> <子任务>` | 创建续算目录 | `modules/continue.md` |
| `@zyx continue --dry-run <项目> <子任务>` | 预览续算 | `modules/continue.md` |
| `@zyx diagnose <项目> [子任务]` | 异常诊断 | `modules/diagnose.md` |
| `@zyx projects` | 项目管理 | `modules/project.md` |
| `@zyx scan <项目>` | 扫描远程目录 | `modules/project.md` |
| `@zyx jobs` | LSF 作业监控 | `scripts/jobs_monitor.py` |
| `@zyx view <目录>` | VESTA 结构查看 | `scripts/vesta_view.py` |
| `@zyx connect <目录>` | SSH 交互终端 | `scripts/ssh_connect.py` |

## 关键约定

- 作业识别：服务器 `job.info` 优先级高于本地 JSON
- 状态判定：bjobs → OUTCAR（详见 `modules/check-report.md` 决策树）
- 续算目录：同级排列 con1/con2/...，不嵌套（详见 `modules/continue.md`）
- 队列选择：bhosts 节点空闲优先（详见 `modules/continue.md`）
- 参考手册：`VASPKIT.md`（固定原子/DIPOL，手动操作）、`scripts/.input_reference.md`（INCAR 参数）
