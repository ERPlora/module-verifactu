from django.apps import AppConfig


class VerifactuConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "verifactu"
    verbose_name = "Verifactu"

    def ready(self):
        pass

    @staticmethod
    def do_before_record_submit(record) -> dict:
        """Called before submitting a record."""
        return {"allow": True}

    @staticmethod
    def do_after_record_submit(record) -> None:
        """Called after record is submitted."""
        pass

    @staticmethod
    def do_after_record_cancel(record) -> None:
        """Called after record is cancelled."""
        pass

    @staticmethod
    def filter_records_list(queryset, request):
        """Filter records queryset."""
        return queryset
