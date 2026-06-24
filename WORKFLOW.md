# ZYX Skill 全流程详解

> 从项目添加 → 日常检查 → 续算 → 提交 的完整闭环

---

## 核心工作流（8步）

```
Step 1: 检查/添加项目      project_manager.py add/scan
Step 2: 日常检查           vasp_check.py + problem_detect.py
Step 3: 更新任务状态        vasp_check.py (bjobs + data + JSON + job.info)
Step 4: 生成PPT报告         summary_report.py + struct2ppt.py
Step 5: 确认是否续算        人工判断（配合 diagnose）
Step 6: 确认续算种类        选择 slab/吸附/频率
Step 7: 生成续算文件         job_continue.py --dry-run
Step 8: 确认提交任务        人工确认 → bsub
```

---

## 第一步：检查/添加项目

**脚本：** project_manager.py

```bash
python scripts/project_manager.py add <项目名> <远程路径>
```

自动 SSH 扫描远程目录，按前缀分类写入 JSON。

## 第二步：日常检查

**脚本：** vasp_check.py + problem_detect.py

一次 SSH 在项目目录生成临时 data 文件（find OUTCAR → grep accuracy/timing/energy），避免逐子任务读大文件。

```bash
python scripts/vasp_check.py
```

检查：OUTCAR 收敛、General timing、离子步数、bjobs 在跑。

## 第三步：更新任务状态

**脚本：** vasp_check.py + safe_ops.py

```
bjobs RUN → Run | data OK → Completed | data FAIL → Failed
data STOP → Stop | 无 data → Pending
```

更新 JSON + 写入服务器 job.info。
续算目录优先：取最新 con* 目录 OUTCAR（忽略 fix/）。

## 第四步：生成 PPT 报告

**脚本：** summary_report.py + struct2ppt.py

```bash
python scripts/summary_report.py --from-db
```

Run → 必渲染（仅 IBRION=2/3 的结构优化类任务）| 状态刚变 → 渲染 | 其他 → 跳过。
VESTA CLI a/b/c 三轴 POSCAR vs CONTCAR 对比。

## 第五步：确认是否续算

人工判断，辅助: problem_detect.py (.diagnosis)

| 状态 | 续算? |
|:----:|:------|
| Stop | 续算 |
| Failed | 检查参数后定 |
| Completed | 不用 |
| Error | 人工介入 |

## 第六步：确认续算种类

| 类型 | 固定 | 偶极 |
|------|:----:|:----:|
| slab 优化 | 40% | 否 |
| 吸附 | 50% | 是 |
| 频率 | 按序号 | 否 |

工具：VASPKIT 402

## 第七步：生成续算文件

**脚本：** job_continue.py --dry-run + safe_ops.py

```
1. 确定当前工作目录
2. CONTCAR 完整性校验
3. N = max(con1,con2,...)+1
4. mkdir con{N}/          (无 -p)
5. job.info (pending)     + 同步 JSON
6. cp -n 4 文件 + mv WAVECAR(有完成标志)
7. 调整 INCAR: ISTART=1, ICHARG=0, DIPOL, 固定比例
8. 队列选择: bhosts > bqueues
9. 生成 vasp.lsf, JobName: {项目}_{末段}
10. 输出预览，等待确认
```

## 第八步：确认提交

```
11. bsub < con{N}/vasp.lsf
12. 回填 job_id → job.info (submitted)
13. 同步 JSON: Run, 记录 job_id
```

---

## 脚本索引

| 脚本 | 步骤 | 作用 |
|------|:----:|------|
| project_manager.py | 1 | 添加/扫描项目 |
| vasp_check.py | 2,3 | 检查 + 状态更新 + data 预扫描 |
| problem_detect.py | 2 | 异常诊断 |
| summary_report.py | 4 | PPT 报告 |
| struct2ppt.py | 4 | 结构图渲染 |
| job_continue.py | 7,8 | 续算 + 提交 |
| safe_ops.py | 3,7 | 安全文件操作 + job.info |
| jobs_monitor.py | 7 | 队列推荐 |

| 手册 | 内容 |
|------|------|
| VASPKIT.md | 402 固定 + DIPOL |
| CONTINUE.md | 续算 + 核数 |
| MONITOR.md | 状态 + 队列 |
| SKILL.md | 核心规则 + 命令 |
