"""Telugu receipts must render real Telugu glyphs, not tofu (invariant 7).

The receipt template asks for "Noto Sans" / "Noto Sans Telugu"; the prod
image (Dockerfile.prod) installs fonts-noto-core. The dev image doesn't, so
this test skips there unless REQUIRE_PDF_FONTS=1 — CI sets that when it runs
the suite inside the prod image, where a missing font must fail the build.
"""
import os
import re
import shutil
import subprocess
from unittest import skipUnless

from django.template.loader import render_to_string
from django.test import SimpleTestCase
from django.utils import translation


def _telugu_font_installed():
    if not shutil.which('fc-list'):
        return False
    result = subprocess.run(['fc-list', ':lang=te', 'family'], capture_output=True, text=True)
    return 'Noto Sans Telugu' in result.stdout


REQUIRED = os.environ.get('REQUIRE_PDF_FONTS') == '1'


@skipUnless(REQUIRED or _telugu_font_installed(), 'Telugu fonts not installed (dev image); CI checks the prod image')
class ReceiptPdfFontTests(SimpleTestCase):
    def test_telugu_receipt_embeds_noto_sans_telugu(self):
        from weasyprint import HTML

        with translation.override('te'):
            html = render_to_string('billing/receipt.html', {
                'language_code': 'te',
                'receipt_number': 'RCP-0001',
                'resident_name': 'రవి కుమార్',
                'property_name': 'శ్రీ సాయి పీజీ',
                'amount': '4500.00',
                'payment_mode_label': 'నగదు',
            })
        pdf = HTML(string=html).write_pdf(uncompressed_pdf=True)
        fonts = {name.decode() for name in re.findall(rb'/BaseFont\s*/[A-Z]{6}\+([A-Za-z0-9\-_]+)', pdf)}
        self.assertIn('Noto-Sans-Telugu', fonts)
