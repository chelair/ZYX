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

## 续算种类

| 类型 | 固定比例 | 偶极矫正 | VASPKit |
|------|:---:|:---:|------|
| slab 优化 | 40% | 否 | 402 Fix by Heights |
| 吸附 | 50% | 是 | 402 Fix by Heights + DIPOL |
| 频率 | 按序号 | 否 | 402 Fix by Indices |

判断依据：子任务名/目录前缀（adsorption→吸附, abs→吸附, opt/slab→slab, freq→频率）

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

续算文件创建后，需手动执行：
1. **VASPKit 402 固定原子**：`vaspkit → 4 → 402 → 3`（Fix by Heights）
2. **DIPOL z 中心**：已自动计算填入 INCAR，无需手动（吸附类型）

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
