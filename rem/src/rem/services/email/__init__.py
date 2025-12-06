"""
Email Service Module.

Provides EmailService for sending transactional emails and passwordless login.
"""

from .service import EmailService
from .templates import EmailTemplate, login_code_template

__all__ = ["EmailService", "EmailTemplate", "login_code_template"]
