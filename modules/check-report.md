# 检查与报告模块

从项目检查到 PPT 报告生成的完整流程。

## 第一步：SSH 检查任务状态

**脚本：** `python scripts/vasp_check.py [项目] [子任务]`

对每个 `status=Run` 的子任务，执行以下判定：

```
Step 0: bjobs 查询
  └─ bjobs RUN → 标记 Run（不覆盖，继续下载/分析）
  └─ bjobs PEND → 标记 PEND
  └─ 未找到 → 进入 OUTCAR 判定

Step 1: OUTCAR 判定（仅 bjobs 未命中时执行）
  ├─ General timing + accuracy → Completed
  ├─ General timing + 无accuracy → Failed
  ├─ General timing + I REFUSE → Error
  ├─ 有 OUTCAR 无 timing → Stop（walltime killed）
  └─ 无 OUTCAR → Pending
```

每个子任务额外执行：
- 下载 POSCAR + CONTCAR 到本地 `{LOCAL_BASE}/{项目}/{子任务}/`
- 读取最新续算目录（conN/）的 OUTCAR
- 写入 `.ionic_steps` 文件
- 写入 `作业状态.txt` 汇总文件

## 第二步：更新状态

**自动：** `vasp_check.py` 内部完成。
更新 `vaspcheck_projects.json` 和 `jobs_monitor.py` 的队列数据。

## 第三步：生成 PPT 报告

**脚本：** `python scripts/generate_report.py [--theme dark] [--no-struct]`

流程：
1. 调用 `vasp_check.py`（如未跳过）
2. 调用 `summary_report.py --from-db --from-results {DailyCheck}/.check_results.json`
3. 如需结构图：`struct2ppt.py` 通过 VESTA 渲染 POSCAR vs CONTCAR

也可单独运行：
```bash
python scripts/summary_report.py --from-db                   # 仅报告，不检查
python scripts/summary_report.py --from-db --no-struct        # 跳过结构图
```

## 第四步：结构图渲染规则

**仅当：** `status=Run` 且 ionic steps ≥ 5 时渲染结构对比。
- a/b 轴同页（上下排列），c 轴单独一页
- 保持原图宽高比，不拉伸
- 标题格式：项目/子任务/任务类型

## 状态判定决策树（完整）

```
bjobs 查询
  ├─ RUN → Run（不覆盖，继续监控）
  ├─ PEND → PEND
  └─ 未命中 → 读 OUTCAR
       ├─ General timing + accuracy → Completed
       ├─ General timing + 未收敛 → Failed  
       ├─ 有 OUTCAR + 无 timing → Stop
       └─ 无 OUTCAR → Pending
```

## 渲染触发条件

| 条件 | 是否渲染结构图 |
|------|:---:|
| status=Run | ✅ 每次 |
| ionic_steps < 5 | ❌  跳过 |
| status=Completed/Failed/Stop | ❌ 跳过 |
