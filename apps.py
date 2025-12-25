from django.apps import AppConfig


class VerifactuConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'verifactu'
    verbose_name = 'Verifactu'

    def ready(self):
        # Import signals if needed
        pass
