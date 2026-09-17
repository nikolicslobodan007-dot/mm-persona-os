"""Razvojna podešavanja. F0: baza nije obavezna za testove common/ sloja."""

from config.settings.base import *  # noqa: F401,F403

DEBUG = True
ALLOWED_HOSTS = ["*"]
