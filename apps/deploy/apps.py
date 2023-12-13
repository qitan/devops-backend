from django.apps import AppConfig


class DeployConfig(AppConfig):
    name = 'deploy'

    def ready(self):
        import deploy.signals
