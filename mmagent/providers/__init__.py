"""providers 包：按协议抽象的模型 Provider 层（v0.3 完成五个协议适配）。"""


def redact_secret(text: str, secret: str, placeholder: str = "***REDACTED***") -> str:
    """从文本中移除密钥（错误消息/日志统一出口）。"""
    if not secret:
        return text
    return text.replace(secret, placeholder)
