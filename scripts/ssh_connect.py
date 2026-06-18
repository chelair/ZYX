"""
SSH 连接超算服务器 — 连接、登录、交互式操作

用法:
  python scripts/ssh_connect.py <host> <project_dir> [options]

参数:
  host          用户名@服务器地址，如 mdye@hpc.xmu.edu.cn
  project_dir   服务器上的项目目录路径

选项:
  --port PORT           SSH 端口（默认 22）
  --key KEY_PATH        私钥路径（默认 ~/.ssh/id_rsa）
  --password PASSWORD   密码（不推荐，优先用密钥）
  --timeout SEC         连接超时秒数（默认 10）

示例:
  python scripts/ssh_connect.py mdye@hpc.xmu.edu.cn /data/gpfs03/mdye/projects
"""
import argparse
import os
import sys
from pathlib import Path

try:
    import paramiko
except ImportError:
    print("需要安装 paramiko，运行: pip install paramiko")
    sys.exit(1)


def parse_args():
    parser = argparse.ArgumentParser(description="SSH 连接超算服务器")
    parser.add_argument("host", help="用户名@服务器地址")
    parser.add_argument("project_dir", help="服务器上的项目目录路径")
    parser.add_argument("--port", type=int, default=22, help="SSH 端口（默认 22）")
    parser.add_argument("--key", default=str(Path.home() / ".ssh" / "id_rsa"), help="私钥路径")
    parser.add_argument("--password", default=None, help="密码（不推荐）")
    parser.add_argument("--timeout", type=int, default=10, help="连接超时秒数（默认 10）")
    return parser.parse_args()


def parse_host(host_str):
    """解析 user@host 格式"""
    if "@" in host_str:
        username, hostname = host_str.rsplit("@", 1)
    else:
        username, hostname = os.getenv("USER") or os.getenv("USERNAME"), host_str
    return username, hostname


def create_ssh_client(hostname, port, username, key_path, password, timeout):
    """创建 SSH 连接并返回 client"""
    print(f"正在连接 {username}@{hostname}:{port} ...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    if password:
        client.connect(hostname, port=port, username=username,
                       password=password, timeout=timeout)
    elif os.path.exists(key_path):
        key = paramiko.RSAKey.from_private_key_file(key_path)
        client.connect(hostname, port=port, username=username,
                       pkey=key, timeout=timeout)
    else:
        print(f"⚠ 密钥文件不存在: {key_path}")
        print("请先配置 SSH 密钥，或用 --password 指定密码")
        return None
    return client


def check_remote_dir(client, remote_dir):
    """确认远程目录存在并列出内容"""
    stdin, stdout, stderr = client.exec_command(f"cd {remote_dir} && pwd && ls -lh")
    exit_status = stdout.channel.recv_exit_status()

    if exit_status == 0:
        output = stdout.read().decode().strip()
        lines = output.split("\n")
        print(f" 项目目录: {lines[0]}")
        print(" 文件列表:")
        for line in lines[1:]:
            print(f"   {line}")
        return True
    else:
        error = stderr.read().decode().strip()
        print(f"❌ 无法进入目录 {remote_dir}: {error}")
        return False


def main():
    args = parse_args()
    username, hostname = parse_host(args.host)
    key_path = os.path.expanduser(args.key)

    client = create_ssh_client(hostname, args.port, username,
                                key_path, args.password, args.timeout)
    if client is None:
        sys.exit(1)

    print(f"✅ 已连接到 {username}@{hostname}")

    if not check_remote_dir(client, args.project_dir):
        client.close()
        sys.exit(1)

    print("\n 连接保持中，输入 'exit' 断开")
    try:
        while True:
            cmd = input("$ ").strip()
            if cmd.lower() in ("exit", "quit"):
                break
            if cmd:
                stdin, stdout, stderr = client.exec_command(cmd)
                print(stdout.read().decode().strip())
                err = stderr.read().decode().strip()
                if err:
                    print(f"⚠ {err}")
    except (EOFError, KeyboardInterrupt):
        pass
    finally:
        client.close()
        print("连接已断开")


if __name__ == "__main__":
    main()
