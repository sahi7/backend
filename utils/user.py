# apps/users/utils.py
import asyncio
from django.core.mail import send_mail
from django.conf import settings
import resend
from django.template.loader import render_to_string
from django.core.mail import EmailMultiAlternatives
from typing import Dict

async def send_welcome_email(user, temp_password):
    context = {
        'full_name': user.get_full_name(),
        'email': user.email,
        'temp_password': temp_password,
        'school_name': 'GTHS Ekondo-TITI',
    }
    await send_templated_email(
        template_name='welcome',
        context=context,
        subject="Welcome Email",
        # to=[user.email]
        to=["indesignartsglobal@gmail.com"]
    )

resend.api_key = settings.RESEND_API_KEY

async def send_templated_email(
    template_name: str,
    context: Dict,
    subject: str = None,
    to: list = None,
    from_email: str = None,
):
    """
    Send HTML + plain-text email using Django templates
    """
    # Render templates
    html_content = render_to_string(f"emails/{template_name}.html", context)
    text_content = render_to_string(f"emails/{template_name}.txt", context)

    if not subject:
        subject = render_to_string(f"emails/{template_name}_subject.txt", context).strip()

    from_email = from_email or settings.DEFAULT_FROM_EMAIL
    to = to or [context.get('email')]

    print(f"Sending email FROM: {from_email} \nCONTEXT: {context}")

    # Build email
    email = EmailMultiAlternatives(
        subject=subject,
        body=text_content,
        from_email=from_email,
        to=to,
    )
    email.attach_alternative(html_content, "text/html")

    # Send async
    await asyncio.to_thread(email.send)