from typing import Any, Optional

import dotenv
import requests  # type: ignore[import-untyped]

dotenv.load_dotenv()


def http_request(
    url: str,
    method: str = "GET",
    headers: Optional[dict[str, str]] = None,
    data: Optional[str | dict[Any, Any]] = None,
    params: Optional[dict[str, str]] = None,
    timeout: int = 30,
) -> dict[str, Any]:
    """向API和Web服务发起HTTP请求。

    Args:
        url: 目标URL
        method: HTTP方法 (GET, POST, PUT, DELETE等)
        headers: 要包含的HTTP头
        data: 请求体数据 (字符串或字典)
        params: URL查询参数
        timeout: 请求超时时间（秒）

    Returns:
        包含响应数据的字典，包括状态、头和内容
    """
    try:
        kwargs: dict[str, Any] = {
            "url": url,
            "method": method.upper(),
            "timeout": timeout,
        }

        if headers:
            kwargs["headers"] = headers
        if params:
            kwargs["params"] = params
        if data:
            if isinstance(data, dict):
                kwargs["json"] = data
            else:
                kwargs["data"] = data

        response = requests.request(**kwargs)

        try:
            content = response.json()
        except (ValueError, AttributeError):
            content = response.text

        return {
            "success": response.status_code < 400,
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "content": content,
            "url": response.url,
        }

    except requests.exceptions.Timeout:
        return {
            "success": False,
            "status_code": 0,
            "headers": {},
            "content": f"Request timed out after {timeout} seconds",
            "url": url,
        }
    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "status_code": 0,
            "headers": {},
            "content": f"Request error: {e!s}",
            "url": url,
        }
    except Exception as e:
        return {
            "success": False,
            "status_code": 0,
            "headers": {},
            "content": f"Error making request: {e!s}",
            "url": url,
        }
