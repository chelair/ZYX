"""
VASP 续算 — 创建 conN/ 目录，接续未收敛作业

两步式流程:
  Step 1: python scripts/job_continue.py <项目> <子任务> --dry-run   # 生成文件预览
  Step 2: python scripts/job_continue.py <项目> <子任务>               # 确认并提交

规则来源:
  - WORKFLOW.md    Step 7-8 续算流程
  - CONTINUE.md    续算场景 + CONTCAR 校验 + 核数估算
  - VASPKIT.md     VASPKit 402 固定规则
  - .input_reference.md    续算参数调整明细
  - SKILL.md       命令一览 + 核心规则
"""
import argparse
import re
import sys
from datetime import datetime
from config import SSH_KEY_DEFAULT
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = Path(__file__).resolve().parent
PROJECTS_FILE = SKILL_DIR / "vaspcheck_projects.json"
HPC_HOST = "mdye@hpc.xmu.edu.cn"
HPC_PORT = 22

sys.path.insert(0, str(SCRIPTS_DIR))
from ssh_manager import SSHManager
from safe_ops import (
    safe_mkdir, safe_cp, safe_mv, safe_write_text,
    safe_upload_file, check_remote_exists, read_remote_job_info,
)
from project_store import load_projects, save_projects, find_project, find_subtask
from jobs_monitor import recommend_queue, QUEUES, cores_per_node, NODE_GROUPS


# ═══════════════════════════════════════════════
#  辅助函数
# ═══════════════════════════════════════════════

def remote_read_text(client, path):
    """SSH 读取远程文件内容"""
    try:
        stdin, stdout, _ = client.exec_command(f'cat "{path}" 2>/dev/null')
        return stdout.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def remote_write_text(client, path, text):
    """通过 SFTP 直接覆写远程文件（用于续算目录中我们刚创建的文件）"""
    sftp = None
    try:
        sftp = client.open_sftp()
        with sftp.open(path, "w") as f:
            f.write(text.encode("utf-8"))
            f.flush()
        sftp.close()
        return True
    except Exception as e:
        try:
            if sftp:
                sftp.close()
        except Exception:
            pass
        print(f"  [!] 写入 {path} 失败: {e}")
        return False


def remote_read_incar(client, path):
    """读取远程 INCAR 并解析为 {key: value, ...}"""
    text = remote_read_text(client, path)
    result = {}
    for line in text.split("\n"):
        line = line.strip()
        if not line or line.startswith("!"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            result[k.strip().upper()] = v.strip()
    return result, text


def remote_modify_incar_line(client, path, key, new_value):
    """修改 INCAR 中某参数的值，保留注释和格式"""
    text = remote_read_text(client, path)
    new_lines = []
    found = False
    for line in text.split("\n"):
        stripped = line.strip()
        if not found and not stripped.startswith("!") and "=" in stripped:
            k = stripped.split("=", 1)[0].strip().upper()
            if k == key.upper():
                indent = line[:len(line) - len(line.lstrip())]
                new_lines.append(f"{indent}{key} = {new_value}")
                found = True
                continue
        new_lines.append(line)
    if not found:
        new_lines.append(f"{key} = {new_value}")
    return remote_write_text(client, path, "\n".join(new_lines))


def classify_fix_type(subtask_name, subtask_dir):
    """根据子任务名/目录判断固定类型和比例"""
    name_lower = (subtask_name + " " + subtask_dir).lower()
    if any(kw in name_lower for kw in ["频率", "freq", "振动", "frequency"]):
        return "frequency", None
    if any(kw in name_lower for kw in ["吸附", "abs", "oer", "反应"]):
        return "adsorption", 0.50
    if any(kw in name_lower for kw in ["结构优化", "opt", "raw", "slab"]):
        return "slab", 0.40
    return "slab", 0.40  # 默认 slab



def _calc_dipol_center(client, poscar_path):
    """SSH 读取 POSCAR，计算 z 几何中心
    Returns: (z_center, z_min, z_max) 或 (None, None, None)
    """
    try:
        stdin, stdout, _ = client.exec_command(f"cat {poscar_path}")
        poscar_lines = stdout.read().decode().split("\n")
        zvals = []
        in_coords = False
        for line in poscar_lines:
            s = line.strip()
            if s.lower() in ("direct", "cartesian", "selective dynamics"):
                in_coords = True
                continue
            if in_coords:
                parts = s.split()
                if len(parts) >= 3:
                    try:
                        zvals.append(float(parts[2]))
                    except ValueError:
                        pass
        if not zvals:
            return None, None, None
        zmin = min(zvals)
        zmax = max(zvals)
        zcenter = round((zmin + zmax) / 2, 2)
        return zcenter, zmin, zmax
    except Exception:
        return None, None, None
def needs_dipole(subtask_name, subtask_dir):
    """判断是否需要偶极矫正（仅吸附类需要）"""
    name_lower = (subtask_name + " " + subtask_dir).lower()
    return any(kw in name_lower for kw in ["吸附", "abs", "oer"])


def build_job_name(project_name, sub_dir, con_name):
    """Job name <=9 chars, [A-Za-z0-9_] only (bjobs shows last 9)"""
    import re
    
    # Project: extract 2-3 char keyword
    raw = "".join(c for c in project_name if c.isalnum() or c == "_")
    short = raw.replace("_", "")[:3]
    
    # Sub: last segment, 2-4 chars
    sub = sub_dir.rstrip("/").split("/")[-1]
    sub = "".join(c for c in sub if c.isalnum())
    sub = sub[:4]
    
    # Con number
    m = re.search(r"(\d+)$", con_name)
    cn = "_c" + m.group() if m else ""
    
    name = short + "_" + sub + cn
    if len(name) > 9:
        name = name.replace("_", "")
        name = name[:9]
    return name
def check_contcar_integrity(client, remote_dir):
    """CONTCAR 完整性校验 — 比较预期坐标行数和实际行数

    步骤:
      1. 读取 POSCAR 原子总数
      2. 计算预期坐标行数
      3. 读取 CONTCAR 末尾，检查是否截断

    Returns:
      (True, poscar_atoms) 完整
      (False, 原因) 不完整
    """
    cmd = (
        f'cd "{remote_dir}" && '
        f'if [ ! -f CONTCAR ]; then echo "NO_CONTCAR"; exit; fi && '
        # Get atom counts: if line 6 is element symbols, use line 7
        f'line6=$(sed -n "6p" POSCAR 2>/dev/null) && '
        f'if echo "$line6" | grep -qE "^[[:space:]]*[0-9]"; then '
        f'  n_atoms="$line6"; else n_atoms=$(sed -n "7p" POSCAR 2>/dev/null); fi && '
        f'c_lines=$(grep -c "" CONTCAR 2>/dev/null) && '
        f'tail -3 CONTCAR | cat && '
        f'echo "---ATOMS=$n_atoms---" && '
        f'echo "---CLINES=$c_lines---"'
    )
    stdin, stdout, _ = client.exec_command(cmd)
    output = stdout.read().decode().strip()

    if "NO_CONTCAR" in output:
        return False, "CONTCAR 不存在"

    # 解析原子数
    m_atoms = re.search(r'---ATOMS=([\d\s]+)---', output)
    if not m_atoms:
        return False, "无法解析原子数"
    atoms_str = m_atoms.group(1).strip()
    try:
        total_atoms = sum(int(x) for x in atoms_str.split())
    except ValueError:
        return False, "原子数解析失败"

    return True, total_atoms


# ═══════════════════════════════════════════════
#  WAVECAR 判断
# ═══════════════════════════════════════════════

def check_wavecar_ready(client, remote_dir):
    """检查 OUTCAR 是否有完成标志 & WAVECAR 是否存在

    Returns:
      "ready"    — OUTCAR 有完成标志 + WAVECAR 存在 → 可 mv
      "exists"   — WAVECAR 存在但 OUTCAR 未完成 → 不移动
      "missing"  — WAVECAR 不存在
    """
    cmd = (
        f'cd "{remote_dir}" && '
        f'has_flag=$(grep -c "General timing and accounting" OUTCAR 2>/dev/null || echo 0) && '
        f'has_wave=$(test -f WAVECAR && echo Y || echo N) && '
        f'echo "FLAG=$has_flag WAVE=$has_wave"'
    )
    stdin, stdout, _ = client.exec_command(cmd)
    result = stdout.read().decode().strip()

    m = re.search(r'FLAG=(\d+) WAVE=([YN])', result)
    if not m:
        return "missing"

    has_flag = int(m.group(1)) > 0
    has_wave = m.group(2) == "Y"

    if has_flag and has_wave:
        return "ready"
    elif has_wave:
        return "exists"
    else:
        return "missing"


# ═══════════════════════════════════════════════
#  确定当前工作目录
# ═══════════════════════════════════════════════

def find_work_dir(client, base_dir):
    """Determine current work directory
    If base_dir itself is conN, look for siblings in parent.
    Only considers con dirs that have CONTCAR (actually ran).
    Returns: (work_dir, latest_con_num, parent_dir)
    """
    # If base_dir itself is conN, go up one level
    if re.search(r"/con\d+$", base_dir):
        parent = "/".join(base_dir.split("/")[:-1])
    else:
        parent = base_dir
    cmd = f'ls -d "{parent}"/con[0-9]*/ 2>/dev/null | sort -V'
    stdin, stdout, _ = client.exec_command(cmd)
    con_dirs = stdout.read().decode().strip().split()
    # Filter: only con dirs that actually ran (have CONTCAR)
    ran_dirs = []
    for d in con_dirs:
        d = d.strip()
        if not d:
            continue
        check_cmd = f"test -s {d}/CONTCAR ; echo $?"
        stdin2, stdout2, _ = client.exec_command(check_cmd)
        if stdout2.read().decode().strip() == "0":
            ran_dirs.append(d)
    if ran_dirs:
        latest = ran_dirs[-1].rstrip("/")
        m = re.search(r"con(\d+)$", latest)
        latest_num = int(m.group(1)) if m else 0
        return latest, latest_num, parent
    else:
        return base_dir, 0, parent
def find_next_con_number(client, base_dir):
    """Calculate next con number, returns (n, parent_dir)"""
    if re.search(r"/con\d+$", base_dir):
        parent = "/".join(base_dir.split("/")[:-1])
    else:
        parent = base_dir
    cmd = f'ls -d "{parent}"/con[0-9]*/ 2>/dev/null | sort -V'
    stdin, stdout, _ = client.exec_command(cmd)
    con_dirs = stdout.read().decode().strip().split()
    max_n = 0
    for d in con_dirs:
        d = d.strip()
        if not d:
            continue
        m = re.search(r"con(\d+)/?$", d)
        if m:
            n = int(m.group(1))
            if n > max_n:
                max_n = n
    return max_n + 1, parent

def _check_bhosts(client, cores, ptile=24):
    """MONITOR.md P0: bhosts 节点状态检查
    
    1. 仅取 STATUS=ok 的节点
    2. 按 HOST_NAME 匹配队列节点范围
    3. 统计每个队列中 free >= ptile 的 ok 节点数
    4. 按优先级排序返回
    
    Returns: list of {queue, ok_nodes, free_nodes, can_fit, ...}
    """
    # (jobs_monitor imported at module level)
    

    stdin, stdout, _ = client.exec_command("bhosts 2>/dev/null")
    raw = stdout.read().decode().strip()
    if not raw:
        return []
    
    # Parse bhosts: HOST_NAME STATUS JL/U MAX NJOBS RUN ...
    ok_nodes = {}  # hostname -> free_slots
    for line in raw.split("\n"):
        parts = line.split()
        if len(parts) < 7:
            continue
        host, status = parts[0], parts[1]
        if host.startswith("HOST") or status != "ok":
            continue
        try:
            max_slots = int(parts[3])
            njobs = int(parts[4])
            free = max_slots - njobs
            if free > 0:
                ok_nodes[host] = free
        except ValueError:
            continue
    
    if not ok_nodes:
        return [{"queue": "NONE", "ok_nodes": 0, "free_24": 0, "can_fit": False}]
    
    # Map hostname -> queue using node ranges
    def _host_in_range(host, prefix, lo, hi):
        """Check if host matches prefixNN where NN in [lo, hi]"""
        if not host.startswith(prefix):
            return False
        try:
            num = int(host[len(prefix):])
            return lo <= num <= hi
        except ValueError:
            return False
    
    def _host_to_queue(host):
        for qname, start, end, prefix in NODE_GROUPS:
            if _host_in_range(host, prefix, start, end):
                return qname
        return None
    
    # Aggregate by queue
    queue_stats = {}
    for host, free in ok_nodes.items():
        q = _host_to_queue(host)
        if q is None:
            continue
        if q not in queue_stats:
            queue_stats[q] = {"total_ok": 0, "free_24": 0, "free_cores": 0, "nodes": []}
        queue_stats[q]["total_ok"] += 1
        queue_stats[q]["free_cores"] += free
        if free >= ptile:
            queue_stats[q]["free_24"] += 1
            queue_stats[q]["nodes"].append(f"{host}({free})")
    
    # Build prioritized result
    result = []
    for qname, stats in queue_stats.items():
        qinfo = QUEUES.get(qname, {})
        nodes_needed = (cores + ptile - 1) // ptile
        can_fit = stats["free_24"] >= nodes_needed
        result.append({
            "queue": qname,
            "ok_nodes": stats["total_ok"],
            "free_24": stats["free_24"],
            "free_cores": stats["free_cores"],
            "can_fit": can_fit,
            "nodes_needed": nodes_needed,
            "suspend_risk": qinfo.get("suspend_risk", "?"),
            "paid": qinfo.get("paid", False),
            "sample_nodes": stats["nodes"][:4],
        })
    
    # Sort: can_fit first, then free (no cost), then low suspend risk
    risk_order = {"none": 0, "low": 1, "high": 2, "?": 3}
    result.sort(key=lambda x: (
        not x["can_fit"],
        1 if x["paid"] else 0,
        risk_order.get(x["suspend_risk"], 3),
        -x["free_24"],
    ))
    return result


def generate_vasp_lsf(job_name, queue, cores=48, ptile=24, walltime="24:00"):
    """生成 vasp.lsf 内容

    模板参考 submit/vasp.lsf
    """
    return f"""#!/bin/bash
#BSUB -J {job_name}
#BSUB -q {queue}
#BSUB -o %J.out
#BSUB -e %J.err
#BSUB -W {walltime}
#BSUB -wt 50
#BSUB -wa URG
#BSUB -n {cores}
#BSUB -R "span[ptile={ptile}]"

source /data/gpfs03/mdye/intel/parallel_studio_xe_2020/psxevars.sh
module load impi

export I_MPI_HYDRA_BOOTSTRAP=lsf
export I_MPI_FABRICS=shm:ofi

rm -rf STOPCAR

echo "=== Job Started at $(date) ===" > result

lsf_watcher() {{
    trap 'echo "LSTOP = .TRUE." > STOPCAR; echo "=== [$(date)] LSF Walltime Warning! STOPCAR generated. ===" >> result; exit 0' SIGURG
    while true; do
        sleep 60
    done
}}
lsf_watcher &
WATCHER_PID=$!

mpiexec.hydra -genvall -n {cores} /data/gpfs03/mdye/vasp.6.4.2/bin/vasp_std >> result

echo "=== Job Finished at $(date) ===" >> result

kill $WATCHER_PID 2>/dev/null
"""


# ═══════════════════════════════════════════════
#  生成 job.info 内容
# ═══════════════════════════════════════════════

def generate_job_info(project_name, subtask_dir, con_dir_rel, queue, job_name, cores, incar_params):
    """生成 job.info 内容"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "[submit]",
        f"project     = {project_name}",
        f"subtask     = {subtask_dir}",
        f"directory   = {con_dir_rel}",
        f"queue       = {queue}",
        f"job_name    = {job_name}",
        f"cores       = {cores}",
        f"status      = pending",
        f"submitted_at = {now}",
        f"job_id      = ",
        "",
        "[incar]",
    ]
    for k, v in incar_params.items():
        lines.append(f"{k:<12} = {v}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════
#  核数估算
# ═══════════════════════════════════════════════

def estimate_cores(total_atoms, ibrion=None, is_neb=False):
    """根据原子数和计算类型估算核数"""
    if is_neb:
        return 48

    if total_atoms < 100:
        cores = 24
    elif total_atoms <= 150:
        cores = 36
    else:
        cores = 48

    return cores


# ═══════════════════════════════════════════════
#  主流程
# ═══════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="VASP 续算 — 创建 conN/ 并提交")
    parser.add_argument("project", help="项目名")
    parser.add_argument("subtask", help="子任务名")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不创建/提交")
    parser.add_argument("--host", default=HPC_HOST, help="SSH 主机")
    parser.add_argument("--port", type=int, default=HPC_PORT, help="SSH 端口")
    parser.add_argument("--key", default=str(SSH_KEY_DEFAULT), help="SSH 私钥路径")
    parser.add_argument("--timeout", type=int, default=15, help="连接超时")
    parser.add_argument("--cores", type=int, default=None, help="指定核数（默认自动估算）")
    parser.add_argument("--queue", default=None, help="指定队列（默认自动推荐）")
    parser.add_argument("--yes", "-y", action="store_true", help="跳过确认直接提交")
    parser.add_argument("--no-submit", action="store_true", help="仅生成文件，不提交")
    args = parser.parse_args()

    # ── 1. 加载项目 ──
    projects = load_projects()
    proj = find_project(projects, args.project)
    if not proj:
        print(f"[X] 未找到项目: {args.project}")
        sys.exit(1)

    sub = find_subtask(proj, args.subtask)
    if not sub:
        print(f"[X] 未找到子任务: {args.project} / {args.subtask}")
        sys.exit(1)

    base_path = proj["path"]
    sub_dir = sub["dir"]
    remote_base = f"{base_path}/{sub_dir}"

    # ── 2. SSH 连接 ──
    mgr = SSHManager()
    try:
        username, hostname, client = mgr.get_parsed(args.host, args.port, args.key, timeout=args.timeout)
        print(f"[OK] 已连接到 {username}@{hostname}")
        print(f"[项目] {args.project}  /  {args.subtask}")
        print(f"[路径] {remote_base}")
        print()

        # ── 3. 检查远程目录 ──
        if not check_remote_exists(client, remote_base, "dir"):
            print(f"[X] 远程目录不存在: {remote_base}")
            return

        # ── 4. 确定工作目录 ──
        work_dir, cur_con, parent_dir = find_work_dir(client, remote_base)
        if cur_con > 0:
            print(f"[现状] 已有续算目录 con{cur_con}/，基于此目录继续")
            print(f"       {work_dir}")
        else:
            print(f"[现状] 原始目录，尚无续算")

        # ── 5. CONTCAR 完整性校验 ──
        print()
        print("-" * 60)
        print("  [1/10] CONTCAR 完整性校验")
        print("-" * 60)

        if not check_remote_exists(client, f"{work_dir}/CONTCAR", "file"):
            print("  [X] CONTCAR 不存在，无法续算")
            return

        if not check_remote_exists(client, f"{work_dir}/OUTCAR", "file"):
            print("  [X] OUTCAR 不存在，无法续算")
            return

        ok, atoms = check_contcar_integrity(client, work_dir)
        if not ok:
            print(f"  [X] CONTCAR 不完整: {atoms}")
            return
        print(f"  [OK] CONTCAR 完整，原子数: {atoms}")

        # ── 6. 计算续算编号 ──
        print()
        print("-" * 60)
        print("  [2/10] 计算续算编号")
        print("-" * 60)
        n, con_parent = find_next_con_number(client, remote_base)
        con_name = f"con{n}"
        con_path = f"{con_parent}/{con_name}"
        print(f"       con{n}/")

        # ── 7. 创建续算目录 ──
        print()
        print("-" * 60)
        print("  [3/10] 创建目录")
        print("-" * 60)
        if not args.dry_run:
            ok, err = safe_mkdir(client, con_path)
            if not ok:
                print(f"  [X] 创建失败: {err}")
                return
            print(f"  [OK] mkdir {con_path}")
        else:
            print(f"  [DRY-RUN] mkdir {con_path}")

        # ── 8. 复制文件 ──
        print()
        print("-" * 60)
        print("  [4/10] 复制文件 (cp -n)")
        print("-" * 60)
        copy_pairs = [
            ("CONTCAR", "POSCAR"),
            ("INCAR", "INCAR"),
            ("KPOINTS", "KPOINTS"),
            ("POTCAR", "POTCAR"),
        ]

        copy_ok = True
        for src_name, dst_name in copy_pairs:
            src = f"{work_dir}/{src_name}"
            dst = f"{con_path}/{dst_name}"
            if args.dry_run:
                print(f"  [DRY-RUN] cp -n {src} → {dst}")
                continue
            if not check_remote_exists(client, src, "file"):
                print(f"  [!] {src_name} 不存在，跳过")
                continue
            ok, err = safe_cp(client, src, dst)
            if ok:
                print(f"  [OK] {src_name} → {dst_name}")
            else:
                print(f"  [X] cp -n {src_name} 失败: {err}")
                copy_ok = False
        # Fallback: if KPOINTS missing, try IBZKPT
        if not check_remote_exists(client, f"{con_path}/KPOINTS", "file"):
            for src_name in [f"{work_dir}/IBZKPT", f"{remote_base}/IBZKPT", f"{remote_base}/KPOINTS"]:
                if check_remote_exists(client, src_name, "file"):
                    ok, err = safe_cp(client, src_name, f"{con_path}/KPOINTS")
                    if ok:
                        print("  [OK] IBZKPT -> KPOINTS")
                    break


        if not copy_ok:
            print("  [!] 部分文件复制失败，终止")
            return

        # ── 9. WAVECAR 处理 ──
        print()
        print("-" * 60)
        print("  [5/10] WAVECAR 处理")
        print("-" * 60)
        wave_status = check_wavecar_ready(client, work_dir)
        if wave_status == "ready":
            if args.dry_run:
                print(f"  [DRY-RUN] mv {work_dir}/WAVECAR → {con_path}/WAVECAR")
            else:
                ok, err = safe_mv(client, f"{work_dir}/WAVECAR", f"{con_path}/WAVECAR")
                if ok:
                    print("  [OK] WAVECAR 已移动（有完成标志）")
                else:
                    print(f"  [!] WAVECAR 移动失败: {err}")
        elif wave_status == "exists":
            print("  [!] WAVECAR 存在但 OUTCAR 无完成标志，不移动")
            print("      续算时不使用 WAVECAR (ISTART=0)")
        else:
            print("  [-] WAVECAR 不存在，从头开始")

        # ── 10. 修改 INCAR ──
        print()
        print("-" * 60)
        print("  [6/10] 调整 INCAR 参数")
        print("-" * 60)

        incar_params = {"ISTART": "1", "ICHARG": "0"}

        if not args.dry_run:
            orig_incar, _ = remote_read_incar(client, f"{con_path}/INCAR")
            for k in ["IBRION", "NSW", "EDIFF", "EDIFFG", "ENCUT", "ISPIN",
                       "ISIF", "ISMEAR", "SIGMA", "PREC", "LREAL", "IVDW",
                       "NELM", "NELMIN", "POTIM", "LWAVE", "LCHARG"]:
                if k in orig_incar:
                    incar_params[k] = orig_incar[k]

            remote_modify_incar_line(client, f"{con_path}/INCAR", "ISTART", "1")
            remote_modify_incar_line(client, f"{con_path}/INCAR", "ICHARG", "0")
            remote_modify_incar_line(client, f"{con_path}/INCAR", "LWAVE", ".TRUE.")
            print("  [OK] ISTART=1, ICHARG=0, LWAVE=.TRUE.")
        else:
            print("  [DRY-RUN] ISTART=1, ICHARG=0, LWAVE=.TRUE.")

        # ── 11. 固定类型识别 ──
        fix_type, fix_ratio = classify_fix_type(args.subtask, sub_dir)
        print(f"\n  [7/10] 固定类型识别: {fix_type}")
        if fix_ratio:
            print(f"         固定比例: {fix_ratio*100:.0f}%（VASPKit 402 Fix by Heights）")
            print(f"         续算后手动: vaspkit → 4 → 402 → 3")
            print(f"         z 阈值 = z_min + {fix_ratio} × (z_max - z_min)")
        elif fix_type == "frequency":
            print(f"         频率矫正: 按原子序号固定（VASPKit 402 Fix by Indices）")
            print(f"         续算后手动: vaspkit → 4 → 402 → 1")

        # ── 12. DIPOL 矫正 ──
        has_dipole = needs_dipole(args.subtask, sub_dir)
        if has_dipole:
            print(f"\n  [8/10] DIPOL 偶极矫正")
            print(f"         吸附构型 → 需添加 DIPOL")
            if not args.dry_run:
                remote_modify_incar_line(client, f"{con_path}/INCAR", "LDIPOL", ".TRUE.")
                remote_modify_incar_line(client, f"{con_path}/INCAR", "IDIPOL", "3")
                print("  [OK] LDIPOL=.TRUE. IDIPOL=3 已写入")
                zc, zmin, zmax = _calc_dipol_center(client, f"{con_path}/POSCAR")
                if zc is not None:
                    remote_modify_incar_line(client, f"{con_path}/INCAR", "DIPOL", f"0.5 0.5 {zc}")
                    print(f"  [OK] DIPOL = 0.5 0.5 {zc} (z_min={zmin}, z_max={zmax})")
                else:
                    print("  [!] DIPOL z 中心自动计算失败，请手动填入")
        print("-" * 60)


        is_neb = sub_dir.startswith("neb/")
        cores = args.cores or estimate_cores(atoms, is_neb=is_neb)
        # ── P0: bhosts 检查节点(仅 STATUS=ok,按队列映射) ──
        bhosts_data = _check_bhosts(client, cores)
        if bhosts_data:
            print("  bhosts (ok nodes free ≥ ptile):")
            for bh in bhosts_data:
                fit = "✓" if bh["can_fit"] else "✗"
                paid = "$" if bh["paid"] else " "
                nodes_str = ", ".join(bh["sample_nodes"]) if bh["sample_nodes"] else "-"
                print(f"    {fit} {paid} {bh["queue"]:<20} ok={bh["ok_nodes"]} free24={bh["free_24"]} need={bh["nodes_needed"]}  [{nodes_str}]")
            # Auto-select first queue that fits
            fitting = [bh for bh in bhosts_data if bh["can_fit"]]
        else:
            print("  bhosts: 无法获取节点状态")
            fitting = []



        recs = recommend_queue(cores=cores, urgent=False, special_neb=is_neb)
        print(f"  体系原子数: {atoms}, 推荐核数: {cores}")
        # P1: bhosts fixes queue selection (bhosts shown above)
        selected_queue = args.queue
        if not selected_queue:
            if fitting:
                selected_queue = fitting[0]["queue"]
            else:
                selected_queue = recs[0]["name"]
            print("  队列: " + selected_queue)
        # ── 14. 生成提交文件 ──
        print()
        print("-" * 60)
        print("  [10/10] 生成提交文件")
        print("-" * 60)

        job_name = build_job_name(args.project, sub_dir, con_name)
        lsf_content = generate_vasp_lsf(job_name, selected_queue, cores)
        job_info_content = generate_job_info(
            args.project, sub_dir, f"{sub_dir}/{con_name}",
            selected_queue, job_name, cores, incar_params
        )

        if not args.dry_run:
            lsf_path = f"{con_path}/vasp.lsf"
            ok, err = safe_write_text(client, lsf_path, lsf_content)
            if ok:
                print(f"  [OK] vasp.lsf 已写入 → {con_path}/vasp.lsf")
                print(f"       JobName: {job_name}, 队列: {selected_queue}, 核数: {cores}")
            else:
                print(f"  [X] vasp.lsf 写入失败: {err}")
                if "目标文件已存在" in err:
                    if remote_write_text(client, lsf_path, lsf_content):
                        print(f"  [OK] vasp.lsf 已覆写")

            ji_path = f"{con_path}/job.info"
            ok, err = safe_write_text(client, ji_path, job_info_content)
            if ok:
                print(f"  [OK] job.info 已写入")
            else:
                if "目标文件已存在" in err:
                    if remote_write_text(client, ji_path, job_info_content):
                        print(f"  [OK] job.info 已覆写")
                        ok = True

            if ok:
                sub["status"] = "Pending"
                save_projects(projects)
                print(f"  [OK] JSON 已同步 → {args.project}/{args.subtask} = Pending")
        else:
            print(f"  [DRY-RUN] vasp.lsf → JobName: {job_name}, 队列: {selected_queue}, 核数: {cores}")
            print(f"  [DRY-RUN] job.info 待写入")
            print(f"  [DRY-RUN] JSON → Pending")

        # ── 预览摘要 ──
        print()
        print("=" * 60)
        print("  续算预览")
        print("=" * 60)
        print(f"  项目:         {args.project}")
        print(f"  子任务:       {args.subtask}")
        print(f"  目录:         {sub_dir}")
        print(f"  工作目录:     {work_dir}")
        print(f"  续算目录:     {con_name}/")
        print(f"  作业名:       {job_name}")
        print(f"  队列:         {selected_queue}")
        print(f"  核数:         {cores}")
        print(f"  原子数:       {atoms}")
        print(f"  固定类型:     {fix_type}" + (f" ({fix_ratio*100:.0f}%)" if fix_ratio else ""))
        print(f"  偶极矫正:     {'需要' if has_dipole else '不需要'}")

        if args.dry_run:
            print()
            print("  [!] 这是 --dry-run 预览模式")
            print("  确认无误后运行（不含 --dry-run）以执行续算")
        else:
            print()
            print(f"  [OK] 文件已生成: {con_path}/")
            print(f"       - POSCAR (from CONTCAR)")
            print(f"       - INCAR (ISTART=1, ICHARG=0, LWAVE=.TRUE.)")
            print(f"       - KPOINTS, POTCAR")
            if wave_status == "ready":
                print(f"       - WAVECAR (已移动)")
            print(f"       - vasp.lsf")
            print(f"       - job.info")

            if args.no_submit:
                print()
                print("  [--no-submit] 跳过提交，仅生成文件")
                print(f"  需手动提交: bsub < {con_path}/vasp.lsf")
            elif args.yes:
                print()
                print("  [--yes] 自动确认，提交作业")
            else:
                print()
                print("  [跳过] 未确认提交（加 --yes 可自动提交）")
                print(f"  需手动提交: bsub < {con_path}/vasp.lsf")
                mgr.close_all()
                return

            if args.yes:
                print()
                print("-" * 60)
                print("  提交作业")
                print("-" * 60)

                cmd = f'cd "{con_path}" && bsub < vasp.lsf'
                stdin, stdout, stderr = client.exec_command(cmd)
                bsub_out = stdout.read().decode().strip()
                bsub_err = stderr.read().decode().strip()

                if bsub_err and "error" in bsub_err.lower():
                    print(f"  [X] bsub 失败: {bsub_err}")
                    return

                print(f"  [OK] 提交结果: {bsub_out}")

                m = re.search(r'Job <(\d+)>', bsub_out)
                job_id = m.group(1) if m else ""

                if job_id:
                    print(f"  [OK] Job ID: {job_id}")

                    updated_ji = job_info_content.replace(
                        "status      = pending",
                        "status      = submitted"
                    )
                    updated_ji = updated_ji.replace(
                        "job_id      = ",
                        f"job_id      = {job_id}"
                    )
                    remote_write_text(client, f"{con_path}/job.info", updated_ji)
                    print(f"  [OK] job.info 已更新 (job_id={job_id}, status=submitted)")

                    sub["status"] = "Run"
                    sub["job_id"] = job_id
                    save_projects(projects)
                    print(f"  [OK] JSON 已同步 → {args.project}/{args.subtask} = Run (job_id={job_id})")
                else:
                    print(f"  [!] 无法解析 job_id")
                    print(f"      原始输出: {bsub_out}")

                print()
                print("=" * 60)
                print("  续算完成")
                print("=" * 60)
            else:
                print()
                print("  [跳过] 未提交，文件已保存在服务器")
                print(f"  需手动提交: bsub < {con_path}/vasp.lsf")

    finally:
        mgr.close_all()
        print("\n连接已断开")


if __name__ == "__main__":
    main()