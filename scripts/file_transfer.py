"""
文件传输 — 通过 SFTP 下载/上传 VASP 结果文件
"""

DOWNLOAD_FILES = ["POSCAR", "CONTCAR", "INCAR"]
"""默认下载的文件列表"""


def download_file(sftp, remote_path, local_path, fname):
    """通过 SFTP 下载单个文件到本地

    Args:
        sftp: paramiko SFTPClient
        remote_path: 远程文件路径
        local_path: 本地目标路径 (Path)
        fname: 显示用的文件名

    Returns:
        bool 是否成功
    """
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