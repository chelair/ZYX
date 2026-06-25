# 续算模块

为未收敛/停止的作业创建 conN/ 续算目录并提交。

## 前置判断

根据 vasp_check 检查结果决定是否续算：

| 状态 | 操作 |
|:----:|------|
| Stop | ✅ 直接续算 |
| Failed | 🔍 先 diagnose 检查参数 |
| Completed | ❌ 不需要 |
| Error | ⚠️ 人工介入 |

## 计算类型识别

根据 INCAR 中 IBRION 和子任务目录前缀自动判断，无需手动指定。

## 执行流程

### Step 1: 预览（必须先执行）

```bash
python scripts/job_continue.py <项目名> <子任务名> --dry-run
```

输出预览：
- 当前工作目录和最新 conN
- CONTCAR 完整性校验结果
- 新续算编号 con{N}
- 文件复制计划（cp -n）
- WAVECAR 移动计划（仅 OUTCAR 有 finish 标志时）
- INCAR 调整预览（ISTART=1, ICHARG=0, LWAVE=.T., DIPOL 自动计算）
- bhosts 节点空闲状态
- 队列推荐和选择
- 提交预览（JobName ≤9 字符，仅 [A-Za-z0-9_]）

### Step 2: 执行

```bash
# 实际创建（不提交）
python scripts/job_continue.py <项目名> <子任务名> --no-submit --queue <队列> --cores <核数>

# 自动提交（跳过确认）
python scripts/job_continue.py <项目名> <子任务名> --yes --queue <队列> --cores <核数>
```

### Step 3: 手动后续操作

续算文件创建后检查 INCAR（DIPOL 已自动计算填入，吸附类型）。
固定原子操作请手动运行 VASPKit 402。

### Step 4: 提交

```bash
bsub < {path}/con{N}/vasp.lsf
```

## 续算目录规则

```
{project_path}/{sub_dir}/
  ├── con1/    ← 第一次续算
  ├── con2/    ← 第二次续算
  ├── con3/    ← 同级排列，不嵌套
  └── ...
```

如 sub_dir 本身已是 conN，则往上一层找同级目录创建 con{N+1}。

## CONTCAR 完整性校验

读取 POSCAR 第 6/7 行获取原子数，检查 CONTCAR 末尾是否完整。损坏的 CONTCAR 不允许续算。

## 队列选择

```
P0: bhosts（仅 STATUS=ok 的节点，按队列映射统计 free >= ptile 的节点数）
P1: 按优先级排序：能放下 > 免费 > 低挂起风险
P2: 无合适队列时报告并建议调整核数或使用付费队列
```

## INCAR 自动调整

| 参数 | 调整 |
|------|------|
| ISTART | 1 |
| ICHARG | 0 |
| LWAVE | .TRUE. |
| LDIPOL | .TRUE.（仅吸附） |
| IDIPOL | 3（仅吸附） |
| DIPOL | 0.5 0.5 {z_center}（自动计算） |

## 精确脚本调用

```bash
# 方式一：zyx 统一入口（推荐）
python scripts/zyx.py continue 项目 子任务  --yes --queue charge --cores 24
python scripts/zyx.py continue 项目 子任务  --dry-run  # 仅预览

# 方式二：直接调用
python scripts/job_continue.py 项目 子任务 --dry-run  # 预览
python scripts/job_continue.py 项目 子任务 --yes --queue charge --cores 24  # 自动提交
python scripts/job_continue.py 项目 子任务 --queue ocean_530_1day --cores 48 --no-submit  # 仅生成不提交
```

## bhosts 队列选择逻辑

1. SSH bhosts，只取 STATUS=ok 的节点
2. 按节点名前缀匹配队列范围（hd→ocean, s→normal_1day_new, b→normal_2week）
3. 统计每个队列 free >= ptile 的节点数
4. 排序：能放下 → 免费 → 低挂起风险
5. 无合适队列时自动选择 charge（付费）

## 已自动处理

- KPOINTS 缺失 → 自动 cp IBZKPT → KPOINTS
- DIPOL → 自动 SSH 读 POSCAR 计算 z_center
- conN 目录 → 自动排除 0 字节 CONTCAR 和待提交目录
- JobName → 自动缩短至 ≤9 字符 [A-Za-z0-9_] 格式
