from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

class Command(BaseCommand):
    help = 'Create a superuser with a password.'

    def add_arguments(self, parser):
        parser.add_argument('--username', type=str, help='Superuser username', default='admin')
        parser.add_argument('--password', type=str, help='Superuser password', default='admin')
        parser.add_argument('--email', type=str, help='Superuser email', default='admin@example.com')

    def handle(self, *args, **options):
        User = get_user_model()
        username = options['username']
        password = options['password']
        email = options['email']

        if not User.objects.filter(username=username).exists():
            User.objects.create_superuser(username=username, password=password, email=email)
            self.stdout.write(self.style.SUCCESS(f'Superuser {username} created successfully.'))
        else:
            self.stdout.write(self.style.WARNING(f'Superuser {username} already exists.'))
