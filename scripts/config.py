"""
ZYX Skill 本地路径配置

所有本地硬编码路径集中在此，各脚本通过 from config import ... 引用。
服务器路径（HPC_HOST / HPC_PORT / 远程项目路径）保留在原脚本中不变。
"""
from pathlib import Path


# ──────────────────────────────────────────────
#  本地数据目录
# ──────────────────────────────────────────────

LOCAL_BASE = Path("D:/POSCAR/HuaSuan/check")
"""VASP 检查结果本地存放根目录"""

DAILY_CHECK_DIR = Path("D:/POSCAR/HuaSuan/check/DailyCheck")
"""每日检查汇总报告存放目录"""


# ──────────────────────────────────────────────
#  VESTA 可执行文件
# ──────────────────────────────────────────────

VESTA_EXE = Path("D:/Working/APP/VESTA-win64/VESTA.exe")
"""VESTA 主程序路径"""

VESTA_CANDIDATE_PATHS = [
    Path("D:/Working/APP/VESTA-win64/VESTA.exe"),
    Path("C:/Program Files/VESTA-win64/VESTA.exe"),
    Path("C:/Program Files/VESTA/VESTA.exe"),
    Path("C:/Program Files (x86)/VESTA/VESTA.exe"),
]
"""VESTA 自动检测候选路径列表"""


# ──────────────────────────────────────────────
#  SSH 密钥路径
# ──────────────────────────────────────────────

SSH_KEY_DEFAULT = Path.home() / ".ssh" / "id_rsa"
"""默认 SSH RSA 私钥路径"""

SSH_KEY_ED25519 = Path.home() / ".ssh" / "id_ed25519"
"""备用 SSH Ed25519 私钥路径"""


# ──────────────────────────────────────────────
#  HPC 服务器连接
# ──────────────────────────────────────────────

HPC_HOST = "mdye@hpc.xmu.edu.cn"
"""HPC 服务器地址 (user@host)"""

HPC_PORT = 22
"""SSH 端口"""
"""备用 SSH Ed25519 私钥路径"""