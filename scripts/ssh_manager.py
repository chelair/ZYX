"""
SSH 连接管理器 — 共享 SSH 连接，避免重复创建

在同一 Python 进程内，对同一 {host, port, username} 复用已有连接，
自动健康检查（连接断开后重建）。

用法:
    from ssh_manager import SSHManager

    mgr = SSHManager()
    client = mgr.get(hostname, port, username, key_path)
    # ... 使用 client 执行多个操作 ...
    mgr.close()  # 清理全部

    # 上下文管理器方式（推荐）:
    with SSHManager() as mgr:
        client = mgr.get(hostname, port, username, key_path)
        # ...
"""
from ssh_connect import create_ssh_client


class SSHManagerError(Exception):
    """SSH 连接管理器异常"""
    pass


class SSHManager:
    """SSH 连接管理器

    内部维护 _connections: dict[key, client]
    key = (hostname, port, username)
    """

    def __init__(self):
        self._connections = {}

    def _key(self, hostname, port, username):
        return (hostname, port, username)

    def get(self, hostname, port, username, key_path, password=None, timeout=15):
        """获取 SSH 连接。已有连接且健康则复用，否则新建。

        Args:
            hostname: 服务器地址
            port: SSH 端口
            username: 用户名
            key_path: 私钥路径
            password: 密码（可选）
            timeout: 连接超时秒数

        Returns:
            paramiko.SSHClient
        """
        key = self._key(hostname, port, username)

        # 检查已有连接是否可用
        if key in self._connections:
            client = self._connections[key]
            if self._is_alive(client):
                return client
            else:
                # 连接已断开，清理
                try:
                    client.close()
                except Exception:
                    pass
                del self._connections[key]

        # 创建新连接
        client = create_ssh_client(hostname, port, username, key_path, password, timeout)
        if client is None:
            raise SSHManagerError(f"无法连接到 {username}@{hostname}:{port}")

        self._connections[key] = client
        return client

    def get_parsed(self, host, port, key_path, password=None, timeout=15):
        """解析 user@host 格式后连接

        Args:
            host: "user@host" 格式字符串
            port: SSH 端口
            key_path: 私钥路径
            password: 密码（可选）
            timeout: 连接超时

        Returns:
            (username, hostname, client)
        """
        from ssh_connect import parse_host
        username, hostname = parse_host(host)
        client = self.get(hostname, port, username, key_path, password, timeout)
        return username, hostname, client

    def _is_alive(self, client, timeout=5):
        """检查 SSH 连接是否存活"""
        try:
            client.exec_command("echo alive", timeout=timeout)
            return True
        except Exception:
            return False

    def close(self, hostname=None, port=None, username=None):
        """关闭连接

        Args:
            hostname/port/username: 指定关闭某个连接
                                  全不指定则关闭所有
        """
        if hostname is not None:
            key = self._key(hostname, port, username)
            if key in self._connections:
                try:
                    self._connections[key].close()
                except Exception:
                    pass
                del self._connections[key]
        else:
            for key, client in self._connections.items():
                try:
                    client.close()
                except Exception:
                    pass
            self._connections.clear()

    def close_all(self):
        """关闭所有连接（同 close()）"""
        self.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close_all()
        return False  # 不吞异常