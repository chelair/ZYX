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
| `@zyx scan <项目>` | **SSH 扫描项目目录，自动发现并归类子任务** |
| `@zyx projects` | 管理项目及子任务列表 |
| `@zyx view <目录>` | 在 VESTA 中打开 POSCAR + CONTCAR 进行结构对比 |
| `@zyx jobs` | 查看超算上正在运行的作业，关联到项目/子任务 |

## 脚本说明

| 脚本 | 功能 |
|------|------|
| `scripts/ssh_connect.py` | SSH 连接 + 交互式终端 |
| `scripts/project_manager.py` | 管理项目和子任务（增/删/改/扫描） |
| `scripts/vasp_check.py` | 遍历 Run 子任务，检查收敛性，自动更新状态 |
| `scripts/vesta_view.py` | 用 ASE 生成结构对比图（自动插入 PPT） |
| `scripts/jobs_monitor.py` | 监控 LSF 作业，关联到项目和子任务 |
| `scripts/struct2ppt.py` | 用 ASE 渲染结构对比图（POSCAR vs CONTCAR，a/b/c轴） |
| `scripts/generate_report.py` | 统一入口：检查→汇总PPT→结构图 一键完成 |

## 数据模型

每个项目可包含多个子任务：

- **结构优化** (relax) — 结构弛豫，检查是否收敛
- **电子结构** (scf/static/bands/dos) — 静态自洽/能带/态密度
- **NEB** (neb) — 过渡态搜索

子任务状态：`Pending`(未开始) → `Run`(运行中，自动检测) → `Completed`/`Failed`(自动)

## 自动扫描与分类

`project_manager.py scan <项目>` 可 SSH 登录超算，自动发现项目根目录下的子目录并按规则分类：

| 目录前缀 | 分类标签 |
|---------|---------|
| `opt/` | 结构优化 |
| `abs/` | 吸附 |
| `s8/` | S8还原 |
| `barrier/` | 分解能垒 |
| `dos/` | DOS/PDOS |
| `bader/` | 差分+bader |
| `freediag/` | 自由能 |
| `neb/` | NEB |
| `static/` / `scf/` | 电子结构 |
| `bands/` | 能带 |
| `md/` | 分子动力学 |

扫描逻辑：
1. 遍历项目根目录下所有二级子目录（如 `opt/model1`、`abs/2_1`）
2. 按前缀匹配分类标签，生成任务名 `"{标签}-{子目录名}"`
3. 自动跳过 `old/`、`backup/`、`tmp/` 等目录
4. 检测是否有 OUTCAR → 有则自动设为 `Run`，无则设为 `Pending`
5. **已有记录的子任务不会重复添加**

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

### 3. 一键扫描 + 检查
```bash
python scripts/project_manager.py scan <项目名>   # SSH 扫描，自动发现并归类
python scripts/vasp_check.py                     # 检查所有 Run 子任务
```

### 4. 执行检查
```bash
python scripts/vasp_check.py                    # 检查所有 Run 子任务
python scripts/vasp_check.py test               # 只检查 test 的 Run 子任务
python scripts/vasp_check.py test 结构优化       # 只检查结构优化（无视状态）
```

### 5. 查看结果
```
D:\Tech-data\poscars\HS/
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

## 作业监控 (bjobs)

`jobs_monitor.py` SSH 登录超算运行 `bjobs -l`，解析每个作业并自动匹配到已知项目：

```bash
python scripts/jobs_monitor.py              # 查看所有作业
```

输出字段：JobID | 状态 | 核数 | 队列 | 归属项目 | 子任务 | 目录路径

自动追加内容：
- `blimits` + `busers`：核数配额使用情况、用户作业统计
- `bqueues`：常用 5 个队列状态（PEND/RUN/SUSP）
- `bhosts`：各队列节点组在线/空闲核数
- 交互式队列推荐（综合付费/挂起风险/核数/跨节点通信/NEB整除）

- 自动展开 `$HOME` → `/data/gpfs03/mdye`
- 根据 Execution CWD 匹配到项目 + 子任务
- 未匹配的目录显示原始路径

## VESTA 可视化对比

`vesta_view.py` 一键在 VESTA 中打开 POSCAR 和 CONTCAR，方便查看结构优化前后的变化：

```bash
python scripts/vesta_view.py <目录>        # 打开目录下的 POSCAR + CONTCAR
python scripts/vesta_view.py <文件>        # 打开单个 VASP 文件
python scripts/vesta_view.py              # 打开当前目录下的文件
python scripts/vesta_view.py --vesta <路径> # 指定 VESTA.exe 位置
```

示例：
```bash
python scripts/vesta_view.py D:\Tech-data\poscars\HS\Co4N_0703\abs\2_1
```

VESTA 中叠加对比：
1. CONTCAR 打开时会弹出对话框，选 **"Open as a new phase"**
2. 在 `Edit` → `Edit Data` → `Phase` 中给两个结构设不同颜色
3. 开启 `Show unit cell` 显示晶胞

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
