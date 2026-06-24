---
name: zyx
description: 通过SSH连接到超算服务器，定位项目并读取最新VASP计算结果文件，执行收敛性与合理性检验，并生成结构化的检验报告。
runAs: subagent
effort: high
---

# VASP 工作流自动化

通过 SSH 连接超算服务器，自动完成 VASP 计算结果检查与报告。

## 核心规则

- ⛔ **必须完整执行 WORKFLOW.md 中的步骤**。触发检查/项目工作流时，严格按照 workflow 的 8 步流程运行，不得擅自跳过、合并或改动任何步骤。若某步骤因环境问题失败，应报告错误信息，由用户决定如何处理。
- ⛔ **绝对禁止**删除服务器上的任何文件(包括目录)
- ✅ 只允许：创建新目录 + 创建新文件 + 读取文件内容
- ✅ 复制文件使用 `cp -n`（no-clobber），目标存在时自动拒绝
- ✅ 创建目录使用 `mkdir <dir>`（不加 `-p`），已存在时报错退出
- ✅ 写入新文件使用临时文件 + fsync + rename（原子提交）

## 命令一览

| 命令 | 用途 |
|------|------|
| `@zyx connect <目录>` | SSH 连接超算并进入交互式终端 |
| `@zyx check [项目] [子任务]` | 检查 Run 子任务，下载结果，生成汇总报告 |
| `@zyx scan <项目>` | SSH 扫描项目目录，自动发现并归类子任务 |
| `@zyx projects` | 管理项目及子任务列表 |
| `@zyx view <目录>` | VESTA 中打开 POSCAR + CONTCAR 对比 |
| `@zyx jobs` | 查看超算作业，关联到项目/子任务 |
| `@zyx report` | 生成 VASP 状态汇总 PPT + 结构图 |
| `@zyx continue <项目> <子任务>` | 创建续算目录 conN/，接续未收敛作业 |
| `@zyx continue --dry-run <项目> <子任务>` | 预览续算操作，不执行 |
| `@zyx diagnose <项目> [子任务]` | SSH 诊断异常并给出建议 |
| `@zyx download <项目> [子任务]` | 下载输出文件到本地项目目录 |

## 作业识别标识 (job.info)

服务器上每个计算目录下的 `job.info` 是 skill **识别作业的首要依据**，优先级高于 JSON。

```ini
[submit]
project  = a_Fe2O3_0701
subtask  = opt/Fe2O3_110
status   = pending
job_id   = 123456
[incar]
IBRION   = 2
NSW      = 500
```

## 数据模型

目录前缀自动归类：`opt/` `raw/` `abs/` `oer/` `neb/` `s8/` `barrier/` `dos/` `bader/` `frac/` `static/` `scf/` `bands/` `md/`

状态: bjobs RUN→Run, PEND→PEND, accuracy→Completed, 无accuracy→Failed, I REFUSE→Error, 有OUTCAR无bjobs→Stop, 无OUTCAR→Pending

## 脚本说明

| 脚本 | 功能 |
|------|------|
| `scripts/vasp_check.py` | 检查收敛 + 诊断（data 预扫描） |
| `scripts/jobs_monitor.py` | LSF 作业监控 + 队列推荐 |
| `scripts/project_manager.py` | 项目管理 (add 后自动 scan) |
| `scripts/safe_ops.py` | 安全层: cp -n / mkdir / job.info 读写 |
| `scripts/problem_detect.py` | 异常诊断: 9 项检测 |
| `scripts/summary_report.py` | PPT 报告 + 结构图 |
| `scripts/ssh_connect.py` | SSH 连接 + 交互终端 |
| `scripts/job_continue.py` | 续算操作 (两步式) |

## 参考手册（按需查阅）

| 手册 | 内容 |
|------|------|
| `VASPKIT.md` | VASPKit 402 固定原子 + DIPOL 偶极矫正 + INCAR/POTCAR/KPOINTS |
| `CONTINUE.md` | 续算流程 + CONTCAR 校验 + 核数估算 + vasp.lsf |
| `MONITOR.md` | 状态判定 + 续算目录处理 + 队列选择三步决策 |
| `WORKFLOW.md` | 完整项目生命周期流程 |
| `scripts/.input_reference.md` | INCAR 参数 + DFT+U/磁矩/色散/HSE 参考 |
