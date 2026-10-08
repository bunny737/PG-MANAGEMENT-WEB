from django.core.management.base import BaseCommand

from apps.devices.models import AppVersionPolicy, Flavor, Platform

DEFAULT_ANDROID_STORE_URL = 'https://play.google.com/store/apps/details?id=com.pgmate.app'


class Command(BaseCommand):
    help = (
        'Create one AppVersionPolicy per platform and flavor (min_build=1, so nothing is '
        'force-updated). Existing rows are left untouched. Rollout step 2.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--latest-build', type=int, default=1, help='Current store release build number.')
        parser.add_argument('--latest-version', default='', help='Current store release version name.')
        parser.add_argument('--android-store-url', default=DEFAULT_ANDROID_STORE_URL)
        parser.add_argument('--ios-store-url', default='')

    def handle(self, *args, **options):
        store_urls = {Platform.ANDROID: options['android_store_url'], Platform.IOS: options['ios_store_url']}
        for platform in Platform.values:
            for flavor in Flavor.values:
                _, created = AppVersionPolicy.objects.get_or_create(
                    platform=platform, flavor=flavor,
                    defaults={
                        'min_build': 1,
                        'latest_build': max(options['latest_build'], 1),
                        'latest_version': options['latest_version'],
                        'store_url': store_urls[platform],
                    },
                )
                self.stdout.write(f'{platform}/{flavor}: {"created" if created else "exists"}')
