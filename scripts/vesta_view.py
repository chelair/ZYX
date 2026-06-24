"""
VESTA 可视化 — 打开 POSCAR 和 CONTCAR 进行结构对比

用法:
  python scripts/vesta_view.py <文件或目录>
  python scripts/vesta_view.py {LOCAL_BASE}/Co4N_0703/abs/2_1
  python scripts/vesta_view.py {LOCAL_BASE}/Co4N_0703/abs/2_1/CONTCAR

说明:
  1. 传入目录 → 自动找该目录下的 POSCAR 和 CONTCAR
  2. 传入文件 → 只打开该文件
  3. 有 CONTCAR 时会尝试叠加两个文件
"""
import argparse
import subprocess
import sys
import time
from config import VESTA_EXE, VESTA_CANDIDATE_PATHS
from pathlib import Path


def find_vesta():
    """自动定位 VESTA.exe — 从 config 获取候选路径"""
    for p in VESTA_CANDIDATE_PATHS:
        if p.exists():
            return p
    import shutil
    found = shutil.which("VESTA.exe") or shutil.which("VESTA")
    if found:
        return Path(found)
    return None


def open_in_vesta(vesta_exe, file_path):
    """用 VESTA 打开一个文件（Windows ShellExecute 风格）"""
    if not file_path.exists():
        print(f"  [!] 文件不存在: {file_path}")
        return False
    try:
        subprocess.Popen(
            [str(vesta_exe), str(file_path)],
            executable=str(vesta_exe),
            shell=False,
        )
        print(f"  [OK] 已打开: {file_path.name}")
        return True
    except Exception as e:
        print(f"  [X] 打开失败: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="VESTA 结构可视化")
    parser.add_argument("path", nargs="?", default=None,
                        help="VASP 文件路径 或 包含 POSCAR/CONTCAR 的目录")
    parser.add_argument("--vesta", default=None, help="VESTA.exe 路径")
    args = parser.parse_args()

    # 定位 VESTA
    vesta_exe = Path(args.vesta) if args.vesta else find_vesta()
    if not vesta_exe or not vesta_exe.exists():
        print(f"[X] 找不到 VESTA.exe")
        print(f"   请通过 --vesta 指定路径，或安装到默认位置")
        sys.exit(1)
    print(f"[VESTA] {vesta_exe}")

    # 确定要打开的路径
    base = Path(args.path) if args.path else Path.cwd()

    if base.is_file():
        # 传入的是单个文件
        open_in_vesta(vesta_exe, base)
        return

    if base.is_dir():
        # 传入的是目录 → 找 POSCAR / CONTCAR
        poscar = base / "POSCAR"
        contcar = base / "CONTCAR"

        if not poscar.exists() and not contcar.exists():
            print(f"[X] 目录 {base} 中未找到 POSCAR 或 CONTCAR")
            print(f"   请指定 VASP 文件路径或包含 POSCAR/CONTCAR 的目录")
            sys.exit(1)

        print(f"[目录] {base}")

        # 先关掉已有的 VESTA 实例，确保干净打开
        subprocess.run(
            ["powershell", "-Command",
             "Get-Process VESTA -ErrorAction SilentlyContinue | Stop-Process -Force"],
            capture_output=True, timeout=5)
        time.sleep(1)

        # 1) 打开 POSCAR（如果有）
        poscar_ok = False
        if poscar.exists():
            poscar_ok = open_in_vesta(vesta_exe, poscar)
            time.sleep(1.5)  # 等 VESTA 加载

        # 2) 打开 CONTCAR（如果有）→ VESTA 单实例会检测到第二个进程
        #    并将文件传给已有实例
        if contcar.exists() and poscar_ok:
            # 再次启动 VESTA，它会通过 DDE/IPC 把 CONTCAR 传给已有实例
            print(f"  [..] 正在叠加导入 CONTCAR ...")
            time.sleep(1)
            subprocess.Popen(
                [str(vesta_exe), str(contcar)],
                executable=str(vesta_exe),
                shell=False,
            )
            print(f"  [OK] 已发送 CONTCAR 到 VESTA")
            print(f"\n  ===  VESTA 操作提示 ===")
            print(f"  如果弹出对话框，请选择「Open as a new phase」")
            print(f"  然后在 Edit → Edit Data → Phase 中给两个相设不同颜色")
            print(f"  =========================")
        elif contcar.exists() and not poscar_ok:
            open_in_vesta(vesta_exe, contcar)

        return

    print(f"[X] 路径无效: {base}")
    sys.exit(1)


if __name__ == "__main__":
    main()