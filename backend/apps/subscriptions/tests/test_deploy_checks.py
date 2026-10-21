from django.test import SimpleTestCase, override_settings

from apps.subscriptions.checks import check_razorpay_settings

GOOD = {
    'RAZORPAY_KEY_ID': 'rzp_live_CIonlyNotReal00',
    'RAZORPAY_KEY_SECRET': 'a-real-looking-secret-0123456789',
    'RAZORPAY_WEBHOOK_SECRET': 'a-real-looking-webhook-secret-01',
    'RAZORPAY_ALLOW_UNSIGNED_WEBHOOKS': False,
}


def ids(**overrides):
    with override_settings(**{**GOOD, **overrides}):
        return [error.id for error in check_razorpay_settings(None)]


class RazorpayDeployCheckTests(SimpleTestCase):
    def test_valid_live_and_test_keys_pass(self):
        self.assertEqual(ids(), [])
        self.assertEqual(ids(RAZORPAY_KEY_ID='rzp_test_AbCdEfGhIjKlMn'), [])

    def test_a_missing_key_id_is_an_error(self):
        self.assertEqual(ids(RAZORPAY_KEY_ID=''), ['subscriptions.E001'])

    def test_a_malformed_key_id_is_an_error(self):
        for bad in ('rzp_prod_AbCdEfGhIjKlMn', 'rzp_live_short', 'AbCdEfGhIjKlMnOpQr', 'rzp_live_placeholder0000'):
            with self.subTest(key=bad):
                self.assertEqual(ids(RAZORPAY_KEY_ID=bad), ['subscriptions.E002'])

    def test_blank_or_placeholder_secrets_are_errors(self):
        self.assertEqual(ids(RAZORPAY_KEY_SECRET=''), ['subscriptions.E003'])
        self.assertEqual(ids(RAZORPAY_KEY_SECRET='placeholder'), ['subscriptions.E003'])
        self.assertEqual(ids(RAZORPAY_WEBHOOK_SECRET=''), ['subscriptions.E004'])
        self.assertEqual(ids(RAZORPAY_WEBHOOK_SECRET='CHANGEME-webhook'), ['subscriptions.E004'])

    def test_unsigned_webhooks_are_an_error(self):
        self.assertEqual(ids(RAZORPAY_ALLOW_UNSIGNED_WEBHOOKS=True), ['subscriptions.E005'])

    def test_everything_missing_reports_every_problem(self):
        self.assertEqual(
            ids(RAZORPAY_KEY_ID='', RAZORPAY_KEY_SECRET='', RAZORPAY_WEBHOOK_SECRET=''),
            ['subscriptions.E001', 'subscriptions.E003', 'subscriptions.E004'],
        )

    def test_the_check_only_runs_for_deploy_checks(self):
        from django.core.checks import registry

        deploy_checks = registry.registry.get_checks(include_deployment_checks=True)
        regular_checks = registry.registry.get_checks(include_deployment_checks=False)
        self.assertIn(check_razorpay_settings, deploy_checks)
        self.assertNotIn(check_razorpay_settings, regular_checks)
