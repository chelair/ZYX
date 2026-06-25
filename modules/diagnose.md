# 诊断模块

对 VASP 计算结果进行异常检测并给出修复建议。

## 使用方法

```bash
# 诊断单个项目/子任务
python scripts/problem_detect.py <项目名> [子任务名]

# 诊断本地目录
python scripts/problem_detect.py --local <本地目录>
```

## 检测项（9 项）

| 检测项 | 代码 | 严重度 | 触发条件 |
|--------|------|:---:|------|
| SCF 不收敛 | SCF_NOT_CONVERGED | 🟡 | 连续 ≥3 个离子步电子步数 = NELM |
| 离子步未收敛 | IONIC_NOT_CONVERGED | 🟡 | 达 NSW 上限，力未收敛 |
| 力收敛躺平 | FORCE_PLATEAU | 🟡 | 能量方差 < 1e-6 |
| 能量发散 | ENERGY_DIVERGENCE | 🔴 | NaN/Inf 或单调飙升 |
| 能量震荡 | ENERGY_OSCILLATION | 🟡 | dE 正负交替 ≥6 次 |
| 实空间投影错误 | REALSPACE_ERROR | 🔴 | OUTCAR 含 "I REFUSE" |
| 子空间对角化失败 | ZHEGV_FAILED | 🔴 | OUTCAR 含 "ZHEGV" |
| 矩阵非正定 | MATRIX_NOT_POSDEF | 🔴 | OUTCAR 含 "Matrix block" |
| 离子步极少 | TOO_FEW_STEPS | 🟡 | 少于 5 个离子步即结束 |

## 数据来源

- 远程模式：SSH 读取远程 OSZICAR + OUTCAR 尾部 500 行
- 本地模式：读取本地 OSZICAR + OUTCAR(.tail)

## 诊断报告

每个子任务生成两个文件：
- `.diagnosis` — 可读文本报告
- `.diagnosis.json` — JSON 格式（供程序读取）

## 修复建议速查

| 症状 | 建议操作 |
|------|---------|
| SOL_NOT_CONVERGED | ALGO=Fast→Normal/All, AMIX=0.2, BMIX=0.0001 |
| IONIC_NOT_CONVERGED | 力下降中→续算; 力躺平→IBRION=1 |
| ENERGY_DIVERGENCE | 检查原子间距/KPOINTS |
| ENERGY_OSCILLATION | 电子步：减小 AMIX/BMIX; 离子步：减小 POTIM |
| REALSPACE_ERROR | LREAL = .FALSE. |
| ZHEGV_FAILED | 调小 POTIM，检查原子间距 |
| NEGATIVE_VOLUME | ISIF=2 → ISIF=3 + 提高 ENCUT |
