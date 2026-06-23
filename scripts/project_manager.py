"""

项目管理 — 管理 VASP 项目及子任务列表



每个项目包含多个子任务（结构优化 / 电子结构 / NEB），各有独立状态。



用法:

  # 项目管理

  list                             列出所有项目

  show                             查看详细表格

  add <name> <path>                添加项目

  remove <name>                    删除项目



  # 子任务管理

  sub add <project> <name> <dir>          添加子任务

  sub remove <project> <name>             删除子任务

  sub status <project> <name> <状态>       修改状态 (Run/Stop/Completed)



示例:

  python scripts/project_manager.py add test /data/gpfs03/mdye/projects/test

  python scripts/project_manager.py sub add test 结构优化 relax

  python scripts/project_manager.py sub status test 结构优化 Run

"""

import argparse

import json

import os

import sys

from pathlib import Path



SKILL_DIR = Path(__file__).resolve().parent.parent



# ── 自动分类规则 ──

# 目录前缀 → 任务类型标签

CLASSIFY_RULES = [

    ("opt/",     "结构优化"),

    ("abs/",     "吸附"),

    ("s8/",      "S8还原"),

    ("barrier/", "分解能垒"),

    ("dos/",     "DOS/PDOS"),

    ("bader/",   "差分+bader"),

    ("frac/","自由能矫正"),

    ("neb/",     "NEB"),

    ("static/",  "电子结构"),

    ("scf/",     "电子结构"),

    ("bands/",   "能带"),

    ("md/",      "分子动力学"),

]

IGNORE_DIRS = {"old", "backup", "tmp", "test", ".trash"}



DEFAULT_FILE = SKILL_DIR / "vaspcheck_projects.json"





def load_projects():

    if not DEFAULT_FILE.exists():

        return []

    with open(DEFAULT_FILE, "r", encoding="utf-8") as f:

        return json.load(f)





def save_projects(projects):

    with open(DEFAULT_FILE, "w", encoding="utf-8") as f:

        json.dump(projects, f, ensure_ascii=False, indent=2)

    print(f"[OK] 已写入: {DEFAULT_FILE}")





def get_project(projects, name):

    for p in projects:

        if p["name"] == name:

            return p

    return None





# ── 项目管理 ──



def cmd_list(args):

    projects = load_projects()

    if not projects:

        print(" 项目列表为空")

        return

    print(f"{'项目':<12} {'子任务数':<8} {'路径'}")

    print("-" * 70)

    for p in projects:

        subs = p.get("subs", [])

        run_count = sum(1 for s in subs if s["status"] == "Run")

        tag = f" {run_count}个运行中" if run_count else ""

        print(f"{p['name']:<12} {len(subs):<8}{tag} {p['path']}")





def cmd_show(args):

    projects = load_projects()

    if not projects:

        print(" 项目列表为空")

        return



    for p in projects:

        print(f"\n[项目] {p['name']}  {p['path']}")

        subs = p.get("subs", [])

        if not subs:

            print("   (无子任务)")

            continue

        print(f"   {'子任务':<12} {'目录':<20} {'状态'}")

        print(f"   {'-'*50}")

        for s in subs:

            icons = {"Run": "[Run]", "Stop": "[Stop]", "Completed": "[Done]"}

            icon = icons.get(s["status"], s["status"])

            print(f"   {s['name']:<12} {s['dir']:<20} {icon}")





def cmd_add(args):

    projects = load_projects()

    if get_project(projects, args.name):

        print(f"[X] 项目 '{args.name}' 已存在")

        return

    projects.append({

        "name": args.name,

        "path": args.path,

        "subs": [],

    })

    save_projects(projects)

    print(f" 已添加项目: {args.name}")

    print("   请用 'sub add' 添加子任务")





def cmd_remove(args):

    projects = load_projects()

    new_projects = [p for p in projects if p["name"] != args.name]

    if len(new_projects) == len(projects):

        print(f"[X] 未找到项目: {args.name}")

        return

    save_projects(new_projects)

    print(f" 已删除项目: {args.name}")





# ── 子任务管理 ──



def cmd_sub_add(args):

    projects = load_projects()

    proj = get_project(projects, args.project)

    if not proj:

        print(f"[X] 未找到项目: {args.project}")

        return

    subs = proj.get("subs", [])

    if any(s["name"] == args.name for s in subs):

        print(f"[X] 子任务 '{args.name}' 已存在")

        return

    subs.append({

        "name": args.name,

        "dir": args.dir,

        "status": "Stop",

    })

    proj["subs"] = subs

    save_projects(projects)

    print(f" 已添加子任务: {args.project} -> {args.name} ({args.dir})")





def cmd_sub_remove(args):

    projects = load_projects()

    proj = get_project(projects, args.project)

    if not proj:

        print(f"[X] 未找到项目: {args.project}")

        return

    subs = [s for s in proj.get("subs", []) if s["name"] != args.name]

    if len(subs) == len(proj.get("subs", [])):

        print(f"[X] 未找到子任务: {args.name}")

        return

    proj["subs"] = subs

    save_projects(projects)

    print(f" 已删除子任务: {args.project} -> {args.name}")





def cmd_sub_status(args):

    projects = load_projects()

    proj = get_project(projects, args.project)

    if not proj:

        print(f"[X] 未找到项目: {args.project}")

        return

    for s in proj.get("subs", []):

        if s["name"] == args.name:

            old = s["status"]

            s["status"] = args.status

            save_projects(projects)

            icons = {"Run": "[Run]", "Stop": "[Stop]", "Completed": "[Done]"}

            print(f"[状态] {args.project} / {args.name}: {icons.get(old, old)} -> {icons.get(args.status, args.status)}")

            return

    print(f"[X] 未找到子任务: {args.name}")





def cmd_sub_list(args):

    projects = load_projects()

    proj = get_project(projects, args.project)

    if not proj:

        print(f"[X] 未找到项目: {args.project}")

        return

    subs = proj.get("subs", [])

    if not subs:

        print("   (无子任务)")

        return

    print(f"{'子任务':<12} {'目录':<20} {'状态'}")

    print("-" * 50)

    for s in subs:

        icons = {"Run": "[Run]", "Stop": "[Stop]", "Completed": "[Done]"}

        print(f"{s['name']:<12} {s['dir']:<20} {icons.get(s['status'], s['status'])}")





# ── 扫描与自动分类 ──



def classify_dir(rel_path):

    """根据相对路径自动分类，返回 (任务类型名, 状态)"""

    for prefix, label in CLASSIFY_RULES:

        if rel_path.startswith(prefix):

            tail = rel_path[len(prefix):].rstrip("/")

            # 跳过忽略目录

            if tail in IGNORE_DIRS or tail.split("/")[0] in IGNORE_DIRS:

                return None, None

            # 生成有意义的名称

            name = f"{label}-{tail}" if tail else label

            return name, "Pending"

    # 不匹配规则 → 通用类型

    top = rel_path.split("/")[0]

    if top in IGNORE_DIRS or top.startswith("."):

        return None, None

    return f"通用-{rel_path.replace('/', '-')}", "Pending"





def cmd_scan(args):

    """SSH 扫描项目目录，自动发现并注册新子任务"""

    try:

        import paramiko

    except ImportError:

        print("[X] 需要 paramiko，运行: pip install paramiko")

        return



    projects = load_projects()

    proj = get_project(projects, args.project)

    if not proj:

        print(f"[X] 未找到项目: {args.project}")

        return



    base_path = proj["path"]

    existing_dirs = {s["dir"] for s in proj.get("subs", [])}



    print(f"[扫描] {proj['name']}  ({base_path})")

    print(f"[扫描] SSH {args.host} ...")



    # SSH 连接

    sys.path.insert(0, str(Path(__file__).resolve().parent))

    from ssh_connect import parse_host, create_ssh_client



    username, hostname = parse_host(args.host)

    key_path = os.path.expanduser(args.key)

    client = create_ssh_client(hostname, args.port, username,

                                key_path, None, args.timeout)

    if client is None:

        return



    try:

        # 列出所有二级子目录 (maxdepth 2: 分类目录/具体任务)

        cmd = f"find {base_path} -maxdepth 2 -type d | sort"

        stdin, stdout, stderr = client.exec_command(cmd)

        remote_dirs = stdout.read().decode().strip().split()

        err = stderr.read().decode().strip()



        if err:

            print(f"  [!] 扫描错误: {err}")



        new_subs = []

        for d in remote_dirs:

            rel = d.replace(base_path, "").strip("/")

            if not rel or "/" not in rel:

                # 只处理二级目录 (如 opt/model1, abs/2_1)

                continue



            if rel in existing_dirs:

                continue



            name, status = classify_dir(rel)

            if name is None:

                continue



            # 检查是否有 OUTCAR → 自动设为 Run

            stdin2, stdout2, _ = client.exec_command(f"test -f {d}/OUTCAR && echo Y || echo N")

            has_outcar = stdout2.read().decode().strip()

            if has_outcar == "Y":

                status = "Run"



            new_subs.append({"name": name, "dir": rel, "status": status})

            print(f"  [+] {rel:25s} → {name:20s}  [{status}]")



        if not new_subs:

            print("  (没有发现新子目录)")

            return



        # 加入项目数据库

        proj.setdefault("subs", []).extend(new_subs)

        save_projects(projects)

        print(f"  [OK] 已添加 {len(new_subs)} 个子任务")

        print("  运行 vasp_check.py 开始检查 Run 状态的任务")



    finally:

        client.close()

        print("  连接已断开")





# ── 入口 ──



def main():

    parser = argparse.ArgumentParser(description="VASP 项目管理")

    sub = parser.add_subparsers(dest="command", required=True)



    # list / show / scan

    sub.add_parser("list", help="列出所有项目")

    sub.add_parser("show", help="查看详细表格")



    p_scan = sub.add_parser("scan", help="SSH 扫描项目目录，自动分类并注册子任务")

    p_scan.add_argument("project", help="项目名称")

    p_scan.add_argument("--host", default="mdye@hpc.xmu.edu.cn", help="SSH 用户名@地址")

    p_scan.add_argument("--port", type=int, default=22)

    p_scan.add_argument("--key", default=str(Path.home() / ".ssh" / "id_rsa"))

    p_scan.add_argument("--timeout", type=int, default=15)



    # add / remove

    p_add = sub.add_parser("add", help="添加项目")

    p_add.add_argument("name")

    p_add.add_argument("path")



    p_rm = sub.add_parser("remove", help="删除项目")

    p_rm.add_argument("name")



    # sub commands

    p_sub = sub.add_parser("sub", help="管理子任务")

    p_sub_sub = p_sub.add_subparsers(dest="sub_command", required=True)



    p_sa = p_sub_sub.add_parser("add", help="添加子任务")

    p_sa.add_argument("project")

    p_sa.add_argument("name", help="子任务名称，如 结构优化")

    p_sa.add_argument("dir", help="服务器上的子目录名，如 relax")



    p_sr = p_sub_sub.add_parser("remove", help="删除子任务")

    p_sr.add_argument("project")

    p_sr.add_argument("name")



    p_ss = p_sub_sub.add_parser("status", help="修改子任务状态")

    p_ss.add_argument("project")

    p_ss.add_argument("name")

    p_ss.add_argument("status", choices=["Pending", "Run", "Stop", "Completed", "Failed"])



    p_sl = p_sub_sub.add_parser("list", help="列出子任务")

    p_sl.add_argument("project")



    args = parser.parse_args()



    if args.command == "list":

        cmd_list(args)

    elif args.command == "show":

        cmd_show(args)

    elif args.command == "scan":

        cmd_scan(args)

    elif args.command == "add":

        cmd_add(args)

    elif args.command == "remove":

        cmd_remove(args)

    elif args.command == "sub":

        handlers = {

            "add": cmd_sub_add,

            "remove": cmd_sub_remove,

            "status": cmd_sub_status,

            "list": cmd_sub_list,

        }

        handlers[args.sub_command](args)





if __name__ == "__main__":

    main()

