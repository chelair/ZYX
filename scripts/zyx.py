"""
ZYX 统一编排器 — VASP 工作流自动化入口

用法:
  python zyx.py check [项目]             检查任务状态
  python zyx.py report [--no-struct]     生成 PPT 报告（使用最新检查结果）
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
sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import DAILY_CHECK_DIR, LOCAL_BASE
RESULTS_FILE = DAILY_CHECK_DIR / ".check_results.json"


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
    results_file = RESULTS_FILE
    params = ["--from-db", "--from-results", str(results_file), "--theme", args.theme]
    if args.no_struct:
        params.append("--no-struct")
    _run("summary_report.py", *params)



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

    # check
    p = sub.add_parser("check", help="Check task status")
    p.add_argument("project", nargs="?", default=None)
    p.add_argument("subtask", nargs="?", default=None)
    p.add_argument("--timeout", type=int, default=15)

    # report
    p = sub.add_parser("report", help="Generate PPT report")
    p.add_argument("--theme", choices=["light","dark"], default="dark")
    p.add_argument("--no-struct", action="store_true", help="Skip structure diagrams")

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
        "diagnose": cmd_diagnose,
        "projects": cmd_projects,
        "jobs": cmd_jobs,
        "scan": cmd_scan,
    }

    dispatch[args.command](args)


if __name__ == "__main__":
    main()
