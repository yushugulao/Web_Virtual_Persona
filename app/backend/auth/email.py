from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

from app.backend.core.config import Settings


class EmailConfigurationError(RuntimeError):
    pass


def assert_smtp_configured(settings: Settings) -> None:
    missing = [
        name
        for name, value in {
            "PERSONA_RAG_SMTP_HOST": settings.smtp_host,
            "PERSONA_RAG_SMTP_USERNAME": settings.smtp_username,
            "PERSONA_RAG_SMTP_PASSWORD": settings.smtp_password,
            "PERSONA_RAG_SMTP_FROM": settings.smtp_from,
        }.items()
        if not value
    ]
    if missing:
        raise EmailConfigurationError("SMTP 配置不完整，缺少：" + ", ".join(missing))


def send_verification_email(settings: Settings, recipient: str, code: str) -> None:
    assert_smtp_configured(settings)
    message = EmailMessage()
    sender = settings.smtp_from or settings.smtp_username
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = "Persona-RAG 注册验证码"
    message.set_content(
        "\n".join(
            [
                "你好，",
                "",
                f"你的 Persona-RAG 注册验证码是：{code}",
                f"验证码将在 {settings.email_verification_ttl_minutes} 分钟后失效。",
                "",
                "如果不是你在本地 Persona-RAG 项目中发起注册，可以忽略这封邮件。",
            ]
        )
    )

    security = settings.smtp_security.lower().strip()
    if security == "ssl":
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=context, timeout=15) as smtp:
            smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)
        return

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
        if security == "starttls":
            smtp.starttls(context=ssl.create_default_context())
        elif security != "plain":
            raise EmailConfigurationError(f"不支持的 SMTP 安全模式：{settings.smtp_security}")
        smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(message)

