#!/usr/bin/env python3
"""
本地 Mock OAuth 服务器 - 用于本地验证 OAuth 登录流程

仅使用 Python 标准库，无需额外依赖。

使用步骤：
  1. 启动本脚本：python backend/scripts/mock_oauth_server.py
  2. 在 backend/config/oauth_providers.yaml 中启用 local 提供商（enabled: true）
  3. 设置环境变量：
     export OAUTH_LOCAL_CLIENT_ID=local-client
     export OAUTH_LOCAL_CLIENT_SECRET=local-secret
  4. 启动后端，在前端点击「本地测试」登录

回调 URL 需为后端地址，例如：http://localhost:8000/api/v1/auth/oauth/local/callback
（由后端根据 request.base_url 自动生成，无需在 mock 中配置）
"""

import base64
import json
import secrets
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

# 内存存储：授权码 -> { redirect_uri, state }；access_token -> True
_codes: dict = {}
_tokens: dict = {}

# Mock 用户信息（可改）
MOCK_USER = {
    "sub": "local-user-1",
    "email": "local@test.com",
    "name": "Local User",
    "picture": "",
}

# 接受的 client_id / client_secret（与 oauth_providers.yaml 中一致）
EXPECTED_CLIENT_ID = "local-client"
EXPECTED_CLIENT_SECRET = "local-secret"


class MockOAuthHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"[MockOAuth] {args[0]}")

    def _redirect(self, location: str):
        self.send_response(302)
        self.send_header("Location", location)
        self.end_headers()

    def _json(self, data: dict, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def _read_form(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        body = self.rfile.read(length).decode("utf-8")
        return parse_qs(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/authorize":
            q = parse_qs(parsed.query)
            redirect_uri = (q.get("redirect_uri") or [""])[0]
            state = (q.get("state") or [""])[0]
            if not redirect_uri:
                self._json({"error": "redirect_uri required"}, 400)
                return
            code = secrets.token_urlsafe(16)
            _codes[code] = {"redirect_uri": redirect_uri, "state": state}
            sep = "&" if "?" in redirect_uri else "?"
            self._redirect(f"{redirect_uri}{sep}code={code}&state={state}")

        elif path == "/userinfo":
            auth = self.headers.get("Authorization")
            if not auth or not auth.startswith("Bearer "):
                self._json({"error": "unauthorized"}, 401)
                return
            token = auth[7:]
            if not token.startswith("mock_") or token not in _tokens:
                self._json({"error": "invalid token"}, 401)
                return
            self._json(MOCK_USER)

        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/token":
            data = self._read_form()

            def _get(key: str, default: str = "") -> str:
                v = data.get(key, default)
                return (v[0] if isinstance(v, list) else v) or default

            code = _get("code")
            redirect_uri = _get("redirect_uri")

            # 支持 client_secret_basic（后端默认）：Authorization: Basic base64(client_id:client_secret)
            client_id = _get("client_id")
            client_secret = _get("client_secret")
            if not client_id or not client_secret:
                auth = self.headers.get("Authorization")
                if auth and auth.startswith("Basic "):
                    try:
                        decoded = base64.b64decode(auth[6:].strip()).decode("utf-8")
                        client_id, _, client_secret = decoded.partition(":")
                    except Exception:
                        pass

            if code not in _codes:
                self._json({"error": "invalid_grant", "error_description": "invalid code"}, 400)
                return
            if _codes[code]["redirect_uri"] != redirect_uri:
                self._json({"error": "invalid_grant", "error_description": "redirect_uri mismatch"}, 400)
                return
            if client_id != EXPECTED_CLIENT_ID or client_secret != EXPECTED_CLIENT_SECRET:
                self._json({"error": "invalid_client"}, 401)
                return

            _codes.pop(code)
            access_token = "mock_" + secrets.token_urlsafe(16)
            _tokens[access_token] = True

            self._json({"access_token": access_token, "token_type": "Bearer"})
        else:
            self._json({"error": "not found"}, 404)


def main():
    port = 9090
    server = HTTPServer(("", port), MockOAuthHandler)
    print(f"Mock OAuth server: http://localhost:{port}")
    print("  GET /authorize  -> 重定向到 redirect_uri?code=...&state=...")
    print("  POST /token     -> 返回 access_token")
    print("  GET /userinfo   -> 返回用户信息 (Bearer token)")
    print("Client ID / Secret: local-client / local-secret")
    print("Ctrl+C 退出")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
