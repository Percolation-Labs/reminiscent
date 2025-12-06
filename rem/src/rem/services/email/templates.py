"""
Email Templates.

HTML email templates for transactional emails.
Uses inline CSS for maximum email client compatibility.

Downstream apps can customize by:
1. Overriding COLORS dict
2. Setting custom LOGO_URL and TAGLINE
3. Creating custom templates using base_template()
"""

from dataclasses import dataclass
from typing import Optional


# Default colors - override in downstream apps
COLORS = {
    "background": "#F5F5F5",
    "foreground": "#333333",
    "primary": "#4A90D9",
    "accent": "#5CB85C",
    "card": "#FFFFFF",
    "muted": "#6b7280",
    "border": "#E0E0E0",
}

# Branding - override in downstream apps
LOGO_URL: str | None = None
APP_NAME = "REM"
TAGLINE = "Your AI-powered platform"
WEBSITE_URL = "https://rem.ai"
PRIVACY_URL = "https://rem.ai/privacy"
TERMS_URL = "https://rem.ai/terms"


@dataclass
class EmailTemplate:
    """Email template with subject and HTML body."""

    subject: str
    html_body: str


def base_template(
    content: str,
    preheader: Optional[str] = None,
    colors: dict | None = None,
    logo_url: str | None = None,
    app_name: str | None = None,
    tagline: str | None = None,
    website_url: str | None = None,
    privacy_url: str | None = None,
    terms_url: str | None = None,
) -> str:
    """
    Base email template.

    Args:
        content: The main content HTML
        preheader: Optional preview text shown in email clients
        colors: Color overrides (merges with COLORS)
        logo_url: Logo image URL
        app_name: Application name
        tagline: Footer tagline
        website_url: Main website URL
        privacy_url: Privacy policy URL
        terms_url: Terms of service URL

    Returns:
        Complete HTML email
    """
    # Merge colors
    c = {**COLORS, **(colors or {})}

    # Use provided values or module defaults
    logo = logo_url or LOGO_URL
    name = app_name or APP_NAME
    tag = tagline or TAGLINE
    web = website_url or WEBSITE_URL
    privacy = privacy_url or PRIVACY_URL
    terms = terms_url or TERMS_URL

    preheader_html = ""
    if preheader:
        preheader_html = f'''
        <div style="display: none; max-height: 0; overflow: hidden;">
            {preheader}
        </div>
        '''

    logo_html = ""
    if logo:
        logo_html = f'''
            <img src="{logo}" alt="{name}" width="40" height="40" style="display: block; margin: 0 auto 16px auto; border-radius: 8px;">
        '''

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="X-UA-Compatible" content="IE=edge">
    <title>{name}</title>
    <!--[if mso]>
    <style type="text/css">
        body, table, td {{font-family: Arial, sans-serif !important;}}
    </style>
    <![endif]-->
</head>
<body style="margin: 0; padding: 0; background-color: {c['background']}; font-family: 'Georgia', 'Times New Roman', serif;">
    {preheader_html}

    <!-- Email Container -->
    <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="background-color: {c['background']};">
        <tr>
            <td style="padding: 40px 20px;">
                <!-- Inner Container -->
                <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="max-width: 560px; margin: 0 auto;">

                    <!-- Main Content Card -->
                    <tr>
                        <td style="background-color: {c['card']}; border-radius: 16px; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05);">
                            <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%">
                                <tr>
                                    <td style="padding: 40px;">
                                        {content}
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>

                    <!-- Footer -->
                    <tr>
                        <td style="padding: 32px 20px; text-align: center;">
                            {logo_html}

                            <!-- Tagline -->
                            <p style="margin: 0 0 8px 0; font-family: 'Georgia', serif; font-size: 14px; color: {c['muted']}; font-style: italic;">
                                {tag}
                            </p>

                            <!-- Footer Links -->
                            <p style="margin: 0; font-family: Arial, sans-serif; font-size: 12px; color: {c['muted']};">
                                <a href="{web}" style="color: {c['primary']}; text-decoration: none;">{name}</a>
                                &nbsp;&bull;&nbsp;
                                <a href="{privacy}" style="color: {c['primary']}; text-decoration: none;">Privacy</a>
                                &nbsp;&bull;&nbsp;
                                <a href="{terms}" style="color: {c['primary']}; text-decoration: none;">Terms</a>
                            </p>

                            <!-- Copyright -->
                            <p style="margin: 16px 0 0 0; font-family: Arial, sans-serif; font-size: 11px; color: {c['muted']};">
                                &copy; 2025 {name}. All rights reserved.
                            </p>
                        </td>
                    </tr>

                </table>
            </td>
        </tr>
    </table>
</body>
</html>'''


def login_code_template(
    code: str,
    email: str,
    colors: dict | None = None,
    app_name: str | None = None,
    **kwargs,
) -> EmailTemplate:
    """
    Generate a login code email template.

    Args:
        code: The 6-digit login code
        email: The recipient's email address
        colors: Color overrides
        app_name: Application name
        **kwargs: Additional arguments passed to base_template

    Returns:
        EmailTemplate with subject and HTML body
    """
    c = {**COLORS, **(colors or {})}
    name = app_name or APP_NAME

    # Format code with spaces for readability (e.g., "123 456")
    formatted_code = f"{code[:3]} {code[3:]}" if len(code) == 6 else code

    content = f'''
        <!-- Greeting -->
        <h1 style="margin: 0 0 8px 0; font-family: 'Arial', sans-serif; font-size: 24px; font-weight: 600; color: {c['foreground']};">
            Hi there!
        </h1>

        <p style="margin: 0 0 24px 0; font-family: 'Georgia', serif; font-size: 16px; line-height: 1.6; color: {c['foreground']};">
            Here's your login code for {name}. Enter this code to securely access your account.
        </p>

        <!-- Code Box -->
        <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="margin: 0 0 24px 0;">
            <tr>
                <td align="center">
                    <div style="
                        display: inline-block;
                        padding: 20px 40px;
                        background-color: {c['background']};
                        border: 2px solid {c['border']};
                        border-radius: 12px;
                    ">
                        <span style="
                            font-family: 'Courier New', monospace;
                            font-size: 32px;
                            font-weight: 700;
                            letter-spacing: 6px;
                            color: {c['foreground']};
                        ">{formatted_code}</span>
                    </div>
                </td>
            </tr>
        </table>

        <!-- Instructions -->
        <p style="margin: 0 0 8px 0; font-family: 'Georgia', serif; font-size: 14px; line-height: 1.6; color: {c['muted']};">
            This code expires in <strong>10 minutes</strong>.
        </p>

        <p style="margin: 0 0 24px 0; font-family: 'Georgia', serif; font-size: 14px; line-height: 1.6; color: {c['muted']};">
            If you didn't request this code, you can safely ignore this email.
        </p>

        <!-- Divider -->
        <hr style="border: none; border-top: 1px solid {c['border']}; margin: 24px 0;">

        <!-- Security Note -->
        <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%">
            <tr>
                <td style="padding: 16px; background-color: {c['background']}; border-radius: 8px;">
                    <p style="margin: 0; font-family: Arial, sans-serif; font-size: 12px; color: {c['muted']};">
                        <strong style="color: {c['primary']};">Security tip:</strong>
                        Never share your login code with anyone. {name} will never ask for your code via phone or text.
                    </p>
                </td>
            </tr>
        </table>
    '''

    return EmailTemplate(
        subject=f"Your {name} Login Code",
        html_body=base_template(
            content=content,
            preheader=f"Your login code is {formatted_code}",
            colors=colors,
            app_name=app_name,
            **kwargs,
        ),
    )


def welcome_template(
    name: Optional[str] = None,
    colors: dict | None = None,
    app_name: str | None = None,
    features: list[str] | None = None,
    cta_url: str | None = None,
    cta_text: str = "Get Started",
    **kwargs,
) -> EmailTemplate:
    """
    Generate a welcome email template for new users.

    Args:
        name: Optional user's name
        colors: Color overrides
        app_name: Application name
        features: List of feature descriptions
        cta_url: Call-to-action button URL
        cta_text: Call-to-action button text
        **kwargs: Additional arguments passed to base_template

    Returns:
        EmailTemplate with subject and HTML body
    """
    c = {**COLORS, **(colors or {})}
    app = app_name or APP_NAME
    greeting = f"Hi {name}!" if name else "Welcome!"
    url = cta_url or WEBSITE_URL

    # Default features if not provided
    default_features = [
        "Access powerful AI capabilities",
        "Store and organize your data",
        "Collaborate with your team",
    ]
    feature_list = features or default_features

    features_html = "".join(f"<li>{f}</li>" for f in feature_list)

    content = f'''
        <!-- Greeting -->
        <h1 style="margin: 0 0 8px 0; font-family: 'Arial', sans-serif; font-size: 24px; font-weight: 600; color: {c['foreground']};">
            {greeting}
        </h1>

        <p style="margin: 0 0 24px 0; font-family: 'Georgia', serif; font-size: 16px; line-height: 1.6; color: {c['foreground']};">
            Welcome to {app}! We're excited to have you on board.
        </p>

        <!-- Feature List -->
        <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="margin: 0 0 24px 0;">
            <tr>
                <td style="padding: 16px; background-color: {c['background']}; border-radius: 8px;">
                    <p style="margin: 0 0 12px 0; font-family: Arial, sans-serif; font-size: 14px; font-weight: 600; color: {c['primary']};">
                        What you can do with {app}:
                    </p>
                    <ul style="margin: 0; padding-left: 20px; font-family: 'Georgia', serif; font-size: 14px; line-height: 1.8; color: {c['foreground']};">
                        {features_html}
                    </ul>
                </td>
            </tr>
        </table>

        <!-- CTA Button -->
        <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="margin: 0 0 24px 0;">
            <tr>
                <td align="center">
                    <a href="{url}" style="
                        display: inline-block;
                        padding: 14px 32px;
                        background-color: {c['primary']};
                        color: #FFFFFF;
                        font-family: Arial, sans-serif;
                        font-size: 16px;
                        font-weight: 600;
                        text-decoration: none;
                        border-radius: 8px;
                    ">{cta_text}</a>
                </td>
            </tr>
        </table>

        <p style="margin: 0; font-family: 'Georgia', serif; font-size: 14px; line-height: 1.6; color: {c['muted']}; text-align: center;">
            We're glad you're here!
        </p>
    '''

    return EmailTemplate(
        subject=f"Welcome to {app}",
        html_body=base_template(
            content=content,
            preheader=f"Welcome to {app}! Get started today.",
            colors=colors,
            app_name=app_name,
            **kwargs,
        ),
    )
