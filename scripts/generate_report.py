"""
VASP 报告生成 — 统一入口

一键完成：检查 → 汇总PPT → 结构对比图

用法:
  python scripts/generate_report.py              # 检查 + 汇总PPT + 结构图
  python scripts/generate_report.py --no-check   # 只从数据库生成PPT + 结构图
  python scripts/generate_report.py --no-struct  # 检查 + 汇总PPT，不加结构图
  python scripts/generate_report.py --theme dark # 深色主题
"""
import argparse
import subprocess
import sys
from pathlib import Path


from config import LOCAL_BASE

SCRIPTS_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = LOCAL_BASE


def main():
    parser = argparse.ArgumentParser(description="VASP \u62a5\u544a\u751f\u6210 \u2014 \u7edf\u4e00\u5165\u53e3")
    parser.add_argument("--no-check", action="store_true", help="\u4e0d\u6267\u884c\u68c0\u67e5\uff0c\u76f4\u63a5\u4ece\u6570\u636e\u5e93\u751f\u6210\u62a5\u544a")
    parser.add_argument("--no-struct", action="store_true", help="\u4e0d\u6dfb\u52a0\u7ed3\u6784\u5bf9\u6bd4\u56fe")
    parser.add_argument("--theme", choices=["light", "dark"], default="light", help="PPT \u4e3b\u9898")
    parser.add_argument("--project", default=None, help="\u4ec5\u68c0\u67e5\u6307\u5b9a\u9879\u76ee")
    args = parser.parse_args()

    # 1. \u68c0\u67e5 (optional)
    if not args.no_check:
        print("=" * 60)
        print("  Step 1/2: \u68c0\u67e5\u5b50\u4efb\u52a1\u72b6\u6001")
        print("=" * 60)
        check_args = [sys.executable, str(SCRIPTS_DIR / "vasp_check.py")]
        if args.project:
            check_args.append(args.project)
        result = subprocess.run(check_args)
        if result.returncode != 0:
            print("[X] Check failed (code=" + str(result.returncode) + ")")
            sys.exit(result.returncode)
    else:
        print("  [\u8df3\u8fc7\u68c0\u67e5] \u76f4\u63a5\u4ece\u6570\u636e\u5e93\u751f\u6210\u62a5\u544a")

    # 2. \u751f\u6210 PPT
    print()
    print("=" * 60)
    print("  Step 2/2: \u751f\u6210\u6c47\u603b\u62a5\u544a PPT")
    print("=" * 60)

    report_args = [
        sys.executable, str(SCRIPTS_DIR / "summary_report.py"),
        "--from-db",
        "--from-results", str(OUTPUT_DIR / "DailyCheck" / ".check_results.json"),
        "--theme", args.theme,
        "--theme", args.theme,
    ]
    if args.no_struct:
        report_args.append("--no-struct")
    subprocess.run(report_args)

    print()
    print("[OK] \u5168\u90e8\u5b8c\u6210")


if __name__ == "__main__":
    main()