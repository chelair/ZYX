---
name: zyx的VASP工作流
description: 通过SSH连接到超算服务器，定位项目并读取最新VASP计算结果文件，执行收敛性与合理性检验，并生成结构化的检验报告。
runAs: subagent
effort: high
---

# VASP 工作流自动化

通过 SSH 连接超算服务器，自动完成 VASP 计算结果检查与报告。

## 核心规则

- ⛔ **严禁**删除、移动或重命名服务器上的任何文件
- ✅ 只允许读取文件内容和创建新文件（如写入报告）

## 命令一览

| 命令 | 用途 |
|------|------|
| `@zyx connect <目录>` | SSH 连接超算并进入交互式终端 |
| `@zyx check [项目] [子任务]` | 检查 Run 子任务，下载结果，生成汇总报告 |
| `@zyx projects` | 管理项目及子任务列表 |

## 脚本说明

| 脚本 | 功能 |
|------|------|
| `scripts/ssh_connect.py` | SSH 连接 + 交互式终端 |
| `scripts/project_manager.py` | 管理项目和子任务（增/删/改状态） |
| `scripts/vasp_check.py` | 遍历 Run 子任务，检查收敛性，自动更新状态 |

## 数据模型

每个项目可包含多个子任务：

- **结构优化** (relax) — 结构弛豫，检查是否收敛
- **电子结构** (scf/static/bands/dos) — 静态自洽/能带/态密度
- **NEB** (neb) — 过渡态搜索

子任务状态：`Pending`(未开始) → `Run`(运行中，自动检测) → `Completed`/`Failed`(自动)

## 使用流程

### 1. 添加项目
```bash
python scripts/project_manager.py add test /data/gpfs03/mdye/projects/test
```

### 2. 添加子任务
```bash
python scripts/project_manager.py sub add test 结构优化 relax
python scripts/project_manager.py sub add test 电子结构 scf
python scripts/project_manager.py sub status test 结构优化 Run   # 设为运行中
```

### 3. 执行检查
```bash
python scripts/vasp_check.py                    # 检查所有 Run 子任务
python scripts/vasp_check.py test               # 只检查 test 的 Run 子任务
python scripts/vasp_check.py test 结构优化       # 只检查结构优化（无视状态）
```

### 4. 查看结果
```
vaspcheck/
├── test/
│   ├── 结构优化/
│   │   ├── POSCAR
│   │   ├── CONTCAR
│   │   └── 作业状态.txt
│   └── 电子结构/
│       ├── POSCAR
│       ├── CONTCAR
│       └── 作业状态.txt
└── 汇总报告.txt
```

## 文件位置

```
skill/zyx/
├── SKILL.md
├── vaspcheck_projects.json     ← 项目清单（自动更新状态）
└── scripts/
    ├── ssh_connect.py
    ├── project_manager.py
    └── vasp_check.py
```
