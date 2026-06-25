# 项目管理模块

管理 VASP 计算项目和子任务列表，自动扫描远程目录。

## 使用方法

```bash
# 列出所有项目
python scripts/project_manager.py list

# 查看详细表格
python scripts/project_manager.py show

# 添加项目（自动 SSH 扫描远程目录）
python scripts/project_manager.py add <项目名> <远程路径>

# 删除项目
python scripts/project_manager.py remove <项目名>

# 扫描远程目录，自动发现新子任务
python scripts/project_manager.py scan <项目名>

# 手动管理子任务
python scripts/project_manager.py sub add <项目> <子任务名> <目录>
python scripts/project_manager.py sub remove <项目> <子任务名>
python scripts/project_manager.py sub status <项目> <子任务名> <状态>
```

## 自动分类规则

远程目录按前缀自动归类：

| 前缀 | 任务类型 |
|------|---------|
| `opt/` `raw/` | 结构优化 |
| `abs/` `oer/` | 吸附 |
| `static/` `scf/` | 电子结构（自洽） |
| `dos/` `bands/` | 电子结构（态密度/能带） |
| `neb/` | NEB 过渡态 |
| `md/` | 分子动力学 |
| `s8/` | S8 还原 |
| `barrier/` | 分解能垒 |
| `bader/` | Bader 电荷 |
| `frac/` | 自由能矫正 |

忽略目录：`old/` `backup/` `tmp/` `test/` `.trash/` 以及 `con*` 续算目录。

## 项目数据结构

`vaspcheck_projects.json`：
```json
[{
  "name": "项目名",
  "path": "/data/gpfs03/.../远程路径",
  "subs": [
    {"name": "子任务名", "dir": "opt/Fe2O3_110", "status": "Run"}
  ]
}]
```

## 状态流转

```
Pending → Run → Completed  (有 OUTCAR 且收敛)
Pending → Run → Failed     (有 OUTCAR 但未收敛)
Pending → Run → Stop       (walltime 到期)
Pending → PEND             (在队列中等待)
Pending → Error            (I REFUSE 等致命错误)
```

备注：`Run` 状态的任务会被 `vasp_check.py` 自动检查。
