#!/usr/bin/env python3
"""
LSF 作业监控 — SSH 运行 bjobs -l, blimits, bqueues, bhosts
"""
import argparse
import sys
from config import SSH_KEY_DEFAULT
from pathlib import Path
from ssh_manager import SSHManager
from project_store import load_projects

SKILL_DIR = Path(__file__).resolve().parent.parent
PROJECTS_FILE = SKILL_DIR / "vaspcheck_projects.json"
HPC_HOST = "mdye@hpc.xmu.edu.cn"
HPC_PORT = 22

# ── 常用队列配置 ──
QUEUES = {
    "ocean6226R_1day": {"nodes": "hd030-hd048", "suspend_risk": "high",  "paid": False, "desc": "Ocean 队列, 易挂起"},
    "ocean_530_1day":  {"nodes": "hd001-hd029", "suspend_risk": "high",  "paid": False, "desc": "Ocean 队列, 易挂起"},
    "normal_1day_new": {"nodes": "s001-s018",   "suspend_risk": "low",   "paid": False, "desc": "Normal 队列, 稳定"},
    "normal_2week":    {"nodes": "b001-b014",   "suspend_risk": "low",   "paid": False, "desc": "Normal 队列, 长时"},
    "charge":          {"nodes": "s019-s030",   "suspend_risk": "none",  "paid": True,  "desc": "付费队列"},
}

NODE_GROUPS = [
    ("ocean6226R_1day", 30, 48, "hd"),
    ("ocean_530_1day",   1, 29, "hd"),
    ("normal_1day_new",  1, 18, "s"),
    ("charge",          19, 30, "s"),
    ("normal_2week",     1, 14, "b"),
]


def match_project(cwd, projects):
    for proj in projects:
        proj_path = proj["path"]
        if cwd.startswith(proj_path):
            rel = cwd[len(proj_path):].strip("/")
            for sub in proj.get("subs", []):
                if sub["dir"] in rel or rel == sub["dir"]:
                    return proj["name"], sub["name"], sub["dir"]
            if rel:
                return proj["name"], rel, ""
            return proj["name"], "(根目录)", ""
    return "—", "—", ""


def parse_bjobs_o(text):
    """解析 bjobs -o 结构化输出 (每行一个作业, 空格分隔)"""
    jobs = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        j = {
            "id": parts[0],
            "status": parts[1],
            "queue": parts[2],
            "user": parts[3],
            "cores": int(parts[4]) if parts[4].isdigit() else 0,
            "exec_cwd": parts[5] if len(parts) > 5 else "",
            "name": parts[6] if len(parts) > 6 else "",
        }
        # exec_cwd may contain spaces; join remaining parts
        if len(parts) > 7:
            j["exec_cwd"] = " ".join(parts[5:-1] if len(parts) > 7 else parts[5:])
        jobs.append(j)
    return jobs

def parse_bjobs_l(text):
    """fallback: 解析 bjobs -l (保留作为兼容)"""
def status_icon(status):
    icons = {
        "RUN":   "[Run] 运行中", "PEND":  "[P] 排队中", "SSUSP": "[S] 挂起",
        "USUSP": "[U] USUSP", "DONE":  "[D] 已完成", "EXIT":  "[X] 失败",
        "UNKWN": "[?] 未知", "PSUSP": "[P] PSUSP", "WAIT":  "[W] 等待中",
    }
    return icons.get(status, status)


def print_table(jobs_data, projects, client=None):
    header = f"{'JobID':>7}  {'状态':<8}  {'核数':>4}  {'队列':<18}  {'归属项目':<16}  {'子任务':<18}  {'目录路径'}"
    sep = "-" * 120
    print(sep)
    print("  LSF 作业监控 (bjobs)")
    print(sep)
    print(header)
    print(sep)
    for j in jobs_data:
        jid = j.get("id", "?")
        status = j.get("status", "?")
        cores = j.get("cores", "?")
        queue = j.get("queue", "?")
        cwd = j.get("exec_cwd") or j.get("cwd", "")
        proj, subtask, _ = match_project(cwd, projects, client)
        icon = status_icon(status)
        display_cwd = cwd
        if len(cwd) > 45:
            display_cwd = "..." + cwd[-42:]
        print(f"  {jid:<7}  {icon:<8}  {cores:>4}  {queue:<18}  {proj:<16}  {subtask:<18}  {display_cwd}")
    print(sep)
    print(f"  共 {len(jobs_data)} 个作业")


def cores_per_node(queue_name):
    table = {"ocean6226R_1day": 24, "ocean_530_1day": 24, "normal_1day_new": 24, "normal_2week": 28, "charge": 24}
    return table.get(queue_name, 24)


def recommend_queue(cores=48, urgent=False, special_neb=False, neb_images=None):
    candidates = []
    for qname, qinfo in QUEUES.items():
        if qname == "charge" and not urgent:
            continue
        per_node = cores_per_node(qname)
        n_nodes = (cores + per_node - 1) // per_node
        dist = [per_node] * (n_nodes - 1) + [cores - per_node * (n_nodes - 1)]
        if n_nodes == 1:
            comm = "无"
        elif n_nodes == 2:
            comm = "低 (2节点)" if abs(dist[0] - dist[1]) <= 4 else f"中 (核数不均 {dist[0]}+{dist[1]})"
        else:
            comm = f"高 ({n_nodes}节点)"
        neb_ok = True
        if special_neb and neb_images and cores % neb_images != 0:
            neb_ok = False
        candidates.append({
            "name": qname, "nodes": n_nodes, "dist": dist, "comm": comm,
            "suspend_risk": qinfo["suspend_risk"], "paid": qinfo["paid"],
            "neb_ok": neb_ok, "desc": qinfo["desc"],
        })
    def sort_key(c):
        risk = {"none": 0, "low": 1, "high": 2}
        return (1 if c["paid"] else 0, risk.get(c["suspend_risk"], 2), len(c["dist"]))
    candidates.sort(key=sort_key)
    if special_neb:
        candidates = [c for c in candidates if c["neb_ok"]]
    return candidates


def print_queue_status(bq_out):
    target = list(QUEUES.keys())
    print()
    print("=" * 70)
    print("  队列状态 (bqueues)")
    print("=" * 70)
    print(f"  {'队列':<18} {'状态':<16} {'总作业':>6} {'PEND':>6} {'RUN':>6} {'SUSP':>5}")
    print(f"  {'-'*60}")
    for line in bq_out.strip().split("\n"):
        parts = line.split()
        if not parts or parts[0] not in target:
            continue
        qname = parts[0]
        status = parts[2] if len(parts) > 2 else "?"
        node_range = QUEUES[qname]["nodes"]
        njobs = parts[5] if len(parts) > 5 else "?"
        pend = parts[6] if len(parts) > 6 else "?"
        run = parts[7] if len(parts) > 7 else "?"
        susp = parts[8] if len(parts) > 8 else "0"
        print(f"  {qname:<18} {status:<16} {njobs:>6} {pend:>6} {run:>6} {susp:>5}")
        print(f"  {'':<18}  节点: {node_range}")


def print_node_status(bh_out):
    print()
    print("=" * 70)
    print("  节点状态 (bhosts)")
    print("=" * 70)
    node_info = {}
    for line in bh_out.strip().split("\n"):
        parts = line.split()
        if len(parts) >= 7 and parts[0][:2].isalnum():
            node_info[parts[0]] = {"status": parts[1], "max": parts[3], "nrun": parts[5]}
    for qname, start, end, prefix in NODE_GROUPS:
        total = ok = busy = down = max_slots = used_slots = 0
        for i in range(start, end + 1):
            nodename = f"{prefix}{i:02d}" if prefix != "b" else f"{prefix}{i:03d}"
            if nodename in node_info:
                info = node_info[nodename]
                total += 1
                if info["status"] == "ok": ok += 1
                elif info["status"] in ("busy", "unavail"): busy += 1
                else: down += 1
                try:
                    max_slots += int(info["max"])
                    used_slots += int(info["nrun"])
                except: pass
            else:
                down += 1
        node_range = QUEUES.get(qname, {}).get("nodes", "?")
        if total > 0 and max_slots > 0:
            free = max_slots - used_slots
            free_pct = free / max_slots * 100
            print(f"  {qname:<18}  节点: {node_range}")
            print(f"  {'':<18}  在线 {total} | ok {ok} | 忙 {busy} | 离线 {down}")
            print(f"  {'':<18}  总核 {max_slots} | 已用 {used_slots} | 空闲 {free} ({free_pct:.0f}%)")


def main():
    parser = argparse.ArgumentParser(description="LSF 作业监控")
    parser.add_argument("--host", default=HPC_HOST)
    parser.add_argument("--port", type=int, default=HPC_PORT)
    parser.add_argument("--key", default=str(SSH_KEY_DEFAULT))
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--no-queue", action="store_true", help="跳过队列/节点/推荐")
    args = parser.parse_args()

    projects = load_projects()
    print(f"[数据库] {len(projects)} 个项目已加载")

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from ssh_connect import parse_host

    mgr = SSHManager()
    username, hostname, client = mgr.get_parsed(args.host, args.port, args.key, timeout=args.timeout)
    print(f"[连接] {username}@{hostname}")

    try:
        # ── bjobs -o ──
        stdin, stdout, stderr = client.exec_command('bjobs -noheader -o "jobid stat queue user slots exec_cwd job_name submit_time" 2>&1')
        raw = stdout.read().decode("utf-8", errors="replace")
        jobs = parse_bjobs_o(raw)
        if not jobs:
            print("\n(未找到运行中的作业)")
        else:
            print()
            print_table(jobs, projects, client)

        # ── blimits / busers ──
        print()
        print("=" * 60)
        print("  核数使用统计")
        print("=" * 60)
        try:
            stdin, stdout, _ = client.exec_command("blimits 2>/dev/null | grep -w mdye")
            bline = stdout.read().decode().strip()
            if bline:
                for p in bline.split():
                    if "/" in p:
                        print(f"  blimits normal_1day:  核数 {p} (mdye)")
                        break
            stdin, stdout, _ = client.exec_command("busers mdye 2>/dev/null | tail -1")
            buline = stdout.read().decode().strip()
            if buline:
                parts = buline.split()
                if len(parts) >= 7:
                    print(f"  busers mdye:         总作业 {parts[3]}, PEND {parts[4]}, RUN {parts[5]}, SSUSP {parts[6]}")
        except Exception as e:
            print(f"  [!] 获取核数失败: {e}")

        if args.no_queue:
            return

        # ── bqueues ──
        try:
            stdin, stdout, _ = client.exec_command("bqueues -u mdye 2>/dev/null")
            print_queue_status(stdout.read().decode().strip())
        except Exception as e:
            print(f"  [!] 获取队列状态失败: {e}")

        # ── bhosts ──
        try:
            stdin, stdout, _ = client.exec_command("bhosts 2>/dev/null")
            print_node_status(stdout.read().decode().strip())
        except Exception as e:
            print(f"  [!] 获取节点状态失败: {e}")

        # ── 队列推荐 ──
        print()
        print("=" * 70)
        print("  队列推荐")
        print("=" * 70)
        try:
            urgent = input("  是否紧急任务? (y/N): ").strip().lower() == "y"
            cores_str = input("  所需核数? (默认48): ").strip()
            cores = int(cores_str) if cores_str.isdigit() else 48
            neb = input("  是否为 NEB 任务? (y/N): ").strip().lower() == "y"
            neb_imgs = None
            if neb:
                img_str = input("  结构数/镜像数?: ").strip()
                neb_imgs = int(img_str) if img_str.isdigit() else None
            recs = recommend_queue(cores=cores, urgent=urgent, special_neb=neb, neb_images=neb_imgs)
            print(f"\n  推荐排序（越靠前越优）:")
            print(f"  {'队列':<18} {'节点':>4} {'分配':<14} {'损耗':<20} {'挂起风险':<8} {'付费':<5}")
            print(f"  {'-'*70}")
            for r in recs:
                dist_str = "+".join(str(x) for x in r["dist"])
                print(f"  {r['name']:<18} {r['nodes']:>4}  {dist_str:<14} {r['comm']:<20} {r['suspend_risk']:<8} {'是' if r['paid'] else '否'}")
                print(f"  {'':<18}  {r['desc']}")
            if not recs:
                print("  (无符合 NEB 整除条件的队列)")
        except EOFError:
            print("  (跳过推荐)")

        # ── 项目映射 ──
        print(f"\n{'─'*60}")
        print("  项目路径映射:")
        for p in projects:
            print(f"    {p['name']:<15}  →  {p['path']}")

    finally:
        mgr.close_all()
        print("\n连接已断开")


if __name__ == "__main__":
    main()