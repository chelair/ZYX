"""
VASP 异常诊断引擎

数据来源: OSZICAR + OUTCAR（本地或远程）
检测项:
  1. SCF 不收敛        — 电子步连续触及 NELM 上限
  2. 离子步未收敛       — 达 NSW 上限未达收敛精度
  3. 能量发散           — NaN/Inf 或能量飙升
  4. 能量剧烈震荡       — dE 正负交替
  5. I REFUSE           — 实空间投影错误
  6. ZHEGV failed       — 子空间对角化失败
  7. Matrix not pos def — 矩阵非正定
  8. BRACKETING FAILED  — 一维搜索失败
  9. Negative Volume    — 负体积崩溃

用法:
  python scripts/problem_detect.py <项目名> [子任务名]
  python scripts/problem_detect.py --local <本地目录>
"""
import re
import sys
import json
from pathlib import Path
from ssh_manager import SSHManager
from typing import List, Optional


# ═══════════════════════════════════════════════
#  数据结构
# ═══════════════════════════════════════════════

class DiagnosisItem:
    """一条诊断结果"""
    def __init__(self, det_type: str, severity: str, message: str, suggestion: str = ""):
        self.type = det_type
        self.severity = severity
        self.message = message
        self.suggestion = suggestion

    def to_dict(self) -> dict:
        return {"type": self.type, "severity": self.severity,
                "message": self.message, "suggestion": self.suggestion}

    def to_line(self) -> str:
        icon = self.severity[0] if self.severity else "?"
        return f"  {icon} [{self.type}] {self.message}"


class DiagnosisReport:
    """诊断报告"""
    def __init__(self):
        self.items: List[DiagnosisItem] = []
        self.summary = {"🔴": 0, "🟡": 0, "⚪": 0}

    def add(self, item: DiagnosisItem):
        self.items.append(item)
        for key in self.summary:
            if item.severity.startswith(key):
                self.summary[key] += 1
                break

    def has_critical(self) -> bool:
        return any(i.severity.startswith("🔴") for i in self.items)

    def has_warning(self) -> bool:
        return any(i.severity.startswith("🟡") for i in self.items)

    def to_text(self, title: str = "") -> str:
        lines = []
        lines.append("=" * 60)
        if title:
            lines.append(f" 诊断: {title}")
        lines.append("=" * 60)
        for item in self.items:
            lines.append(item.to_line())
            lines.append(f"       -> {item.message}")
            if item.suggestion:
                for s in item.suggestion.split("\n"):
                    lines.append(f"       建议: {s}")
        lines.append("-" * 60)
        parts = []
        if self.summary["🔴"]: parts.append(f"🔴 {self.summary['🔴']} 严重")
        if self.summary["🟡"]: parts.append(f"🟡 {self.summary['🟡']} 警告")
        if self.summary["⚪"]: parts.append(f"⚪ {self.summary['⚪']} 信息")
        lines.append(f" 总计: {', '.join(parts)}" if parts else "  无异常")
        lines.append("=" * 60)
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {"summary": self.summary, "items": [i.to_dict() for i in self.items]}


# ═══════════════════════════════════════════════
#  OSZICAR 解析
# ═══════════════════════════════════════════════

def parse_oszicar(text: str) -> dict:
    """解析 OSZICAR，提取离子步信息和电子步迭代详情"""
    result = {
        "ionic_steps": [],     # [{"n":1, "energy":..., "dE":..., "elec_iters":...}]
        "elec_iters_per_ionic": [],  # 每个离子步的电子步数
        "energies": [],              # 总能量序列
        "all_dE": [],                # 电子步 dE 序列
        "raw_lines": text.split("\n"),
    }

    # 离子步摘要: "   1 F= -123.456 E0= -123.456  d E = -0.123E-03  mag= 12.345"
    ionic_re = re.compile(r'^\s*(\d+)\s+F=\s*([+-]?\d+\.?\d*(?:E[+-]?\d+)?)')
    de_re = re.compile(r'd\s*E\s*=\s*([+-]?\d+\.?\d*(?:E[+-]?\d+)?)')
    # 电子步: "DAV:   1  -0.123E+03  0.456E-01  -0.789E-01"
    elec_re = re.compile(r'^(DAV|RMM):\s+(\d+)\s+([+-]?\d+\.?\d*(?:E[+-]?\d+)?)\s+([+-]?\d+\.?\d*(?:E[+-]?\d+)?)')

    elec_count = 0
    elec_dE_list = []

    for line in result["raw_lines"]:
        s = line.strip()
        if not s:
            continue

        m_elec = elec_re.match(s)
        if m_elec:
            elec_count += 1
            try:
                elec_dE_list.append(float(m_elec.group(4)))
            except ValueError:
                elec_dE_list.append(float("inf"))
            continue

        m_ionic = ionic_re.match(s)
        if m_ionic:
            if result["ionic_steps"]:
                result["ionic_steps"][-1]["elec_iters"] = elec_count
                result["elec_iters_per_ionic"].append(elec_count)
                result["all_dE"].extend(elec_dE_list)

            n = int(m_ionic.group(1))
            try:
                energy = float(m_ionic.group(2))
            except ValueError:
                energy = float("inf")

            m_de = de_re.search(s)
            de_val = float(m_de.group(1)) if m_de else 0.0

            result["ionic_steps"].append({
                "n": n, "energy": energy, "dE": de_val, "elec_iters": 0
            })
            result["energies"].append(energy)
            elec_count = 0
            elec_dE_list = []

    # 最后一个离子步
    if result["ionic_steps"]:
        result["ionic_steps"][-1]["elec_iters"] = elec_count
        result["elec_iters_per_ionic"].append(elec_count)
        result["all_dE"].extend(elec_dE_list)

    return result


# ═══════════════════════════════════════════════
#  OUTCAR 解析（尾部）
# ═══════════════════════════════════════════════

def parse_outcar_tail(text: str) -> dict:
    """解析 OUTCAR 尾部关键信息"""
    result = {
        "converged": False,
        "finished": False,
        "last_force_max": None,
        "nsw": None,
        "fatal_errors": [],
    }

    if "reached required accuracy" in text:
        result["converged"] = True

    if "General timing and accounting informations for this job" in text:
        result["finished"] = True

    # 致命错误文本匹配
    fatal_patterns = [
        "I REFUSE TO CONTINUE",
        "EDDDAV: Call to ZHEGV failed",
        "ZHEGV",
        "Matrix block not positive definite",
        "BRACKETING FAILED",
        "negative volume",
        "internal error in SITES",
    ]
    for pat in fatal_patterns:
        if pat in text:
            result["fatal_errors"].append(pat)

    # 提取最后一步最大力: 从最后一个 TOTAL-FORCE 块
    in_force = False
    force_values = []
    for line in text.split("\n"):
        if "TOTAL-FORCE" in line:
            in_force = True
            force_values = []
            continue
        if in_force:
            if "-------" in line:
                continue
            if not line.strip():
                in_force = False
                continue
            parts = line.strip().split()
            if len(parts) >= 6:
                try:
                    fx, fy, fz = float(parts[3]), float(parts[4]), float(parts[5])
                    force_values.append(max(abs(fx), abs(fy), abs(fz)))
                except ValueError:
                    pass
    if force_values:
        result["last_force_max"] = max(force_values)

    # 提取 NSW
    m = re.search(r'NSW\s*=\s*(\d+)', text, re.IGNORECASE)
    if m:
        result["nsw"] = int(m.group(1))

    return result


# ═══════════════════════════════════════════════
#  检测器 1: SCF 不收敛
# ═══════════════════════════════════════════════

def detect_scf_not_converged(oszicar: dict, nelm: int = 100) -> List[DiagnosisItem]:
    """连续 >=3 个离子步的电子步数 == NELM"""
    items = []
    iters = oszicar.get("elec_iters_per_ionic", [])
    if not iters:
        return items

    consecutive = max_c = 0
    for c in iters:
        if c >= nelm:
            consecutive += 1
            max_c = max(max_c, consecutive)
        else:
            consecutive = 0

    if max_c >= 3:
        items.append(DiagnosisItem(
            "SCF_NOT_CONVERGED", "🟡 警告",
            f"连续 {max_c} 个离子步触及 NELM={nelm} 上限",
            "ALGO=Fast -> Normal/All  |  AMIX=0.2 BMIX=0.0001  |  NELM=100"
        ))
    return items


# ═══════════════════════════════════════════════
#  检测器 2: 离子步未收敛
# ═══════════════════════════════════════════════

def detect_ionic_not_converged(oszicar: dict, outcar: dict,
                                ediffg: float = -0.02) -> List[DiagnosisItem]:
    items = []
    steps = oszicar.get("ionic_steps", [])
    nsw = outcar.get("nsw") or len(steps)
    actual = len(steps)

    if outcar.get("converged"):
        return items

    hit_nsw = actual >= nsw
    last_f = outcar.get("last_force_max")
    force_str = f"{last_f:.4f}" if last_f is not None else "N/A"
    force_ok = True
    if last_f is not None and ediffg < 0:
        force_ok = last_f <= abs(ediffg)

    if hit_nsw and not force_ok:
        items.append(DiagnosisItem(
            "IONIC_NOT_CONVERGED", "🟡 警告",
            f"达 NSW={nsw} 未收敛, 最终力 {force_str} > |EDIFFG|={abs(ediffg)}",
            "力下降中 -> 续算  |  力躺平 -> IBRION=1 突破死锁"
        ))
    elif hit_nsw and force_ok:
        items.append(DiagnosisItem(
            "IONIC_NOT_CONVERGED", "⚪ 信息",
            f"达 NSW={nsw}，力已收敛 ({force_str})，可转静态自洽",
            ""))
    elif not hit_nsw and outcar.get("finished"):
        items.append(DiagnosisItem(
            "IONIC_NOT_CONVERGED", "⚪ 待接续",
            f"作业结束 ({actual}/{nsw} 步) 未收敛，walltime 可能到期",
            "触发续算流程"))

    # 力躺平检测
    if hit_nsw and not force_ok and len(steps) >= 20:
        ens = oszicar.get("energies", [])[-20:]
        if len(ens) >= 10:
            avg = sum(ens) / len(ens)
            var = sum((e - avg)**2 for e in ens) / len(ens)
            if var < 1e-6:
                items.append(DiagnosisItem(
                    "FORCE_PLATEAU", "🟡 警告",
                    "力收敛曲线已躺平，能量几乎不变",
                    "续算时 IBRION=1 (准牛顿) 突破死锁"))
    return items


# ═══════════════════════════════════════════════
#  检测器 3: 能量发散
# ═══════════════════════════════════════════════

def detect_energy_divergence(oszicar: dict) -> List[DiagnosisItem]:
    items = []

    # NaN/Inf/******
    for line in oszicar.get("raw_lines", []):
        if "NaN" in line or "Inf" in line or "******" in line:
            items.append(DiagnosisItem(
                "ENERGY_DIVERGENCE", "🔴 严重",
                "OSZICAR 出现 NaN/Inf/******，计算已崩溃",
                "CONTCAR 已损坏不可用。退回上一步，检查原子间距"))
            return items

    # 趋势: 最后 5 步
    ens = oszicar.get("energies", [])
    if len(ens) >= 5:
        last5 = ens[-5:]
        increasing = all(abs(last5[i]) > abs(last5[i-1]) for i in range(1, 5))
        if increasing:
            delta = abs(last5[-1] - last5[-2])
            if delta > 5.0:
                items.append(DiagnosisItem(
                    "ENERGY_DIVERGENCE", "🔴 严重",
                    f"能量单调飙升，末两步 |ΔE|={delta:.2f} eV",
                    "检查原子间距 / KPOINTS"))
            elif delta > 1.0:
                items.append(DiagnosisItem(
                    "ENERGY_DIVERGENCE", "🟡 警告",
                    f"能量上升趋势，末两步 |ΔE|={delta:.2f} eV",
                    "密切监控"))
    return items


# ═══════════════════════════════════════════════
#  检测器 4: 能量震荡
# ═══════════════════════════════════════════════

def detect_energy_oscillation(oszicar: dict) -> List[DiagnosisItem]:
    items = []
    all_de = oszicar.get("all_dE", [])
    if len(all_de) < 10:
        return items

    recent = all_de[-20:]
    flips = max_flips = 0
    cur = 0
    for i in range(1, len(recent)):
        if recent[i] * recent[i-1] < 0:
            cur += 1
            flips += 1
            max_flips = max(max_flips, cur)
        else:
            cur = 0

    amp = max(recent) - min(recent) if recent else 0

    if max_flips >= 6 and amp > 0.5:
        items.append(DiagnosisItem(
            "ENERGY_OSCILLATION", "🟡 警告",
            f"dE 交替 {max_flips} 次，幅度 {amp:.2f} eV",
            "电子步 -> 减小 AMIX/BMIX 或 ALGO=All\n离子步 -> 减小 POTIM"))
    return items


# ═══════════════════════════════════════════════
#  检测器 5: 致命错误文本
# ═══════════════════════════════════════════════

FATAL_DEFS = [
    ("I REFUSE TO CONTINUE", "REALSPACE_ERROR",
     "实空间投影错误", "LREAL = .FALSE."),
    ("EDDDAV: Call to ZHEGV failed", "ZHEGV_FAILED",
     "子空间对角化失败 (原子间距 < 0.7 Å ?)", "调小 POTIM，检查原子间距"),
    ("Matrix block not positive definite", "MATRIX_NOT_POSDEF",
     "RMM-DIIS 矩阵非正定", "清 WAVECAR 重算 / ALGO=Normal"),
    ("BRACKETING FAILED", "BRACKETING_FAILED",
     "一维搜索失败", "检查电子步收敛 / IBRION=1"),
    ("negative volume", "NEGATIVE_VOLUME",
     "晶胞体积为负", "ISIF=2 弛豫原子 -> ISIF=3 优化晶胞 + 提高 ENCUT"),
]

def detect_fatal_errors(outcar_text: str) -> List[DiagnosisItem]:
    items = []
    for pat, code, desc, sug in FATAL_DEFS:
        if pat in outcar_text:
            items.append(DiagnosisItem(code, "🔴 致命", desc, sug))
    return items


# ═══════════════════════════════════════════════
#  检测器 6: 离子步极少
# ═══════════════════════════════════════════════

def detect_too_few_ionic_steps(oszicar: dict, outcar: dict) -> List[DiagnosisItem]:
    items = []
    actual = len(oszicar.get("ionic_steps", []))
    if outcar.get("finished") and 0 < actual < 5:
        items.append(DiagnosisItem(
            "TOO_FEW_STEPS", "🟡 警告",
            f"仅 {actual} 个离子步即结束，walltime 可能太短",
            "检查 -W 参数"))
    return items


# ═══════════════════════════════════════════════
#  主引擎
# ═══════════════════════════════════════════════

def run_all_detectors(oszicar_text: str, outcar_text: str,
                      nelm: int = 100, ediffg: float = -0.02,
                      nsw: int = None) -> DiagnosisReport:
    report = DiagnosisReport()
    oszicar = parse_oszicar(oszicar_text)
    outcar = parse_outcar_tail(outcar_text)
    if nsw is not None:
        outcar["nsw"] = nsw

    # 顺序: 致命 > 发散 > SCF > 离子步 > 震荡 > 极少步
    for item in detect_fatal_errors(outcar_text):       report.add(item)
    for item in detect_energy_divergence(oszicar):       report.add(item)
    for item in detect_scf_not_converged(oszicar, nelm): report.add(item)
    for item in detect_ionic_not_converged(oszicar, outcar, ediffg): report.add(item)
    for item in detect_energy_oscillation(oszicar):      report.add(item)
    for item in detect_too_few_ionic_steps(oszicar, outcar): report.add(item)
    return report


def diagnose_local(local_dir: Path, nelm: int = 100,
                   ediffg: float = -0.02, nsw: int = None) -> DiagnosisReport:
    oszicar_text = outcar_text = ""
    p_osz = local_dir / "OSZICAR"
    if p_osz.exists():
        oszicar_text = p_osz.read_text(encoding="utf-8", errors="replace")
    p_out = local_dir / "OUTCAR"
    if p_out.exists():
        lines = p_out.read_text(encoding="utf-8", errors="replace").split("\n")
        outcar_text = "\n".join(lines[-500:])
    if not outcar_text:
        p_tail = local_dir / "OUTCAR.tail"
        if p_tail.exists():
            outcar_text = p_tail.read_text(encoding="utf-8", errors="replace")

    if not oszicar_text and not outcar_text:
        r = DiagnosisReport()
        r.add(DiagnosisItem("NO_DATA", "⚪ 信息",
                            f"{local_dir} 中未找到 OSZICAR 或 OUTCAR", ""))
        return r
    return run_all_detectors(oszicar_text, outcar_text, nelm, ediffg, nsw)


# ═══════════════════════════════════════════════
#  写入诊断文件（供 vasp_check 调用）
# ═══════════════════════════════════════════════

def write_diagnosis(local_dir: Path, report: DiagnosisReport):
    """将诊断报告写入本地目录的 .diagnosis 文件"""
    diag_path = local_dir / ".diagnosis"
    diag_path.write_text(report.to_text(str(local_dir.name)), encoding="utf-8")
    # 同时写 JSON 格式供程序读取
    json_path = local_dir / ".diagnosis.json"
    json_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
                         encoding="utf-8")
    return diag_path


# ═══════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description="VASP 异常诊断")
    parser.add_argument("project", nargs="?", help="项目名")
    parser.add_argument("subtask", nargs="?", help="子任务名")
    parser.add_argument("--local", help="本地目录路径")
    parser.add_argument("--nelm", type=int, default=100)
    parser.add_argument("--ediffg", type=float, default=-0.02)
    parser.add_argument("--nsw", type=int, default=None)
    parser.add_argument("--host", default="mdye@hpc.xmu.edu.cn")
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--key", default=str(SSH_KEY_DEFAULT))
    parser.add_argument("--timeout", type=int, default=15)
    args = parser.parse_args()

    if args.local:
        d = Path(args.local)
        if not d.exists():
            print(f"[X] 目录不存在: {d}"); sys.exit(1)
        r = diagnose_local(d, args.nelm, args.ediffg, args.nsw)
        print(r.to_text(str(d)))
        write_diagnosis(d, r)
        return

    if not args.project:
        parser.print_help(); sys.exit(1)

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from config import LOCAL_BASE, SSH_KEY_DEFAULT
    from ssh_connect import parse_host

    from project_store import load_projects
    projects = load_projects()

    proj = None
    for p in projects:
        if p["name"] == args.project:
            proj = p; break
    if not proj:
        print(f"[X] 未找到项目: {args.project}"); sys.exit(1)


    mgr = SSHManager()
    try:
        username, hostname, client = mgr.get_parsed(args.host, args.port, args.key, timeout=args.timeout)

        targets = [s for s in proj.get("subs", [])
                   if not args.subtask or s["name"] == args.subtask]
        if not targets:
            print("[X] 无匹配子任务"); sys.exit(1)

        for sub in targets:
            rdir = f"{proj['path']}/{sub['dir']}"
            print(f"\n[诊断] {proj['name']} / {sub['name']}  ({rdir})")

            stdin, stdout, _ = client.exec_command(
                f'cat "{rdir}/OSZICAR" 2>/dev/null || echo "NO_OSZICAR"')
            oszicar_text = stdout.read().decode("utf-8", errors="replace")

            stdin, stdout, _ = client.exec_command(
                f'tail -500 "{rdir}/OUTCAR" 2>/dev/null || echo "NO_OUTCAR"')
            outcar_text = stdout.read().decode("utf-8", errors="replace")

            if "NO_OSZICAR" in oszicar_text and "NO_OUTCAR" in outcar_text:
                print("  ⚪ 无输出文件"); continue

            report = run_all_detectors(oszicar_text, outcar_text,
                                       args.nelm, args.ediffg, args.nsw)
            print(report.to_text(f"{proj['name']} / {sub['name']}"))

            local_base = LOCAL_BASE
            local_dir = local_base / proj["name"] / sub["name"]
            if local_dir.exists():
                write_diagnosis(local_dir, report)
                print(f"  [OK] .diagnosis 已写入 {local_dir}")
    finally:
        mgr.close_all()


if __name__ == "__main__":
    main()