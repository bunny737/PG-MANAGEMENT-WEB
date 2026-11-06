"""Module 23: the tutorial video catalog — language resolution, role audience,
and Super-Admin-only administration."""
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.core.roles import Role
from apps.core.tenancy import tenant_context
from apps.onboarding.models import TutorialVideo

from .base import OnboardingAPITestCase


def make_video(topic='add_property', language='en', **kwargs):
    kwargs.setdefault('title', f'{topic} ({language})')
    kwargs.setdefault('youtube_id', 'dQw4w9WgXcQ')
    return TutorialVideo.objects.create(topic=topic, language=language, **kwargs)


class VideoListTests(OnboardingAPITestCase):
    def setUp(self):
        super().setUp()
        self.tenant = self.create_tenant()
        self.owner = self.create_owner(self.tenant, language_code='te')
        self.authenticate(self.owner)

    def videos(self, expected_status=200, **params):
        response = self.client.get(reverse('help-videos'), params)
        self.assertEqual(response.status_code, expected_status, getattr(response, 'data', None))
        return response

    def test_requested_language_wins_and_english_fills_gaps(self):
        make_video('add_property', 'en')
        make_video('add_property', 'te', youtube_id='tttttttttte')
        make_video('add_floor', 'en', youtube_id='eeeeeeeeeee')
        response = self.videos()  # defaults to the user's language, te
        self.assertEqual(response['Cache-Control'], 'private, max-age=300')
        data = response.data
        self.assertEqual(data['requested_language'], 'te')
        by_topic = {video['topic']: video for video in data['videos']}
        self.assertEqual(by_topic['add_property']['language'], 'te')
        self.assertEqual(by_topic['add_property']['youtube_id'], 'tttttttttte')
        self.assertEqual(by_topic['add_floor']['language'], 'en')  # fallback the client labels

    def test_never_a_third_language(self):
        make_video('add_property', 'hi')
        self.assertEqual(self.videos().data['videos'], [])
        self.owner.tenant.default_language = 'hi'
        self.owner.tenant.save()
        self.assertEqual(self.videos().data['videos'], [])

    def test_explicit_language_and_validation(self):
        make_video('add_property', 'en')
        make_video('add_property', 'te', youtube_id='tttttttttte')
        self.assertEqual(self.videos(language='en').data['videos'][0]['language'], 'en')
        self.assertIn('language', self.videos(language='xx', expected_status=400).data)

    def test_audience_filter_runs_before_language_fallback(self):
        make_video('add_property', 'te', youtube_id='tttttttttte', audience=['owner'])
        make_video('add_property', 'en')
        self.assertEqual(self.videos().data['videos'][0]['language'], 'te')  # owner sees te

        manager = self.create_manager(self.tenant, language_code='te')
        self.authenticate(manager)
        videos = self.videos().data['videos']
        self.assertEqual(len(videos), 1)
        self.assertEqual(videos[0]['language'], 'en')  # te is owner-only; en still reaches the manager

    def test_inactive_hidden_and_ordering(self):
        make_video('add_floor', 'te', sort_order=2, youtube_id='bbbbbbbbbbb')
        make_video('add_property', 'te', sort_order=1)
        make_video('overview', 'te', is_active=False)
        self.assertEqual([v['topic'] for v in self.videos().data['videos']], ['add_property', 'add_floor'])

    def test_available_languages_follow_the_catalog_not_the_ui(self):
        make_video('add_property', 'en')
        make_video('add_property', 'hi', youtube_id='hhhhhhhhhhh')        # Hindi UI isn't live yet
        make_video('add_floor', 'ta', youtube_id='ttttttttttt', is_active=False)
        make_video('add_floor', 'ml', youtube_id='mmmmmmmmmmm', audience=['manager'])
        self.assertEqual(self.videos().data['available_languages'], ['en', 'hi'])
        data = self.videos(language='hi').data
        self.assertEqual([v['language'] for v in data['videos']], ['hi'])

    def test_no_write_methods(self):
        self.assertEqual(self.client.post(reverse('help-videos'), {}).status_code, 405)


class TutorialVideoAdminTests(OnboardingAPITestCase):
    def setUp(self):
        super().setUp()
        self.admin_user = User.objects.create_superuser(
            email='root@example.com', password='x', first_name='Root',
        )
        self.admin_client = Client()
        self.admin_client.force_login(self.admin_user)

    def test_super_admin_can_manage_and_changes_are_audited(self):
        self.assertEqual(self.admin_client.get(reverse('admin:onboarding_tutorialvideo_changelist')).status_code, 200)
        self.assertEqual(self.admin_client.get(reverse('admin:onboarding_tutorialvideo_add')).status_code, 200)
        response = self.admin_client.post(reverse('admin:onboarding_tutorialvideo_add'), {
            'topic': 'add_room', 'language': 'te', 'title': 'గదులు', 'description': '',
            'youtube_id': 'abcdefghijk', 'duration_seconds': '120', 'sort_order': '3',
            'is_active': 'on', 'audience': '["owner", "manager"]',
        })
        self.assertEqual(response.status_code, 302, getattr(response, 'context', None) and
                         response.context['adminform'].form.errors)
        video = TutorialVideo.objects.get(topic='add_room', language='te')
        self.assertEqual(video.updated_by, self.admin_user)
        with tenant_context(None, is_super_admin=True):
            self.assertTrue(AuditLog.objects.filter(action='tutorial_video.created', object_id=str(video.pk)).exists())

    def test_admin_rejects_bad_youtube_id_and_audience(self):
        response = self.admin_client.post(reverse('admin:onboarding_tutorialvideo_add'), {
            'topic': 'add_room', 'language': 'en', 'title': 'Rooms', 'youtube_id': 'https://youtu',
            'sort_order': '0', 'audience': '["resident"]',
        })
        self.assertEqual(response.status_code, 200)
        errors = response.context['adminform'].form.errors
        self.assertIn('youtube_id', errors)
        self.assertIn('audience', errors)
        self.assertFalse(TutorialVideo.objects.exists())

    def test_tenant_owner_cannot_open_the_admin(self):
        owner = self.create_owner(self.create_tenant())
        client = Client()
        client.force_login(owner)
        response = client.get(reverse('admin:onboarding_tutorialvideo_changelist'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/admin/login/', response['Location'])
        self.assertNotEqual(owner.role, Role.SUPER_ADMIN)
