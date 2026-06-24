"""
VASP 计算结果检查 — 编排层

遍历每个项目的 Run 子任务，编排 data 扫描 → OUTCAR 分析 → 文件下载 → 状态更新。

用法:
  python scripts/vasp_check.py                     检查所有 Run 子任务
  python scripts/vasp_check.py <项目名>             检查指定项目的 Run 子任务
  python scripts/vasp_check.py <项目名> <子任务名>    检查指定子任务

新建模块:
  - outcar_analyzer.py    OUTCAR 扫描/分析
  - file_transfer.py      SFTP 文件下载
"""
import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from summary_report import write_summary
from safe_ops import read_remote_job_info
from config import LOCAL_BASE, DAILY_CHECK_DIR, SSH_KEY_DEFAULT
from project_store import load_projects, save_projects

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ssh_connect import parse_host, check_remote_dir
from ssh_manager import SSHManager
from outcar_analyzer import scan_data_file, check_outcar, count_ionic_steps_remote
from file_transfer import download_file

SKILL_DIR = Path(__file__).resolve().parent.parent
PROJECTS_FILE = SKILL_DIR / "vaspcheck_projects.json"
HPC_HOST = "mdye@hpc.xmu.edu.cn"
HPC_PORT = 22



# ── MONITOR.md Step 1: bjobs 查询 ──
def _check_bjobs(client, remote_dir):
    """SSH 运行 bjobs 检查作业状态
    
    优先级: job.info.job_id > 目录路径匹配
    Returns:
        "Run"  — bjobs 显示 RUN
        "PEND" — bjobs 显示 PEND  
        None  — 未找到作业（需回退 OUTCAR 判定）
    """
    try:
        # 先查 job.info 中的 job_id
        job_info = read_remote_job_info(client, remote_dir)
        job_id = ""
        if job_info and "submit" in job_info:
            job_id = job_info["submit"].get("job_id", "")
        
        if job_id and job_id.isdigit():
            stdin, stdout, _ = client.exec_command(
                f'bjobs -noheader -o "stat" {job_id} 2>/dev/null'
            )
            stat = stdout.read().decode().strip()
        else:
            # 无 job_id，按工作目录匹配
            stdin, stdout, _ = client.exec_command(
                f'bjobs -noheader -o "stat cwd" 2>/dev/null | grep "{remote_dir}"'
            )
            stat = stdout.read().decode().strip()
        
        if not stat:
            return None
        
        # bjobs stat: RUN / PEND / SSUSP / USUSP / DONE / EXIT
        if "RUN" in stat:
            return "Run"
        if "PEND" in stat:
            return "PEND"
        # 其他状态(SUSP/DONE/EXIT)表示作业已结束，回退 OUTCAR 判定
        return None
    except Exception:
        return None
def check_subtask(client, project, subtask, data_cache=None):
    """检查单个子任务，返回汇总行数据，若已收敛自动更新状态

    编排流程:
      bjobs 查询 → 状态判定(依 MONITOR.md) → 下载 POSCAR/CONTCAR → 定位续算目录
      → OUTCAR 收敛分析 → ionic 步数 → 结构图渲染
    """
    # 优先读取远程 job.info 做身份校验
    remote_base = f"{project['path']}/{subtask['dir']}"
    ji = read_remote_job_info(client, remote_base)
    if ji and "submit" in ji:
        s = ji["submit"]
        ji_proj = s.get("project", "")
        ji_sub = s.get("subtask", "")
        if ji_proj and ji_proj != project["name"]:
            print("  [!] job.info project '" + str(ji_proj) + "' not match JSON '" + str(project["name"]) + "'")
        if ji_sub and ji_sub != subtask["dir"]:
            print(f"  [!] job.info 子任务 '{ji_sub}' 不匹配 JSON '{subtask['dir']}'")
        print(f"  [job.info] {s.get('job_name', '?')} [{s.get('status', '?')}]")

    proj_name = project["name"]
    sub_name = subtask["name"]
    sub_dir = subtask["dir"]
    base_path = project["path"]
    remote_dir = f"{base_path}/{sub_dir}"
    local_dir = LOCAL_BASE / proj_name / sub_name

    print(f"\n{'='*60}")
    print(f" {proj_name} / {sub_name}")
    print(f" {remote_dir}")
    print(f"{'='*60}")

    local_dir.mkdir(parents=True, exist_ok=True)

    if not check_remote_dir(client, remote_dir):
        return {"proj": proj_name, "sub": sub_name, "status": "连接失败",
                "energy": "", "poscar": "[X]", "contcar": "[X]", "task_type": ""}


    # ── Step 0: bjobs 检查（依 MONITOR.md 决策树）──
    bjobs_status = _check_bjobs(client, remote_dir)
    if bjobs_status:
        old = subtask["status"]
        if subtask["status"] != bjobs_status:
            subtask["status"] = bjobs_status
            print(f"\n[状态] bjobs → {old} -> [{bjobs_status}]")
        else:
            print(f"\n[bjobs] 确认: {bjobs_status}")
        # 如果 bjobs 确认在跑，直接标记 Run，跳过 OUTCAR 状态覆盖
        # 但仍然下载和分析 OUTCAR（用于结构图和监控）

    # 下载 POSCAR / CONTCAR
    sftp = client.open_sftp()
    poscar_ok = download_file(sftp, f"{remote_dir}/POSCAR", local_dir / "POSCAR", "POSCAR")
    contcar_ok = download_file(sftp, f"{remote_dir}/CONTCAR", local_dir / "CONTCAR", "CONTCAR")

    # 查找最新续算目录
    work_dir = remote_dir
    try:
        stdin, stdout, stderr = client.exec_command(
            f"ls -d {remote_dir}/con[0-9]*/ 2>/dev/null | sort -t'n' -k2 -n"
        )
        con_dirs = stdout.read().decode().strip().split()
        if con_dirs:
            latest_con = con_dirs[-1].rstrip("/")
            work_dir = latest_con
            con_name = latest_con.rstrip("/").split("/")[-1]
            print(f"\n 发现续算目录: {con_name}（共 {len(con_dirs)} 个续算），检查最新结果")
    except Exception:
        pass

    # 检查 OUTCAR 收敛状态
    print(f"\n 检查 OUTCAR 收敛状态:")
    conv_status = ""
    energy = ""
    job_finished = False
    task_type = ""
    try:
        sftp.stat(f"{work_dir}/OUTCAR")
        attr = sftp.stat(f"{work_dir}/OUTCAR")
        print(f"    {work_dir}/OUTCAR  ({attr.st_size / 1024:.1f} KB)")
        conv_status, energy, job_finished, task_type, ibrion_val = check_outcar(client, work_dir)
    except FileNotFoundError:
        print(f"   [!] OUTCAR 不存在")
        conv_status = "无OUTCAR"
        ibrion_val = ""

    # 远程读取 ionic step 数（优先用 cache）
    ionic_steps = 0
    if data_cache:
        base_path = project["path"]
        rel_path = "." + work_dir.replace(base_path, "", 1)
        cached_entry = data_cache.get(base_path, {}).get(rel_path, {})
        try:
            ionic_steps = int(cached_entry.get("ionic", "0"))
        except Exception:
            pass
    if ionic_steps == 0:
        ionic_steps = count_ionic_steps_remote(client, work_dir)
    (local_dir / ".ionic_steps").write_text(str(ionic_steps), encoding="utf-8")

    if subtask["status"] == "Pending":
        if conv_status != "无OUTCAR":
            subtask["status"] = "Run"
            print(f"\n[状态] Pending -> [Run] (检测到OUTCAR)")
        else:
            pass
    # 检查 OSZICAR
    try:
        sftp.stat(f"{remote_dir}/OSZICAR")
        stdin, stdout, stderr = client.exec_command(f"tail -3 {remote_dir}/OSZICAR")
        tail = stdout.read().decode().strip()
        if tail:
            print(f"\n    OSZICAR 末尾:")
            for line in tail.split("\n"):
                print(f"      {line}")
    except FileNotFoundError:
        pass

    sftp.close()

    # 自动更新状态：根据收敛性和是否结束
    # ── 依 MONITOR.md: OUTCAR 状态覆盖（仅当 bjobs 未命中时） ──
    # bjobs RUN → 已在 Step 0 处理，此处不覆盖
    # bjobs PEND → 已在 Step 0 处理，此处不覆盖
    if subtask["status"] not in ("Run", "PEND", "Pending", "Completed"):
        if conv_status == "无OUTCAR":
            subtask["status"] = "Pending"
            print(f"\n[状态] -> [Pending] (无OUTCAR)")
        elif job_finished and conv_status in ("已收敛", "已完成"):
            subtask["status"] = "Completed"
            print(f"\n[状态] -> [OK] Completed (accuracy reached)")
        elif job_finished:
            subtask["status"] = "Failed"
            print(f"\n[状态] -> [X] Failed (finished, not converged)")
        elif conv_status not in ("无OUTCAR", "解析失败"):
            # OUTCAR exists but no timing → possibly stopped
            subtask["status"] = "Stop"
            print(f"\n[状态] -> [Stop] (OUTCAR exists, job not running)")

    # 写入子任务状态文件
    status_path = local_dir / "作业状态.txt"
    with open(status_path, "w", encoding="utf-8") as f:
        f.write(f"项目: {proj_name}\n")
        f.write(f"子任务: {sub_name}\n")
        f.write(f"路径: {remote_dir}\n")
        f.write(f"检查时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("-" * 30 + "\n")
        f.write(f"POSCAR: {'[V]' if poscar_ok else '—'}\n")
        f.write(f"CONTCAR: {'[V]' if contcar_ok else '—'}\n")
        f.write(f"OUTCAR: {conv_status}\n")
        clean_energy = energy.strip()
        if energy and "TOTEN" in energy:
            try:
                num = energy.split("=")[-1].strip().replace(" eV", "").strip()
                clean_energy = f"{float(num):.8f}"
            except Exception:
                pass
        f.write(f"能量: {clean_energy} eV\n")

    print(f"\n 已写入: {status_path}")

    return {
        "proj": proj_name,
        "sub": sub_name,
        "status": conv_status,
        "energy": energy,
        "poscar": "[V]" if poscar_ok else "—",
        "contcar": "[V]" if contcar_ok else "—",
        "task_type": task_type,
        "ibrion": ibrion_val if ibrion_val and ibrion_val.lstrip("-").isdigit() else "",
    }


def main():
    parser = argparse.ArgumentParser(description="VASP 计算结果检查")
    parser.add_argument("project", nargs="?", default=None, help="项目名称")
    parser.add_argument("subtask", nargs="?", default=None, help="子任务名称")
    parser.add_argument("--host", default=HPC_HOST)
    parser.add_argument("--port", type=int, default=HPC_PORT)
    parser.add_argument("--key", default=str(SSH_KEY_DEFAULT))
    parser.add_argument("--scan", action="store_true", help="先扫描再检查（自动发现新子目录）")
    parser.add_argument("--timeout", type=int, default=15)
    args = parser.parse_args()

    # 扫描模式
    if args.scan:
        print("=" * 60)
        print("  扫描模式：先自动发现子目录，再检查")
        print("=" * 60)
        pm_script = str(Path(__file__).resolve().parent / "project_manager.py")
        target_projects = [args.project] if args.project else [p["name"] for p in load_projects()]
        for pn in target_projects:
            cmd = [sys.executable, pm_script, "scan", pn, "--host", args.host,
                   "--port", str(args.port), "--key", args.key, "--timeout", str(args.timeout)]
            subprocess.run(cmd, check=False)

    projects = load_projects()
    targets = []
    for proj in projects:
        for sub in proj.get("subs", []):
            if args.project and proj["name"] != args.project:
                continue
            if args.subtask and sub["name"] != args.subtask:
                continue
            if not args.subtask and sub["status"] != "Run":
                continue
            targets.append((proj, sub))

    if not targets:
        print(" 没有符合条件的待检查项")
        print("   请先用 project_manager.py 添加子任务并设为 Run 状态")
        sys.exit(0)

    print(f" 计划检查 {len(targets)} 项")
    for proj, sub in targets:
        print(f"   - {proj['name']} / {sub['name']}  ({proj['path']}/{sub['dir']})")

    mgr = SSHManager()
    try:
        username, hostname, client = mgr.get_parsed(args.host, args.port, args.key, timeout=args.timeout)
        print(f"[OK] 已连接到 {username}@{hostname}\n")

        # 预扫描所有目标项目的 data 文件
        data_cache = {}
        target_paths = set()
        for proj, sub in targets:
            target_paths.add(proj["path"])
        for p in projects:
            if p["path"] in target_paths and p["path"] not in data_cache:
                print(f"  [扫描] {p['name']} ...")
                data_cache[p["path"]] = scan_data_file(client, p["path"])

        results = []
        for proj, sub in targets:
            result = check_subtask(client, proj, sub, data_cache)
            results.append(result)
    finally:
        mgr.close_all()
        print("\n连接已断开")

    save_projects(projects)
    if results:
        write_summary(results, DAILY_CHECK_DIR)
        print(f"\n 项目文件已更新（自动将已收敛子任务标记为 Completed）")


if __name__ == "__main__":
    main()
