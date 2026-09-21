from django.apps import AppConfig


class ObservabilityConfig(AppConfig):
    name = "apps.observability"
    label = "observability"

    def ready(self) -> None:
        # Registracija potrošača eventa (ADR-0004). Uvoz ima sporedni efekat
        # namerno: potrošač postoji čim postoji aplikacija, bez ručnog koraka.
        from apps.observability import consumers  # noqa: F401
