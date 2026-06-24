# Changelog

## v4.0 — 架构重构，代码质量全面升级

### 架构重构
- **模块拆分**：vasp_check.py 18KB 拆为编排层 + outcar_analyzer.py + file_transfer.py，降低耦合
- **项目持久化统一**：新建 project_store.py，load_projects() 从 5 处重复收敛为单例
- **配置集中化**：新增 config.py，统一管理 LOCAL_BASE/VESTA_EXE/SSH_KEY/HPC 路径常量
- **SSH 连接共享**：新建 ssh_manager.py，同主机复用连接，健康检查自动重建
- **续算流程实现**：job_continue.py 完整两步式（dry-run → 确认提交），含 CONTCAR 校验/队列推荐/WAVECAR 安全移动/job.info 回填

### 状态判定完善
- **bjobs 集成**：新增 _check_bjobs()，严格遵循 MONITOR.md 决策树：bjobs RUN→Run，PEND→PEND，否则 OUTCAR 判定
- **修复 ibrion_val 未定义**：OUTCAR 不存在时不再崩溃
- **判定标准内嵌**：决策规则写入 docstring，文档代码不再分离

### 代码质量
- **死代码清理**：7 处未使用导入、3 处 SSH 重构残代码、1 处无用 SSHManager 导入
- **语法修复**：修复 11 处编译错误（import 错位、try 块断裂、残余 parse_host 等）
- **冗余消除**：load_projects 5→1、save_projects 3→1、HPC_HOST 4→1

### PPT 报告优化
- **表格**：7 列→5 列，列宽适配屏幕，行高增大，子任务独立一行
- **VESTA 版面**：a/b 同页上下排 + c 单独一页，保持宽高比不拉伸
- **标题**：改用 项目/子任务/类型 格式
- VESTA 等待 [1,1.5,2.5]→[2,5,8]s，_png_size() 空文件保护

### Bug 修复
- problem_detect.py 无条件 sys.exit(1) → 移除
- _find_struct_dirs 英文匹配中文数据 → 修复
- job_continue/jobs_monitor try/finally 不匹配 → 清理
- UTF-8 BOM 污染 → 批量清除

# Changelog

## v3.2 — VASPKit Integration, Dipole Correction, Status Refinement

### Documentation
- **SKILL.md**: 18 sections, full VASPKit 402 workflow, dipole correction,
  fix rules by scenario (slab 40% / adsorption 50% / frequency by indices),
  DIPOL center calculation, status determination flowchart, queue decision
- **scripts/.input_reference.md**: complete INCAR/KPOINTS/POTCAR reference,
  job core estimation, dipole correction, VASPKit usage

### New Features
- **vasp_check.py**: data file pre-scan replaces per-subtask OUTCAR reading
- **safe_ops.py**: read_remote_job_info(), parse_job_info()
- **project_manager.py**: auto-scan after add, raw/ + oer/ classification

### Workflow
- **Dipole correction**: calculate z geometric center, DIPOL = 0.5 0.5 {z}
- **VASPKit 402**: Fix by Heights (z_min z_max -> Fractional -> all)
- **Status detection**: bjobs first, latest con* OUTCAR, ignore fix/
- **job.info**: visible file, synced with JSON on every state change
## v3.1 — Continuation Workflow & Job Identification

### New Features
- **job.info**: Server-side job identification file (primary ID over JSON)
  - Generated at continuation dir creation with status=pending
  - Updated after bsub with job_id + status=submitted
  - No Chinese characters, English identifiers only
- **Deep sync**: job.info ↔ vaspcheck_projects.json bidirectional status sync
- **Two-step continuation flow**: dry-run generation → user confirm → submit
- **read_remote_job_info()**: SSH read and parse job.info for vasp_check/jobs_monitor

### Improvements
- **problem_detect.py**: 9 detection rules integrated into vasp_check.py
- **safe_ops.py**: Added parse_job_info() and read_remote_job_info()
- **vasp_check.py**: Priority reads job.info for project matching
- **jobs_monitor.py**: match_project() uses job.info as primary source
- **SKILL.md**: Queue decision workflow (bhosts > bqueues), .job_info → job.info,
  continuation flow restructured, job core estimation rules
- **submit/vasp.lsf**: Fixed rm- rf bug, STOPCAR graceful exit
- **templates/**: static/dos/md INCAR templates added

### Documentation
- **scripts/.input_reference.md**: Full reference for INCAR/KPOINTS/POTCAR/submit/job_info
- **conskill.md**: Planning doc for future implementation

## v3.0 — Skill Restructure & Continuation Planning

### Documentation
- **SKILL.md**: Full restructure — core rules (cp -n / mkdir / atomic write),
  new commands (continue/diagnose/download), new sections (Job续算/异常诊断/
  文件下载/渲染触发条件), updated data model and file tree
- **scripts/.input_reference.md**: New reference document recording INCAR parameter
  habits, KPOINTS rule (k×a>20), POTCAR generation (pos2pot), submission script
  conventions, continuation scenarios

### New Features (Planned)
- **scripts/safe_ops.py**: Security layer — cp -n / mkdir(no -p) / mv -n / atomic
  write (tmp+fsync+rename), no-delete guard, TOCTOU-free design
- **Job continuation workflow**: CONTCAR integrity check, con{N}/ directory creation,
  cp -n safe copy, WAVECAR mv on completion flag, node status check via
  bhosts/bqueues/blimits, queue recommendation, .job_info identification file
- **Structure render trigger**: Status-change tracking via .last_status snapshot;
  Run tasks always rendered (monitoring), status-changed tasks rendered once

### Templates
- **templates/relax.incar**: Updated with clearer sectioned comments
- **templates/static.incar**: New — self-consistent calculation (NSW=0, IBRION=-1)
- **templates/dos.incar**: New — DOS extension (NEDOS/EMIN/EMAX)
- **templates/md.incar**: New — Nose-Hoover NVT AIMD, anneal guidance
- **submit/vasp.lsf**: New — STOPCAR graceful walltime exit mechanism

## v2.1 — Code Review Fixes & VESTA CLI Integration

### Bug Fixes
- **ssh_connect.py**: Fix interactive cd bug — use subprocess ssh for real terminal; add Ed25519Key auto-detection
- **project_manager.py**: Fix path prefix bug (d.replace -> startswith); Shell injection protection;
  OUTCAR Voluntary context switches check; early exit on find errors
- **vasp_check.py**: Fix int(ibrion_val) crash with try/except; narrow con*/ -> con[0-9]*/;
  extract hardcoded path to LOCAL_BASE constant
- **jobs_monitor.py**: Switch bjobs -l to bjobs -o structured output; fix path replace ->
  startswith; isalnum node prefix detection

### New Features
- **struct2ppt.py**: VESTA CLI a/b/c axis rendering with adaptive backoff (1.0s/1.5s/2.5s);
  POSCAR vs CONTCAR side-by-side comparison; no-stretch image sizing
- **Ionic step gate**: vasp_check remote-counts free energy TOTEN in OUTCAR,
  writes .ionic_steps; struct2ppt skips CONTCAR if <5 steps
- **Error status**: Detect "I REFUSE TO CONTINUE" in OUTCAR -> [X] error status

## v2.0 — Full VASP Workflow Automation

- project_manager.py: scan command with 12 prefix rules
- vasp_check.py: SSH convergence check, auto-status, download
- summary_report.py: PPT with per-project grouping
- struct2ppt.py: VESTA CLI rendering
- generate_report.py: unified entrypoint
- jobs_monitor.py: LSF monitoring + queue recommendation
- vesta_view.py: VESTA GUI launcher

## v1.0 — Initial Version

- Basic SSH connection
- Project/subtask CRUD
- VASP convergence check
- Basic status flow
