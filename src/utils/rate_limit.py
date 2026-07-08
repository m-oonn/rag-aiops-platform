"""安全最佳实践: 速率限制器单例。

独立模块避免 main.py ↔ auth.py 之间的循环导入。
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

# 基于客户端 IP 的速率限制器，用于防止暴力破解登录等
limiter = Limiter(key_func=get_remote_address)
