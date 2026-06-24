"""
OUTCAR 分析 — 远程扫描 OUTCAR，判断收敛状态和 ionic 步数

功能:
  - scan_data_file:   远程项目目录预扫描，一次 SSH 遍历所有 OUTCAR
  - check_outcar:     读取单目录 OUTCAR，判断收敛状态
  - count_ionic_steps: 统计 ionic 步数
"""
import shlex

# ──────────────────────────────────────────────
#  data 预扫描（增强版）
# ──────────────────────────────────────────────

def scan_data_file(client, base_path):
    """在远程项目目录生成增强版 data 文件

    一次 SSH 遍历所有 OUTCAR，避免逐个子任务重复读取。
    生成 key=value 格式的临时文件，解析后返回字典。

    Returns:
        {full_dir_path: {status, ionic, energy, wavecar}}
    """
    script = (
        'cd ' + shlex.quote(base_path) + ' && TMP=$(mktemp) && '
        'find . -name OUTCAR -type f -print0 | while IFS= read -r -d "\" f; do '
        'd=$(dirname "$f"); '
        'echo "DIR=$d" >> "$TMP"; '
        'if grep -q "reached required accuracy" "$f"; then echo "STATUS=OK" >> "$TMP"; '
        'elif grep -q "General timing and accounting" "$f"; then echo "STATUS=FAIL" >> "$TMP"; '
        'elif grep -q "free  energy" "$f"; then echo "STATUS=STOP" >> "$TMP"; '
        'else echo "STATUS=NO" >> "$TMP"; fi; '
        'echo "IONIC=$(grep -c \"free  energy   TOTEN  =\" "$f")" >> "$TMP"; '
        'echo "ENERGY=$(grep \"free  energy   TOTEN  =\" "$f" | tail -1)" >> "$TMP"; '
        'echo "WAVECAR=$(ls -l "$d/WAVECAR" 2>/dev/null | awk \"{print $5}\" || echo 0)" >> "$TMP"; '
        'done && cat "$TMP" && rm -f "$TMP"'
    )
    try:
        stdin, stdout, _ = client.exec_command(script)
        raw = stdout.read().decode("utf-8", errors="replace").strip()
    except Exception:
        return {}

    result = {}
    current_dir = None
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("DIR="):
            current_dir = line[4:]
            result[current_dir] = {}
        elif current_dir and "=" in line:
            k, v = line.split("=", 1)
            result[current_dir][k.lower()] = v
    return result


# ──────────────────────────────────────────────
#  OUTCAR 收敛判断
# ──────────────────────────────────────────────

def check_outcar(client, remote_dir):
    """SSH 远程检查 OUTCAR 收敛状态

    检测逻辑:
      - 读取 INCAR 中 IBRION 确定任务类型
      - IBRION=2(优化)/3(NEB): 必须 accuracy 才算收敛
      - IBRION=-1(SCF): 跑完就算完成

    Returns:
        (status_label, energy, job_finished, task_type, ibrion_val)
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
    try:
        calc_type = type_tag.get(int(ibrion_val)) if ibrion_val and ibrion_val.lstrip("-").isdigit() else ""
    except ValueError:
        calc_type = ""

    from summary_report import clean_energy_str

    if status == "CONVERGED":
        print(f"      [OK] {calc_type} 已收敛，作业已完成")
        print(f"       {clean_energy_str(energy)}")
        return "已收敛", energy, True, "结构优化" if ibrion_val == "2" else "NEB" if ibrion_val == "3" else "SCF", ibrion_val

    elif status == "COMPLETED":
        print(f"      [OK] {calc_type} 已完成")
        print(f"       {clean_energy_str(energy)}")
        return "已完成", energy, True, "结构优化" if ibrion_val == "2" else "NEB" if ibrion_val == "3" else "SCF", ibrion_val

    elif status == "NOT_CONVERGED_FINISHED":
        print(f"      [X] {calc_type} 作业已结束但未收敛")
        print(f"       {clean_energy_str(energy)}")
        return "未收敛", energy, True, "结构优化" if ibrion_val == "2" else "NEB" if ibrion_val == "3" else "SCF", ibrion_val

    elif status == "FINISHED_NO_RESULT":
        print(f"      [X] 作业已结束，但无能量记录")
        return "未收敛", "", True, "", ibrion_val

    elif status == "CONVERGED_RUNNING":
        print(f"       {calc_type} 已收敛（作业仍在运行中）")
        print(f"       {clean_energy_str(energy)}")
        return "收敛中", energy, False, "结构优化" if ibrion_val == "2" else "NEB" if ibrion_val == "3" else "SCF", ibrion_val

    elif status == "NOT_CONVERGED_WITH_ENERGY":
        print(f"      [!] {calc_type} 未收敛（有能量记录，可能在运行）")
        print(f"       {clean_energy_str(energy)}")
        return "未收敛", energy, False, "结构优化" if ibrion_val == "2" else "NEB" if ibrion_val == "3" else "SCF", ibrion_val

    elif status == "NOT_CONVERGED_NO_ENERGY":
        print(f"      [X] 未收敛，无能量记录")
        return "未收敛", "无能量记录", False, "", ibrion_val

    return "解析失败", "", False, "", ""


# ──────────────────────────────────────────────
#  Ionic 步数计数
# ──────────────────────────────────────────────

def count_ionic_steps_remote(client, remote_dir):
    """SSH 远程读取 OUTCAR 中的 ionic step 数
    统计 "free  energy   TOTEN  =" 出现次数
    """
    try:
        stdin, stdout, _ = client.exec_command(
            f'grep -c "free  energy   TOTEN  =" {remote_dir}/OUTCAR 2>/dev/null || echo 0'
        )
        result = stdout.read().decode().strip()
        return int(result) if result.isdigit() else 0
    except Exception:
        return 0