from django.apps import AppConfig


class IndexingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.indexing'
    verbose_name = 'Indexing'
    
    def ready(self):
        """Import signals when the app is ready"""
        import apps.indexing.signals