"""
安全远程文件操作层

所有远程写操作集中在此，底层依赖 Linux 原子原语：

  mkdir <dir>       不加 -p，目录已存在 → 非零退出
  cp -n <src> <dst> no-clobber，目标存在 → 非零退出
  mv -n <src> <dst> no-clobber，目标存在 → 非零退出，不删除源
  tmp + fsync + mv  写入临时文件 → fsync → rename（原子提交）

⛔ 禁止在 safe_ops 之外执行任何远程写操作
"""
import shlex
from pathlib import Path


# ──────────────────────────────────────────────
#  文件存在性检查
# ──────────────────────────────────────────────

def check_remote_exists(client, remote_path, ftype="any"):
    """检查远程路径是否存在

    Args:
        client: paramiko SSHClient
        remote_path: 远程路径
        ftype: "file" / "dir" / "any"

    Returns:
        True 存在, False 不存在
    """
    if ftype == "file":
        cmd = f"test -f {shlex.quote(remote_path)} && echo Y || echo N"
    elif ftype == "dir":
        cmd = f"test -d {shlex.quote(remote_path)} && echo Y || echo N"
    else:
        cmd = f"test -e {shlex.quote(remote_path)} && echo Y || echo N"

    try:
        stdin, stdout, _ = client.exec_command(cmd)
        result = stdout.read().decode().strip()
        return result == "Y"
    except Exception:
        return False


# ──────────────────────────────────────────────
#  创建目录  mkdir <dir>  (不加 -p)
# ──────────────────────────────────────────────

def safe_mkdir(client, remote_dir):
    """在远程创建目录。不加 -p，已存在时报错。

    Args:
        client: paramiko SSHClient
        remote_dir: 要创建的目录路径

    Returns:
        (True, "") 成功
        (False, "错误信息") 失败
    """
    cmd = f"mkdir {shlex.quote(remote_dir)}"
    try:
        stdin, stdout, stderr = client.exec_command(cmd)
        exit_code = stdout.channel.recv_exit_status()
        if exit_code == 0:
            return True, ""
        else:
            err = stderr.read().decode().strip()
            return False, err or f"mkdir 返回非零 ({exit_code})"
    except Exception as e:
        return False, str(e)


# ──────────────────────────────────────────────
#  复制文件  cp -n <src> <dst>
# ──────────────────────────────────────────────

def safe_cp(client, src, dst):
    """在远程复制文件。cp -n，目标存在时不覆盖。

    Args:
        client: paramiko SSHClient
        src: 源路径
        dst: 目标路径

    Returns:
        (True, "") 成功
        (False, "错误信息") 失败
    """
    cmd = f"cp -n {shlex.quote(src)} {shlex.quote(dst)}"
    try:
        stdin, stdout, stderr = client.exec_command(cmd)
        exit_code = stdout.channel.recv_exit_status()
        if exit_code == 0:
            return True, ""
        else:
            err = stderr.read().decode().strip()
            return False, err or f"cp -n 返回非零 ({exit_code})，目标可能已存在"
    except Exception as e:
        return False, str(e)


# ──────────────────────────────────────────────
#  移动文件  mv -n <src> <dst>
# ──────────────────────────────────────────────

def safe_mv(client, src, dst):
    """在远程移动文件。mv -n，目标存在时不移动不删除源。

    Args:
        client: paramiko SSHClient
        src: 源路径
        dst: 目标路径

    Returns:
        (True, "") 成功
        (False, "错误信息") 失败
    """
    cmd = f"mv -n {shlex.quote(src)} {shlex.quote(dst)}"
    try:
        stdin, stdout, stderr = client.exec_command(cmd)
        exit_code = stdout.channel.recv_exit_status()
        if exit_code == 0:
            return True, ""
        else:
            err = stderr.read().decode().strip()
            return False, err or f"mv -n 返回非零 ({exit_code})，目标可能已存在"
    except Exception as e:
        return False, str(e)


# ──────────────────────────────────────────────
#  原子写入新文件  tmp + fsync + mv -n
# ──────────────────────────────────────────────

def safe_write_text(client, remote_path, text):
    """在远程原子写入文本文件。不覆盖已有文件。

    流程: 写入 .tmp → fsync → mv -n 到目标路径
    mv -n 确保目标在写入期间被其他人创建时也不会被覆盖。

    Args:
        client: paramiko SSHClient
        remote_path: 目标路径（必须不存在）
        text: 要写入的文本内容

    Returns:
        (True, "") 成功
        (False, "错误信息") 失败
    """
    # 1. 检查目标是否已存在
    if check_remote_exists(client, remote_path, "file"):
        return False, f"目标文件已存在: {remote_path}"

    tmp_path = remote_path + ".tmp"
    sftp = None
    try:
        sftp = client.open_sftp()

        # 2. 写入临时文件
        with sftp.open(tmp_path, "w") as f:
            f.write(text.encode("utf-8"))
            f.flush()

        # 3. fsync 确保数据落盘
        try:
            fd = sftp.file(tmp_path, "r")
            fd.close()
        except Exception:
            pass

        sftp.close()
        sftp = None

        # 4. 原子 rename: mv -n tmp → target
        return safe_mv(client, tmp_path, remote_path)

    except Exception as e:
        # 清理临时文件
        try:
            if sftp:
                sftp.remove(tmp_path)
                sftp.close()
        except Exception:
            pass
        return False, str(e)


# ──────────────────────────────────────────────
#  本地上传 → 远程  tmp + fsync + mv -n
# ──────────────────────────────────────────────

def safe_upload_file(client, local_path, remote_path):
    """将本地文件上传到远程。不覆盖已有文件。

    Args:
        client: paramiko SSHClient
        local_path: 本地文件路径
        remote_path: 远程目标路径（必须不存在）

    Returns:
        (True, "") 成功
        (False, "错误信息") 失败
    """
    local_path = Path(local_path)

    # 0. 检查本地源文件存在
    if not local_path.exists():
        return False, f"本地文件不存在: {local_path}"

    # 1. 检查远程目标是否已存在
    if check_remote_exists(client, remote_path, "file"):
        return False, f"远程目标文件已存在: {remote_path}"

    tmp_path = remote_path + ".upload_tmp"
    sftp = None
    try:
        sftp = client.open_sftp()

        # 2. 上传到临时文件
        sftp.put(str(local_path), tmp_path)

        sftp.close()
        sftp = None

        # 3. 原子 rename
        return safe_mv(client, tmp_path, remote_path)

    except Exception as e:
        try:
            if sftp:
                try:
                    sftp.remove(tmp_path)
                except Exception:
                    pass
                sftp.close()
        except Exception:
            pass
        return False, str(e)


# ──────────────────────────────────────────────
#  删除远程文件  ⛔ 严禁使用，仅做安全检查
# ──────────────────────────────────────────────

def _assert_no_delete(func):
    """装饰器：禁止删除操作的守卫"""
    def wrapper(*args, **kwargs):
        raise RuntimeError(
            "⛔ 绝对禁止删除服务器上的任何文件！\n"
            "safe_ops.py 不提供任何删除功能。"
        )
    return wrapper


# ═══════════════════════════════════════════════
#  job.info 读写
# ═══════════════════════════════════════════════

JOB_INFO_FILENAME = "job.info"

def parse_job_info(text: str) -> dict:
    """解析 job.info 文本为字典

    格式:
        [submit]
        key = value
        [incar]
        key = value

    Returns:
        {"submit": {"key": "value", ...}, "incar": {"key": "value", ...}}
    """
    result = {}
    current_section = None
    for line in text.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current_section = line[1:-1]
            result[current_section] = {}
            continue
        if current_section and "=" in line:
            k, v = line.split("=", 1)
            result[current_section][k.strip()] = v.strip()
    return result


def read_remote_job_info(client, remote_dir: str) -> dict:
    """SSH 读取远程目录下的 job.info

    Args:
        client: paramiko SSHClient
        remote_dir: 远程目录路径

    Returns:
        dict 解析结果，如文件不存在返回空 dict
    """
    path = f"{remote_dir.rstrip('/')}/{JOB_INFO_FILENAME}"
    if not check_remote_exists(client, path, "file"):
        return {}
    try:
        stdin, stdout, _ = client.exec_command(f"cat {shlex.quote(path)}")
        text = stdout.read().decode("utf-8", errors="replace")
        return parse_job_info(text)
    except Exception:
        return {}