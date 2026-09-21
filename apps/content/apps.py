from django.apps import AppConfig


class ContentConfig(AppConfig):
    name = "apps.content"
    label = "content"

    def ready(self) -> None:
        # F7 (ADR-0009): status sadržaja prati status akcije objave.
        from apps.content import consumers  # noqa: F401
