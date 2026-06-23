"""

VASP 计算结果检查 — 遍历每个项目的 Run 子任务，下载结果并检查收敛性

用法:

  python scripts/vasp_check.py                     检查所有 Run 子任务

  python scripts/vasp_check.py <项目名>             检查指定项目的 Run 子任务

  python scripts/vasp_check.py <项目名> <子任务名>    检查指定子任务

输出:

  D:\Tech-data\poscars\HS/<项目名>/<子任务名>/     POSCAR, CONTCAR, 作业状态.txt

  D:\Tech-data\poscars\HS/汇总报告.txt             所有检查结果的汇总表格

"""

import argparse
import json
import os
import subprocess
import sys

from datetime import datetime

from wcwidth import wcswidth

from pathlib import Path
from summary_report import write_summary, pad, clean_energy_str

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ssh_connect import parse_host, create_ssh_client, check_remote_dir

DOWNLOAD_FILES = ["POSCAR", "CONTCAR"]

SKILL_DIR = Path(__file__).resolve().parent.parent

PROJECTS_FILE = SKILL_DIR / "vaspcheck_projects.json"

HPC_HOST = "mdye@hpc.xmu.edu.cn"

HPC_PORT = 22

def load_projects():

    if not PROJECTS_FILE.exists():

        print(f"[X] 找不到项目文件: {PROJECTS_FILE}")

        print("请先用 project_manager.py 添加项目")

        sys.exit(1)

    with open(PROJECTS_FILE, "r", encoding="utf-8") as f:

        return json.load(f)

def save_projects(projects):

    with open(PROJECTS_FILE, "w", encoding="utf-8") as f:

        json.dump(projects, f, ensure_ascii=False, indent=2)

def download_file(sftp, remote_path, local_path, fname):

    try:

        sftp.stat(remote_path)

        sftp.get(remote_path, str(local_path))

        size = local_path.stat().st_size / 1024

        print(f"   [OK] {fname}  ({size:.1f} KB)")

        return True

    except FileNotFoundError:

        print(f"   [!] {fname}  不存在，跳过")

    except Exception as e:

        print(f"   [X] {fname}  下载失败: {e}")

    return False

def check_outcar(client, remote_dir):

    """返回 (status_label, energy, job_finished)

    

    检测逻辑:

      - 读取 INCAR 中 IBRION 确定任务类型

      - IBRION=2(优化)/3(NEB): 必须 accuracy 才算收敛

      - IBRION=-1(SCF): 跑完就算完成

    """

    cmd = (

        f'cd {remote_dir}; '

        f'ibrion=$(grep -i "IBRION" INCAR 2>/dev/null | tail -1 | awk -F"=" "{{print \\$2}}" | awk "{{print \\$1}}"); '

        f'accuracy=$(grep -c "reached required accuracy" OUTCAR 2>/dev/null || echo 0); '

        f'finished=$(grep -c "General timing and accounting informations for this job:" OUTCAR 2>/dev/null || echo 0); '

        f'last_energy=$(grep "free  energy   TOTEN  =" OUTCAR 2>/dev/null | tail -n 1); '

        f'if [ "$finished" -gt 0 ] 2>/dev/null; then '

        f'  if [ "$accuracy" -gt 0 ] 2>/dev/null; then '

        f'    echo "CONVERGED"; echo "$ibrion"; echo "$last_energy"; '

        f'  elif [ -n "$last_energy" ]; then '

        f'    if [ "$ibrion" = "2" ] || [ "$ibrion" = "3" ]; then '

        f'      echo "NOT_CONVERGED_FINISHED"; echo "$ibrion"; echo "$last_energy"; '

        f'    else '

        f'      echo "COMPLETED"; echo "$ibrion"; echo "$last_energy"; '

        f'    fi; '

        f'  else '

        f'    echo "FINISHED_NO_RESULT"; echo "$ibrion"; '

        f'  fi; '

        f'else '

        f'  if [ "$accuracy" -gt 0 ] 2>/dev/null; then '

        f'    echo "CONVERGED_RUNNING"; echo "$ibrion"; echo "$last_energy"; '

        f'  elif [ -n "$last_energy" ]; then '

        f'    echo "NOT_CONVERGED_WITH_ENERGY"; echo "$ibrion"; echo "$last_energy"; '

        f'  else '

        f'    echo "NOT_CONVERGED_NO_ENERGY"; echo "$ibrion"; '

        f'  fi; '

        f'fi'

    )

    stdin, stdout, stderr = client.exec_command(cmd)

    output = stdout.read().decode().strip()

    lines = output.split("\n")

    status = lines[0] if lines else "UNKNOWN"

    ibrion_val = lines[1] if len(lines) > 1 else ""

    energy = lines[2] if len(lines) > 2 else ""

    type_tag = {2: "结构优化", 3: "NEB", -1: "SCF"}

    calc_type = type_tag.get(int(ibrion_val)) if ibrion_val else ""

    if status == "CONVERGED":

        print(f"      [OK] {calc_type} 已收敛，作业已完成")

        print(f"       {clean_energy_str(energy)}")

        return "已收敛", energy, True, "结构优化" if ibrion_val == "2" else "NEB" if ibrion_val == "3" else "SCF"

    elif status == "COMPLETED":

        print(f"      [OK] {calc_type} 已完成")

        print(f"       {clean_energy_str(energy)}")

        return "已完成", energy, True, "结构优化" if ibrion_val == "2" else "NEB" if ibrion_val == "3" else "SCF"

    elif status == "NOT_CONVERGED_FINISHED":

        print(f"      [X] {calc_type} 作业已结束但未收敛")

        print(f"       {clean_energy_str(energy)}")

        return "未收敛", energy, True, "结构优化" if ibrion_val == "2" else "NEB" if ibrion_val == "3" else "SCF"

    elif status == "FINISHED_NO_RESULT":

        print(f"      [X] 作业已结束，但无能量记录")

        return "未收敛", "", True, ""

    elif status == "CONVERGED_RUNNING":

        print(f"       {calc_type} 已收敛（作业仍在运行中）")

        print(f"       {clean_energy_str(energy)}")

        return "收敛中", energy, False, "结构优化" if ibrion_val == "2" else "NEB" if ibrion_val == "3" else "SCF"

    elif status == "NOT_CONVERGED_WITH_ENERGY":

        print(f"      [!] {calc_type} 未收敛（有能量记录，可能在运行）")

        print(f"       {clean_energy_str(energy)}")

        return "未收敛", energy, False, "结构优化" if ibrion_val == "2" else "NEB" if ibrion_val == "3" else "SCF"

    elif status == "NOT_CONVERGED_NO_ENERGY":

        print(f"      [X] 未收敛，无能量记录")

        return "未收敛", "无能量记录", False, ""

    return "解析失败", "", False, ""

def check_subtask(client, project, subtask):

    """检查单个子任务，返回汇总行数据，若已收敛自动更新状态"""

    proj_name = project["name"]

    sub_name = subtask["name"]

    sub_dir = subtask["dir"]

    base_path = project["path"]

    remote_dir = f"{base_path}/{sub_dir}"

    local_dir = Path("D:/Tech-data/poscars/HS") / proj_name / sub_name

    print(f"\n{'='*60}")

    print(f" {proj_name} / {sub_name}")

    print(f" {remote_dir}")

    print(f"{'='*60}")

    local_dir.mkdir(parents=True, exist_ok=True)

    if not check_remote_dir(client, remote_dir):

        return {"proj": proj_name, "sub": sub_name, "status": "连接失败",

                "energy": "", "poscar": "[X]", "contcar": "[X]", "task_type": ""}

    # 下载

    sftp = client.open_sftp()

    poscar_ok = download_file(sftp, f"{remote_dir}/POSCAR", local_dir / "POSCAR", "POSCAR")

    contcar_ok = download_file(sftp, f"{remote_dir}/CONTCAR", local_dir / "CONTCAR", "CONTCAR")

    # 查找最新续算目录（con / con2 / con3 ...）

    work_dir = remote_dir

    try:

        stdin, stdout, stderr = client.exec_command(

            f"ls -d {remote_dir}/con*/ 2>/dev/null | sort -t'n' -k2 -n"

        )

        con_dirs = stdout.read().decode().strip().split()

        if con_dirs:

            # 排序取最后一个（最高编号）

            latest_con = con_dirs[-1].rstrip("/")

            work_dir = latest_con

            con_name = latest_con.rstrip("/").split("/")[-1]

            print(f"\n 发现续算目录: {con_name}（共 {len(con_dirs)} 个续算），检查最新结果")

    except Exception:

        pass

    # 检查 OUTCAR

    print(f"\n 检查 OUTCAR 收敛状态:")

    conv_status = ""

    energy = ""

    job_finished = False

    task_type = ""

    try:

        sftp.stat(f"{work_dir}/OUTCAR")

        attr = sftp.stat(f"{work_dir}/OUTCAR")

        print(f"    {work_dir}/OUTCAR  ({attr.st_size / 1024:.1f} KB)")

        conv_status, energy, job_finished, task_type = check_outcar(client, work_dir)

    except FileNotFoundError:

        print(f"   [!] OUTCAR 不存在")

        conv_status = "无OUTCAR"

    # 自动状态转换：Pending → Run（发现OUTCAR）/ 保持Pending（无文件）

    if subtask["status"] == "Pending":

        if conv_status != "无OUTCAR":

            subtask["status"] = "Run"

            print(f"\n[状态] Pending -> [Run] (检测到OUTCAR)")

        else:

            print(f"\n[状态] 仍为 Pending (尚无输出文件)")

    # ...

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

    if conv_status == "已收敛" or conv_status == "已完成":

        if job_finished and subtask["status"] not in ("Completed", "Pending"):

            old = subtask["status"]

            subtask["status"] = "Completed"

            print(f"\n 状态自动更新: {old} -> [OK] Completed")

    elif conv_status == "未收敛" and job_finished:

        if subtask["status"] not in ("Failed", "Pending"):

            old = subtask["status"]

            subtask["status"] = "Failed"

            print(f"\n 作业已结束但未收敛: {old} -> [X] Failed")

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

        # 清理能量值为纯数值

        clean_energy = energy.strip()

        if energy and "TOTEN" in energy:

            try:

                num = energy.split("=")[-1].strip().replace(" eV", "").strip()

                clean_energy = f"{float(num):.8f}"

            except:

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

    }



def main():
    parser = argparse.ArgumentParser(description="VASP \u8ba1\u7b97\u7ed3\u679c\u68c0\u67e5")
    parser.add_argument("project", nargs="?", default=None, help="\u9879\u76ee\u540d\u79f0")
    parser.add_argument("subtask", nargs="?", default=None, help="\u5b50\u4efb\u52a1\u540d\u79f0")
    parser.add_argument("--host", default=HPC_HOST)
    parser.add_argument("--port", type=int, default=HPC_PORT)
    parser.add_argument("--key", default=str(Path.home() / ".ssh" / "id_rsa"))
    parser.add_argument("--scan", action="store_true", help="\u5148\u626b\u63cf\u518d\u68c0\u67e5\uff08\u81ea\u52a8\u53d1\u73b0\u65b0\u5b50\u76ee\u5f55\uff09")
    parser.add_argument("--timeout", type=int, default=15)
    args = parser.parse_args()

    # \u626b\u63cf\u6a21\u5f0f
    if args.scan:
        print("=" * 60)
        print("  \u626b\u63cf\u6a21\u5f0f\uff1a\u5148\u81ea\u52a8\u53d1\u73b0\u5b50\u76ee\u5f55\uff0c\u518d\u68c0\u67e5")
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
        print(" \u6ca1\u6709\u7b26\u5408\u6761\u4ef6\u7684\u5f85\u68c0\u67e5\u9879")
        print("   \u8bf7\u5148\u7528 project_manager.py \u6dfb\u52a0\u5b50\u4efb\u52a1\u5e76\u8bbe\u4e3a Run \u72b6\u6001")
        sys.exit(0)

    print(f" \u8ba1\u5212\u68c0\u67e5 {len(targets)} \u9879")
    for proj, sub in targets:
        print(f"   - {proj['name']} / {sub['name']}  ({proj['path']}/{sub['dir']})")

    username, hostname = parse_host(args.host)
    key_path = os.path.expanduser(args.key)
    client = create_ssh_client(hostname, args.port, username, key_path, None, args.timeout)
    if client is None:
        sys.exit(1)
    print(f"[OK] \u5df2\u8fde\u63a5\u5230 {username}@{hostname}\n")

    results = []
    try:
        for proj, sub in targets:
            result = check_subtask(client, proj, sub)
            results.append(result)
    finally:
        client.close()
        print("\n\u8fde\u63a5\u5df2\u65ad\u5f00")

    save_projects(projects)
    if results:
        write_summary(results)
        print(f"\n \u9879\u76ee\u6587\u4ef6\u5df2\u66f4\u65b0\uff08\u81ea\u52a8\u5c06\u5df2\u6536\u655b\u5b50\u4efb\u52a1\u6807\u8bb0\u4e3a Completed\uff09")



if __name__ == "__main__":

    main()

