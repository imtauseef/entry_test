# -*- coding: utf-8 -*-
"""Word (.doc) export of the CBT QWeb reports (Odoo 17).

The same QWeb template that produces the PDF is rendered to HTML and handed to
MS Word as a ``.doc`` (``Content-Type: application/msword``). Word opens the
HTML as a document, so the table / font / logo design is kept without a
separate Word template.

The HTML is only patched in-place (Office namespaces, A4 page setup, Word
section, page fields, absolute URLs). It is not re-parsed or wrapped in
MHTML: those steps made Word print tags and meta as text.
"""
import logging
import re
import time

from werkzeug.exceptions import BadRequest, NotFound

from odoo import _, http
from odoo.exceptions import AccessError, MissingError
from odoo.http import content_disposition, request
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)

_ALLOWED_REPORT_TYPES = ('qweb-pdf', 'qweb-html')
_MAX_RECORDS = 500

_MSO_NS = (
    'xmlns:o="urn:schemas-microsoft-com:office:office" '
    'xmlns:w="urn:schemas-microsoft-com:office:word" '
    'xmlns:m="http://schemas.microsoft.com/office/2004/12/omml" '
    'xmlns="http://www.w3.org/TR/REC-html40"'
)

_PAGE_FIELD = (
    '<span style=\'mso-field-code:" PAGE "\'>'
    '<span style=\'mso-no-proof:yes\'>1</span></span>'
)
_NUMPAGES_FIELD = (
    '<span style=\'mso-field-code:" NUMPAGES "\'>'
    '<span style=\'mso-no-proof:yes\'>1</span></span>'
)

# A4 page setup + Word-friendly styling for the in-flow header/footer.  These
# rules are injected at the end of <head> so they win over the report assets.
# Word only understands a subset of CSS: simple class selectors, tables,
# borders and page-break-* work; flex/grid and max-* do not.
_WORD_STYLE = (
    '<style>'
    '@page WordSection1 {'
    '  size: 21.0cm 29.7cm;'
    '  margin: 2.2cm 1.4cm 2.0cm 1.4cm;'
    '  mso-header-margin: 0.6cm;'
    '  mso-footer-margin: 0.6cm;'
    '  mso-paper-source: 0;'
    '}'
    'div.WordSection1 { page: WordSection1; }'
    'body {'
    '  font-family: "Lato", "Segoe UI", "Noto Sans", Arial, sans-serif;'
    '  font-size: 10.5pt; color: #111111; line-height: 1.35;'
    '  margin: 0 !important; padding: 0 !important;'
    '  mso-pagination: widow-orphan;'
    '}'
    '.container, .container-fluid {'
    '  width: auto !important; max-width: none !important;'
    '  margin: 0 !important; padding: 0 !important;'
    '}'
    '#wrapwrap, main { width: auto !important; margin: 0 !important; }'
    'p { margin: 0 0 6pt 0; }'
    'h1, h2, h3, h4, h5, h6 {'
    '  margin: 0 0 8pt 0; font-weight: bold; page-break-after: avoid;'
    '}'
    'table {'
    '  border-collapse: collapse;'
    '  mso-table-lspace: 0pt; mso-table-rspace: 0pt;'
    '}'
    'tr { page-break-inside: avoid; }'
    'td, th { vertical-align: top; }'
    'img { border: 0; }'
    'a { color: inherit; text-decoration: none; }'
    '.d-none, .d-print-none, .o_no_print, .no-print { display: none; }'
    '.cbt-report { font-size: 11pt; color: #000000; }'
    '.cbt-title {'
    '  text-align: center; font-size: 15pt; letter-spacing: 0.5pt;'
    '  margin: 0 0 12pt 0;'
    '}'
    '.cbt-details { margin: 0 0 10pt 0; }'
    '.cbt-details td { padding: 2pt 4pt; }'
    '.cbt-instructions {'
    '  border: 1px solid #555555; padding: 6pt 9pt;'
    '  margin: 6pt 0 12pt 0; page-break-inside: avoid;'
    '}'
    '.cbt-question { margin: 0 0 9pt 0; page-break-inside: avoid; }'
    '.cbt-qnum { width: 32px; font-weight: bold; }'
    '.cbt-options { margin-left: 32px; }'
    '.cbt-opt-letter { width: 28px; }'
    '.cbt-section-title {'
    '  margin: 12pt 0 6pt 0; font-size: 12pt; page-break-after: avoid;'
    '}'
    '.cbt-qbody table, .cbt-obody table, .cbt-answerkey table {'
    '  width: 100% !important; table-layout: fixed;'
    '}'
    '.cbt-answerkey td, .cbt-answerkey th {'
    '  border: 1px solid #555555; padding: 3pt 5pt;'
    '}'
    '.cbt-paper { page-break-inside: auto; }'
    '.header, .o_cbt_report_header {'
    '  display: block; border-bottom: 1px solid #333333;'
    '  padding-bottom: 4pt; margin: 0 0 12pt 0;'
    '}'
    '.footer, .o_cbt_report_footer {'
    '  display: block; border-top: 1px solid #333333;'
    '  padding-top: 4pt; margin: 14pt 0 0 0;'
    '  font-size: 9pt; color: #333333;'
    '}'
    '</style>'
)

# Force Print view (the default Web Layout looks wrong) and identify the file
# as a Word document so Word opens it directly instead of asking.
_WORD_META = (
    '<meta http-equiv="Content-Type" content="text/html; charset=utf-8">'
    '<meta name="ProgId" content="Word.Document">'
    '<meta name="Generator" content="Microsoft Word 15">'
    '<!--[if gte mso 9]><xml><w:WordDocument>'
    '<w:View>Print</w:View><w:Zoom>100</w:Zoom>'
    '<w:DoNotOptimizeForBrowser/></w:WordDocument></xml><![endif]-->'
)


_IMG_MAX_HEIGHT = re.compile(
    r'style\s*=\s*["\'][^"\']*\bmax-height\s*:\s*([\d.]+)px',
    re.IGNORECASE)


def _img_size(match):
    """Add a Word-honoured ``height`` attribute from the CSS max-height."""
    tag = match.group(0)
    if re.search(r'\bheight\s*=', tag, flags=re.IGNORECASE):
        return tag
    found = _IMG_MAX_HEIGHT.search(tag)
    if not found:
        return tag
    opening = tag.rstrip('>').rstrip('/').rstrip()
    return '%s height="%d">' % (opening, round(float(found.group(1))))


class CBTReportWordController(http.Controller):
    """Serve the existing QWeb report design as a Word-compatible ``.doc``.

    URL: ``/cbt/report/word?report_ref=<xmlid|report_name>&res_id=<id>``.
    Several records: ``res_ids=1,2,3``.
    """

    @http.route('/cbt/report/word', type='http', auth='user', methods=['GET'])
    def cbt_report_word(self, report_ref=None, res_model=None, res_id=None,
                        res_ids=None, token=None, **kwargs):
        env = request.env
        if not report_ref:
            raise BadRequest(_("No report was specified."))

        try:
            report = env['ir.actions.report']._get_report(report_ref)
        except (ValueError, KeyError, MissingError):
            raise NotFound(_("Report not found."))
        if not report or report.report_type not in _ALLOWED_REPORT_TYPES:
            raise BadRequest(_("This report cannot be exported to Word."))

        if report.groups_id and not (report.groups_id & env.user.groups_id):
            raise AccessError(_("You are not allowed to print this report."))

        ids = [int(i) for i in re.findall(r'\d+', str(res_ids or res_id or ''))]
        if not ids:
            raise BadRequest(_("No document was selected."))
        if len(ids) > _MAX_RECORDS:
            raise BadRequest(_("Too many documents selected."))

        records = env[report.model].browse(ids).exists()
        if not records:
            raise MissingError(_("The selected document no longer exists."))
        records.check_access_rights('read')
        records.check_access_rule('read')

        html, _report_type = env['ir.actions.report']._render_qweb_html(
            report_ref, records.ids)
        html_str = (html.decode('utf-8', errors='ignore')
                    if isinstance(html, bytes) else str(html))

        base_url = (env['ir.config_parameter'].sudo().get_param('web.base.url')
                    or request.httprequest.host_url)
        document = self._to_word_html(html_str, base_url=base_url)
        filename = self._filename(report, records)

        response = request.make_response(document, headers=[
            ('Content-Type', 'application/msword;charset=utf-8'),
            ('Content-Disposition', content_disposition(filename)),
            ('Cache-Control', 'no-store'),
        ])
        if token:
            response.set_cookie('fileToken', token)
        return response

    @staticmethod
    def _to_word_html(html, base_url=None):
        """Patch the rendered QWeb HTML so Word opens it as a document."""
        if isinstance(html, bytes):
            html = html.decode('utf-8', errors='ignore')
        html = html.strip()
        if not html:
            raise BadRequest(_("The report is empty."))

        html = re.sub(r'<script\b[^>]*>.*?</script>', '', html,
                      flags=re.IGNORECASE | re.DOTALL)

        if re.search(r'<html\b', html, flags=re.IGNORECASE):
            html = re.sub(r'<html\b', '<html %s' % _MSO_NS, html, count=1,
                          flags=re.IGNORECASE)
        else:
            html = '<html %s><body>%s</body></html>' % (_MSO_NS, html)

        head_block = _WORD_META + _WORD_STYLE
        if re.search(r'</head\s*>', html, flags=re.IGNORECASE):
            # Append at the end of <head> so our rules win over report assets.
            html = re.sub(r'</head\s*>', lambda m: head_block + m.group(0),
                          html, count=1, flags=re.IGNORECASE)
        elif re.search(r'<head\b[^>]*>', html, flags=re.IGNORECASE):
            html = re.sub(r'<head\b[^>]*>', lambda m: m.group(0) + head_block,
                          html, count=1, flags=re.IGNORECASE)
        else:
            html = re.sub(r'<html\b[^>]*>', lambda m: m.group(0) +
                          '<head>' + head_block + '</head>',
                          html, count=1, flags=re.IGNORECASE)

        # Word ignores max-height/max-width but honours the height attribute:
        # copy max-height onto img tags (e.g. the company logo) so it does not
        # print at its natural, oversized dimensions.
        html = re.sub(r'<img\b[^>]*>', _img_size, html, flags=re.IGNORECASE)

        if not re.search(r'<div\b[^>]*\bWordSection1\b', html, flags=re.I):
            html = re.sub(r'(<body\b[^>]*>)',
                          r'\1<div class="WordSection1">', html, count=1,
                          flags=re.IGNORECASE)
            html = re.sub(r'</body>', '</div></body>', html, count=1,
                          flags=re.IGNORECASE)

        html = re.sub(
            r'<span\b([^>]*\bclass=["\'][^"\']*\bpage\b[^"\']*["\'][^>]*)>'
            r'\s*</span>',
            _PAGE_FIELD, html, flags=re.IGNORECASE)
        html = re.sub(
            r'<span\b([^>]*\bclass=["\'][^"\']*\btopage\b[^"\']*["\'][^>]*)>'
            r'\s*</span>',
            _NUMPAGES_FIELD, html, flags=re.IGNORECASE)
        html = re.sub(
            r'<span\b([^>]*\bclass=["\'][^"\']*\bpage\b[^"\']*["\'][^>]*)\s*/>',
            _PAGE_FIELD, html, flags=re.IGNORECASE)
        html = re.sub(
            r'<span\b([^>]*\bclass=["\'][^"\']*\btopage\b[^"\']*["\'][^>]*)\s*/>',
            _NUMPAGES_FIELD, html, flags=re.IGNORECASE)

        if base_url:
            base = base_url.rstrip('/')
            html = re.sub(
                r'(src|href)="/(?!/)',
                lambda m: '%s="%s/' % (m.group(1), base),
                html, flags=re.IGNORECASE)

        return html

    @staticmethod
    def _filename(report, records):
        name = None
        if len(records) == 1 and report.print_report_name:
            try:
                name = safe_eval(report.print_report_name,
                                 {'object': records, 'time': time})
            except Exception:  # noqa: BLE001 - never break the download
                _logger.warning("Cannot evaluate print_report_name of %s",
                                report.display_name, exc_info=True)
        if not name:
            if len(records) == 1:
                try:
                    suffix = records.display_name
                except Exception:  # noqa: BLE001
                    suffix = str(records.id)
            else:
                suffix = '%d' % len(records)
            name = '%s_%s' % (report.name or 'Report', suffix)
        name = re.sub(r'[\\/:*?"<>|\r\n\t]+', '_', str(name)).strip(' ._')
        return '%s.doc' % (name or 'Report')
