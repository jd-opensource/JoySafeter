"""
凭据加密/解密工具
"""

import base64
import json
from typing import Any, Dict

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from app.core.settings import settings


class CredentialEncryption:
    """凭据加密类"""

    def __init__(self, key: str | None = None):
        """
        初始化加密器

        Args:
            key: 加密密钥，如果为None则从settings获取或生成
        """
        if key is None:
            # 从settings获取密钥，如果没有则使用默认密钥（生产环境应该从环境变量获取）
            key = getattr(settings, "credential_encryption_key", None)
            if key is None:
                # 生成一个默认密钥（仅用于开发环境）
                key = Fernet.generate_key().decode()

        if isinstance(key, str):
            key_bytes = key.encode()
        else:
            key_bytes = key

        # 如果密钥不是Fernet格式，使用PBKDF2派生
        try:
            self.fernet = Fernet(key_bytes)
        except ValueError:
            # 密钥不是Fernet格式，使用PBKDF2派生
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=b"credential_salt",  # 生产环境应该使用随机salt
                iterations=100000,
            )
            key_bytes = base64.urlsafe_b64encode(kdf.derive(key_bytes))
            self.fernet = Fernet(key_bytes)

    def encrypt(self, data: Dict[str, Any]) -> str:
        """
        加密凭据数据

        Args:
            data: 要加密的凭据字典

        Returns:
            加密后的字符串（base64编码）
        """
        json_str = json.dumps(data, ensure_ascii=False)
        encrypted = self.fernet.encrypt(json_str.encode())
        return base64.urlsafe_b64encode(encrypted).decode()

    def decrypt(self, encrypted_data: str) -> Dict[str, Any]:
        """
        解密凭据数据

        Args:
            encrypted_data: 加密后的字符串（base64编码）

        Returns:
            解密后的凭据字典
        """
        encrypted_bytes = base64.urlsafe_b64decode(encrypted_data.encode())
        decrypted_bytes = self.fernet.decrypt(encrypted_bytes)
        result = json.loads(decrypted_bytes.decode())
        return result if isinstance(result, dict) else {}


# 全局加密器实例
_default_encryption = None


def get_encryption() -> CredentialEncryption:
    """获取全局加密器实例"""
    global _default_encryption
    if _default_encryption is None:
        _default_encryption = CredentialEncryption()
    return _default_encryption


def encrypt_credentials(credentials: Dict[str, Any], key: str | None = None) -> str:
    """
    加密凭据

    Args:
        credentials: 凭据字典
        key: 加密密钥，如果为None则使用默认密钥

    Returns:
        加密后的字符串
    """
    encryption = CredentialEncryption(key) if key else get_encryption()
    return encryption.encrypt(credentials)


def decrypt_credentials(encrypted_data: str, key: str | None = None) -> Dict[str, Any]:
    """
    解密凭据

    Args:
        encrypted_data: 加密后的字符串
        key: 加密密钥，如果为None则使用默认密钥

    Returns:
        解密后的凭据字典
    """
    encryption = CredentialEncryption(key) if key else get_encryption()
    return encryption.decrypt(encrypted_data)
