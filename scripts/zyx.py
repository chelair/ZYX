"""
ZYX 统一编排器 — VASP 工作流自动化入口

用法:
  python zyx.py check [项目]             检查任务状态
  python zyx.py report [--no-struct]     生成 PPT 报告（使用最新检查结果）
  python zyx.py workflow [项目]          check → 状态判定 → continue → report
  python zyx.py continue 项目 子任务     续算：先预览 --dry-run，确认后执行
  python zyx.py diagnose 项目 [子任务]   异常诊断
  python zyx.py projects                项目管理
  python zyx.py jobs                     LSF 作业监控
  python zyx.py scan 项目               扫描远程目录
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = Path("D:/POSCAR/HuaSuan/check")


def _run(script, *args, **kwargs):
    """Run a script in the scripts/ directory"""
    cmd = [sys.executable, str(SCRIPTS_DIR / script)] + list(args)
    print(f"\n[zyx] {' '.join(cmd)}")
    return subprocess.run(cmd, **kwargs)


def _load_projects():
    """Load current project data"""
    pj = SCRIPTS_DIR.parent / "vaspcheck_projects.json"
    if not pj.exists():
        print("[X] 没有项目数据，请先添加项目")
        return []
    with open(pj, "r", encoding="utf-8") as f:
        return json.load(f)


def _find_stopped(projects):
    """Find subtasks with status=Stop that need continuation"""
    stopped = []
    for p in projects:
        for s in p.get("subs", []):
            if s["status"] == "Stop":
                stopped.append((p["name"], s["name"]))
    return stopped


def cmd_check(args):
    """检查任务状态"""
    params = []
    if args.project:
        params.append(args.project)
    if args.subtask:
        params.append(args.subtask)
    _run("vasp_check.py", *params, "--timeout", str(args.timeout))


def cmd_report(args):
    """生成 PPT 报告"""
    results_file = OUTPUT_DIR / "DailyCheck" / ".check_results.json"
    params = ["--from-db", "--from-results", str(results_file), "--theme", args.theme]
    if args.no_struct:
        params.append("--no-struct")
    _run("summary_report.py", *params)


def cmd_workflow(args):
    """完整工作流：check → 状态判定 → continue → report"""
    projects = _load_projects()
    if not projects:
        return

    print("=" * 60)
    print("  ZYX Workflow: Step 1/3 — 检查任务状态")
    print("=" * 60)
    params = []
    if args.project:
        params.append(args.project)
    result = _run("vasp_check.py", *params, "--timeout", str(args.timeout))
    if result.returncode != 0:
        print(f"\n[!] 检查异常退出 (代码 {result.returncode})")
        if not args.force:
            return

    # Find Stop tasks
    print("\n" + "=" * 60)
    print("  ZYX Workflow: Step 2/3 — 状态判定")
    print("=" * 60)
    projects = _load_projects()
    stopped = _find_stopped(projects)

    if stopped:
        print(f"\n  发现 {len(stopped)} 个 Stop 任务可以续算:")
        for proj, sub in stopped:
            print(f"    - {proj} / {sub}")
        print()
        if not args.yes:
            try:
                confirm = input("  是否为这些任务创建续算? (y/N): ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                confirm = "n"
            if confirm != "y":
                print("  跳过续算")
                stopped = []

    for proj, sub in stopped:
        print(f"\n  [续算] {proj} / {sub}")
        _run("job_continue.py", proj, sub, "--yes",
             "--timeout", str(args.timeout))

    # Report
    print("\n" + "=" * 60)
    print("  ZYX Workflow: Step 3/3 — 生成报告")
    print("=" * 60)
    results_file = OUTPUT_DIR / "DailyCheck" / ".check_results.json"
    params = ["--from-db", "--from-results", str(results_file), "--theme", args.theme]
    if args.no_struct:
        params.append("--no-struct")
    _run("summary_report.py", *params)

    print("\n[OK] 工作流完成")


def cmd_continue(args):
    """续算：预览 → 确认 → 执行"""
    print("=" * 60)
    print("  续算预览" if args.dry_run else "  Step 1/2: 预览续算")
    print("=" * 60)
    result = _run("job_continue.py", args.project, args.subtask,
                  "--dry-run", "--timeout", str(args.timeout))
    if result.returncode != 0:
        print("[X] 预览失败，请检查错误信息")
        return
    if args.dry_run:
        return

    # Step 2: confirm and execute
    if not args.yes:
        try:
            confirm = input("\n  预览无误，确认执行? (y/N): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            confirm = "n"
        if confirm != "y":
            print("[跳过] 未确认")
            return

    print("\n" + "=" * 60)
    print("  Step 2/2: 执行续算")
    print("=" * 60)
    params = [args.project, args.subtask, "--yes", "--timeout", str(args.timeout)]
    if args.queue:
        params += ["--queue", args.queue]
    if args.cores:
        params += ["--cores", str(args.cores)]
    _run("job_continue.py", *params)


def cmd_diagnose(args):
    """异常诊断"""
    params = []
    if args.project:
        params.append(args.project)
    if args.subtask:
        params.append(args.subtask)
    _run("problem_detect.py", *params)


def cmd_projects(args):
    """项目管理"""
    _run("project_manager.py", "list")
    print()
    _run("project_manager.py", "show")


def cmd_jobs(args):
    """LSF 作业监控"""
    _run("jobs_monitor.py")


def cmd_scan(args):
    """扫描远程目录"""
    _run("project_manager.py", "scan", args.project,
         "--timeout", str(args.timeout))


def main():
    parser = argparse.ArgumentParser(description="ZYX VASP workflow")
    sub = parser.add_subparsers(dest="command")

    # workflow
    p = sub.add_parser("workflow", help="Check -> Continue -> Report")
    p.add_argument("project", nargs="?", default=None)
    p.add_argument("--theme", choices=["light","dark"], default="dark")
    p.add_argument("--no-struct", action="store_true")
    p.add_argument("--force", action="store_true", help="Continue on check failure")
    p.add_argument("--yes", "-y", action="store_true", help="Auto confirm")
    p.add_argument("--timeout", type=int, default=15, help="SSH timeout")

    # check
    p = sub.add_parser("check", help="Check task status")
    p.add_argument("project", nargs="?", default=None)
    p.add_argument("subtask", nargs="?", default=None)
    p.add_argument("--timeout", type=int, default=15)

    # report
    p = sub.add_parser("report", help="Generate PPT report")
    p.add_argument("--theme", choices=["light","dark"], default="dark")
    p.add_argument("--no-struct", action="store_true", help="Skip structure diagrams")

    # continue
    p = sub.add_parser("continue", help="Job continuation")
    p.add_argument("project")
    p.add_argument("subtask")
    p.add_argument("--queue", default=None)
    p.add_argument("--cores", type=int, default=None)
    p.add_argument("--yes", "-y", action="store_true", help="Auto confirm + submit")
    p.add_argument("--timeout", type=int, default=15)
    p.add_argument("--dry-run", action="store_true", help="Preview only")
    p.add_argument("--cores", type=int, default=None)
    p.add_argument("--queue", default=None)

    # diagnose
    p = sub.add_parser("diagnose", help="Problem diagnosis")
    p.add_argument("project", nargs="?", default=None)
    p.add_argument("subtask", nargs="?", default=None)
    p.add_argument("--timeout", type=int, default=15)

    # projects
    sub.add_parser("projects", help="List projects")

    # jobs
    sub.add_parser("jobs", help="LSF job monitor")

    # scan
    p = sub.add_parser("scan", help="Scan remote directories")
    p.add_argument("project")
    p.add_argument("--timeout", type=int, default=15)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return
    dispatch = {
        "check": cmd_check,
        "report": cmd_report,
        "workflow": cmd_workflow,
        "continue": cmd_continue,
        "diagnose": cmd_diagnose,
        "projects": cmd_projects,
        "jobs": cmd_jobs,
        "scan": cmd_scan,
    }

    dispatch[args.command](args)


if __name__ == "__main__":
    main()
