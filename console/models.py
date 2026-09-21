"""Drugi faktor za konzolu. ADR-0010.

Tajna TOTP-a se NE čuva u bazi (Canon §2, §17): izvodi se iz
`HMAC(SECRET_KEY, korisnik:verzija)`. U bazi je samo verzija (za rotaciju),
da li je uključen, i poslednji iskorišćen korak (zabrana ponovne upotrebe koda).
"""

from __future__ import annotations

from django.conf import settings
from django.db import models


class OperatorTOTP(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name="console_totp")
    version = models.PositiveIntegerField(default=1)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    last_step = models.BigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "console_operator_totp"

    def __str__(self) -> str:
        return f"totp<{self.user_id}> v{self.version}"
