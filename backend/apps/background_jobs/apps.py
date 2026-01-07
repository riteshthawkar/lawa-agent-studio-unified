from django.apps import AppConfig


class BackgroundJobsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.background_jobs'
    verbose_name = 'Background Jobs'
