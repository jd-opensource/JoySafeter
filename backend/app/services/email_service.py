"""
邮件服务
"""

import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from app.core.settings import settings

logger = logging.getLogger(__name__)


class EmailService:
    """邮件服务"""

    def __init__(self):
        self.smtp_host = settings.smtp_host
        self.smtp_port = settings.smtp_port
        self.smtp_user = settings.smtp_user
        self.smtp_password = settings.smtp_password
        self.from_email = settings.from_email
        self.from_name = settings.from_name
        self.frontend_url = settings.frontend_url

        # 开发模式
        self.is_dev = settings.environment == "development"

    async def send_email(
        self,
        to_email: str,
        subject: str,
        html_content: str,
        text_content: Optional[str] = None,
    ) -> bool:
        """发送邮件"""
        if self.is_dev:
            # 开发模式下只打印日志
            logger.info(f"[DEV] Email to: {to_email}")
            logger.info(f"[DEV] Subject: {subject}")
            logger.info(f"[DEV] Content: {html_content[:200]}...")
            return True

        # 生产模式 - 使用 SMTP
        if not self.smtp_host or not self.smtp_user:
            logger.warning("SMTP not configured, email not sent")
            return False

        try:
            import aiosmtplib

            message = MIMEMultipart("alternative")
            message["Subject"] = subject
            message["From"] = f"{self.from_name} <{self.from_email}>"
            message["To"] = to_email

            if text_content:
                message.attach(MIMEText(text_content, "plain"))
            message.attach(MIMEText(html_content, "html"))

            await aiosmtplib.send(
                message,
                hostname=self.smtp_host,
                port=self.smtp_port,
                username=self.smtp_user,
                password=self.smtp_password,
                start_tls=True,
            )
            return True
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False

    async def send_password_reset_email(
        self,
        to_email: str,
        username: str,
        reset_token: str,
        frontend_url: Optional[str] = None,
    ) -> bool:
        """发送密码重置邮件"""
        url = frontend_url or self.frontend_url
        reset_link = f"{url}/reset-password?token={reset_token}"

        subject = "[JoySafeter] 密码重置请求"

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ text-align: center; padding: 20px 0; }}
                .logo {{ font-size: 24px; font-weight: bold; color: #4F46E5; }}
                .content {{ background: #f9fafb; border-radius: 8px; padding: 30px; margin: 20px 0; }}
                .button {{ display: inline-block; background: linear-gradient(to right, #4ade80, #3b82f6); color: white; padding: 12px 30px; text-decoration: none; border-radius: 8px; font-weight: 600; }}
                .footer {{ text-align: center; color: #6b7280; font-size: 12px; padding: 20px 0; }}
                .warning {{ color: #dc2626; font-size: 12px; margin-top: 20px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <div class="logo">🤖 JoySafeter</div>
                </div>
                <div class="content">
                    <h2>你好，{username}！</h2>
                    <p>我们收到了您的密码重置请求。点击下面的按钮重置您的密码：</p>
                    <p style="text-align: center; margin: 30px 0;">
                        <a href="{reset_link}" class="button">重置密码</a>
                    </p>
                    <p>或者复制以下链接到浏览器：</p>
                    <p style="word-break: break-all; color: #3b82f6;">{reset_link}</p>
                    <p class="warning">⚠️ 此链接将在 24 小时后过期。如果您没有请求重置密码，请忽略此邮件。</p>
                </div>
                <div class="footer">
                    <p>© {__import__("datetime").datetime.now().year} JoySafeter. All rights reserved.</p>
                    <p>这是一封自动发送的邮件，请勿回复。</p>
                </div>
            </div>
        </body>
        </html>
        """

        text_content = f"""
        你好，{username}！

        我们收到了您的密码重置请求。

        请点击以下链接重置您的密码：
        {reset_link}

        此链接将在 24 小时后过期。

        如果您没有请求重置密码，请忽略此邮件。

        ---
        JoySafeter Team
        """

        return await self.send_email(to_email, subject, html_content, text_content)

    async def send_email_verification(
        self,
        to_email: str,
        username: str,
        verify_token: str,
        frontend_url: Optional[str] = None,
    ) -> bool:
        """发送邮箱验证邮件"""
        url = frontend_url or self.frontend_url
        verify_link = f"{url}/verify-email?token={verify_token}"

        subject = "[JoySafeter] 验证您的邮箱"

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ text-align: center; padding: 20px 0; }}
                .logo {{ font-size: 24px; font-weight: bold; color: #4F46E5; }}
                .content {{ background: #f9fafb; border-radius: 8px; padding: 30px; margin: 20px 0; }}
                .button {{ display: inline-block; background: linear-gradient(to right, #4ade80, #3b82f6); color: white; padding: 12px 30px; text-decoration: none; border-radius: 8px; font-weight: 600; }}
                .footer {{ text-align: center; color: #6b7280; font-size: 12px; padding: 20px 0; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <div class="logo">🤖 JoySafeter</div>
                </div>
                <div class="content">
                    <h2>欢迎加入 JoySafeter！</h2>
                    <p>你好，{username}！感谢您注册 JoySafeter。请点击下面的按钮验证您的邮箱：</p>
                    <p style="text-align: center; margin: 30px 0;">
                        <a href="{verify_link}" class="button">验证邮箱</a>
                    </p>
                    <p>或者复制以下链接到浏览器：</p>
                    <p style="word-break: break-all; color: #3b82f6;">{verify_link}</p>
                    <p style="color: #6b7280; font-size: 12px; margin-top: 20px;">此链接将在 72 小时后过期。</p>
                </div>
                <div class="footer">
                    <p>© {__import__("datetime").datetime.now().year} JoySafeter. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """

        text_content = f"""
        欢迎加入 JoySafeter！

        你好，{username}！感谢您注册 JoySafeter。

        请点击以下链接验证您的邮箱：
        {verify_link}

        此链接将在 72 小时后过期。

        ---
        JoySafeter Team
        """

        return await self.send_email(to_email, subject, html_content, text_content)

    async def send_welcome_email(
        self,
        to_email: str,
        username: str,
    ) -> bool:
        """发送欢迎邮件"""
        subject = "[JoySafeter] 欢迎加入 JoySafeter！🎉"

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ text-align: center; padding: 20px 0; }}
                .logo {{ font-size: 24px; font-weight: bold; color: #4F46E5; }}
                .content {{ background: #f9fafb; border-radius: 8px; padding: 30px; margin: 20px 0; }}
                .feature {{ margin: 15px 0; padding: 10px; background: white; border-radius: 6px; }}
                .footer {{ text-align: center; color: #6b7280; font-size: 12px; padding: 20px 0; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <div class="logo">🤖 JoySafeter</div>
                </div>
                <div class="content">
                    <h2>🎉 欢迎加入 JoySafeter，{username}！</h2>
                    <p>您已成功创建账号。以下是您可以开始探索的功能：</p>
                    <div class="feature">🤖 <strong>AI 智能体</strong> - 自动化安全分析</div>
                    <div class="feature">🔒 <strong>安全扫描</strong> - 深度威胁检测</div>
                    <div class="feature">⚡ <strong>实时响应</strong> - 毫秒级告警</div>
                    <div class="feature">📊 <strong>可视化报告</strong> - 数据洞察分析</div>
                    <p>如有任何问题，请随时联系我们的支持团队。</p>
                </div>
                <div class="footer">
                    <p>© {__import__("datetime").datetime.now().year} JoySafeter. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """

        return await self.send_email(to_email, subject, html_content)


email_service = EmailService()
