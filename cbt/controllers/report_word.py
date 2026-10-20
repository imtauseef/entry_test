# -*- coding: utf-8 -*-
"""Word (.doc) export of the CBT QWeb reports (Odoo 17).

The same QWeb template that produces the PDF is rendered to HTML, reshaped so
MS Word keeps the printed design and delivered as a Word MHTML document
(``multipart/related``) named ``.doc``.

Design improvements over a plain "HTML served as .doc":

* the report ``.header`` / ``.footer`` blocks become real Word page headers /
  footers (so the company header repeats on every page) and
  ``<span class="page"/>`` / ``<span class="topage"/>`` become live PAGE /
  NUMPAGES fields;
* images given as ``data:`` URIs (``image_data_uri`` - e.g. the company logo)
  are embedded as MIME parts because Word ignores ``data:`` URIs, and they get
  explicit width/height because Word ignores ``max-width`` / ``max-height``;
* CSS rules using descendant selectors / ``:not()`` (which Word does not
  understand) are inlined onto the matching elements;
* A4 page setup with the same margins as the PDF paper format;
* one page break between records, RTL support, clean file name (honours
  ``print_report_name``) and removal of scripts / external links / hidden
  print helper nodes.
"""
import base64
import hashlib
import logging
import quopri
import re
import time
from html import unescape as html_unescape
from io import BytesIO

from lxml import etree
from lxml import html as lxml_html
from werkzeug.exceptions import BadRequest, NotFound

from odoo import _, http
from odoo.exceptions import AccessError, MissingError
from odoo.http import content_disposition, request
from odoo.tools import html_escape
from odoo.tools.safe_eval import safe_eval

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None

_logger = logging.getLogger(__name__)

_ALLOWED_REPORT_TYPES = ('qweb-pdf', 'qweb-html')
_MAX_RECORDS = 500

_FILES_DIR = 'report_files'
_DOC_LOCATION = 'file:///C:/report.htm'
_MAX_IMG_WIDTH_PX = 680  # printable width of A4 with 1.4cm side margins

_IMG_EXT = {
    'image/png': 'png',
    'image/jpeg': 'jpg',
    'image/jpg': 'jpg',
    'image/gif': 'gif',
    'image/bmp': 'bmp',
}
_DATA_URI = re.compile(r'^data:(image/[\w.+-]+);base64,(.+)$', re.I | re.S)

# Matches the dedicated A4 paper format used by the PDF reports.
_PAGE_SIZE = '21.0cm 29.7cm'
_PAGE_MARGIN = '3.2cm 1.4cm 2.0cm 1.4cm'  # top right bottom left
_HEADER_MARGIN = '0.8cm'
_FOOTER_MARGIN = '0.8cm'

_MSO_NS = (
    'xmlns:v="urn:schemas-microsoft-com:vml" '
    'xmlns:o="urn:schemas-microsoft-com:office:office" '
    'xmlns:w="urn:schemas-microsoft-com:office:word" '
    'xmlns:m="http://schemas.microsoft.com/office/2004/12/omml" '
    'xmlns="http://www.w3.org/TR/REC-html40"'
)

# Only Word compatibility rules here: the visual design must come from the
# report template itself, not from the exporter.
_BASE_CSS = """
body { font-family: "Lato","Segoe UI","Noto Sans",Arial,sans-serif;
       font-size: 10.5pt; color: #000000; line-height: 1.35; }
div.WordSection1 { page: WordSection1; }
table { border-collapse: collapse; mso-table-lspace: 0pt; mso-table-rspace: 0pt; }
tr { page-break-inside: avoid; }
img { border: 0; }
p { margin: 0 0 6pt 0; }
h1, h2, h3, h4, h5, h6 { page-break-after: avoid; }
.d-none, .d-print-none, .o_no_print, .no-print { display: none; }
"""

_PAGE_FIELD = ('<span style=\'mso-field-code:" PAGE "\'>'
               '<span style=\'mso-no-proof:yes\'>1</span></span>')
_NUMPAGES_FIELD = ('<span style=\'mso-field-code:" NUMPAGES "\'>'
                   '<span style=\'mso-no-proof:yes\'>1</span></span>')


# ---------------------------------------------------------------------------
# Small HTML helpers
# ---------------------------------------------------------------------------
def _class_xpath(token):
    return ("//*[contains(concat(' ', normalize-space(@class), ' '), ' %s ')]"
            % token)


# Tags that, if found inside a text node, mean the report arrived HTML-escaped
# and lxml stored the markup as text (Word then prints the tags / meta).
_HTML_TAG = (
    r'div|main|table|thead|tbody|tr|td|th|html|head|body|meta|style|'
    r'p|span|h[1-6]|br|img|strong|em|ul|ol|li|article|header|footer|section'
)
_ESCAPED_ANGLE = r'&(?:amp;)*(?:lt|#0*60|#x0*3c);'
_ESCAPED_TAG = re.compile(
    _ESCAPED_ANGLE + r'\s*/?\s*(?:' + _HTML_TAG + r')\b', re.IGNORECASE)
_REAL_TAG = re.compile(r'<(?:html|div|body|head|table|main)\b', re.IGNORECASE)
_TEXT_MARKUP = re.compile(r'<\s*/?\s*(?:' + _HTML_TAG + r')\b', re.IGNORECASE)


def _unescape_report(html_str):
    """Undo HTML-escaping when the whole payload is escaped (no real tags)."""
    if _REAL_TAG.search(html_str) and not _ESCAPED_TAG.search(html_str):
        return html_str
    if not _ESCAPED_TAG.search(html_str):
        return html_str
    # Fully escaped documents can be unescaped as a whole. Mixed documents
    # (real header + escaped body) are repaired after parsing instead, so
    # that existing ``&amp;`` in real markup is left alone.
    if not _REAL_TAG.search(html_str):
        for _layer in range(3):
            if not _ESCAPED_TAG.search(html_str):
                break
            unescaped = html_unescape(html_str)
            if unescaped == html_str:
                break
            html_str = unescaped
    return html_str


def _parse_fragment(markup):
    """Parse a HTML snippet; return a wrapper element or None."""
    try:
        return lxml_html.fragment_fromstring(
            '<div class="cbt-word-frag">%s</div>' % markup)
    except (etree.ParserError, ValueError):
        return None


def _reify_markup_in_tree(root):
    """Replace text/tail nodes that contain HTML tags with real elements.

    When the report body arrives as ``&lt;div id="wrapwrap"&gt;...``, the
    parser decodes the entities and leaves a text node. Serialising that
    node would print the tags in Word; turning them into elements first
    lets CSS inlining, image embedding and header/footer extraction work.
    """
    for _pass in range(12):
        repaired = False
        for el in list(root.iter()):
            text = el.text or ''
            if _TEXT_MARKUP.search(text):
                frag = _parse_fragment(text)
                if frag is not None:
                    el.text = frag.text
                    for index, child in enumerate(list(frag)):
                        el.insert(index, child)
                    repaired = True
                    break
            parent = el.getparent()
            tail = el.tail or ''
            if parent is not None and _TEXT_MARKUP.search(tail):
                frag = _parse_fragment(tail)
                if frag is not None:
                    el.tail = frag.text
                    idx = parent.index(el)
                    for offset, child in enumerate(list(frag)):
                        parent.insert(idx + 1 + offset, child)
                    repaired = True
                    break
        if not repaired:
            break
    for leftover in root.xpath('//div[@class="cbt-word-frag"]'):
        leftover.drop_tag()


def _merge_style(el, css):
    """Prepend ``css`` to the element style (existing inline style wins)."""
    old = (el.get('style') or '').strip()
    if old and not old.endswith(';'):
        old += ';'
    el.set('style', css + old)


def _markup_or_escape(text):
    text = text or ''
    if _TEXT_MARKUP.search(text):
        return text
    return html_escape(text)


def _inner_html(el):
    """Serialise children as HTML; keep already-decoded markup as markup."""
    parts = [_markup_or_escape(el.text)]
    for child in el:
        parts.append(etree.tostring(
            child, encoding='unicode', method='html', with_tail=False))
        parts.append(_markup_or_escape(child.tail))
    return ''.join(parts)


def _outer_html(el):
    return etree.tostring(el, encoding='unicode', method='html',
                          with_tail=False)


# ---------------------------------------------------------------------------
# Minimal CSS inliner (Word ignores descendant selectors and :not())
# ---------------------------------------------------------------------------
_COMPOUND = re.compile(
    r'(?P<tag>\*|[a-zA-Z][\w-]*)?'
    r'(?P<rest>(?:\.[\w-]+|#[\w-]+|\[[^\]]+\]|:not\([^)]*\)|:[\w-]+)*)$')
_SIMPLE = re.compile(
    r'\.([\w-]+)|#([\w-]+)'
    r'|\[([^\]=~|^$*\s]+)\s*(?:=\s*["\']?([^"\'\]]*)["\']?)?\]'
    r'|:not\(([^)]*)\)|:([\w-]+)')


def _compound_conditions(rest):
    conds, spec, pos = [], 0, 0
    while pos < len(rest):
        match = _SIMPLE.match(rest, pos)
        if not match:
            raise ValueError('unsupported selector part %r' % rest[pos:])
        pos = match.end()
        cls, ident, attr, val, neg, pseudo = match.groups()
        if cls:
            conds.append("contains(concat(' ',normalize-space(@class),' '),"
                         "' %s ')" % cls)
            spec += 10
        elif ident:
            conds.append("@id='%s'" % ident)
            spec += 100
        elif attr:
            conds.append("@%s='%s'" % (attr, val) if val is not None
                         else '@%s' % attr)
            spec += 10
        elif neg is not None:
            inner, inner_spec = _compound_conditions(neg.strip())
            if not inner:
                raise ValueError('empty :not()')
            conds.append('not(%s)' % ' and '.join(inner))
            spec += inner_spec
        elif pseudo == 'first-child':
            conds.append('not(preceding-sibling::*)')
            spec += 10
        elif pseudo == 'last-child':
            conds.append('not(following-sibling::*)')
            spec += 10
        else:
            raise ValueError('unsupported pseudo %r' % pseudo)
    return conds, spec


def _selector_to_xpath(selector):
    tokens = re.split(r'\s*(>)\s*|\s+', selector.strip())
    tokens = [t for t in tokens if t]
    if not tokens or '+' in selector or '~' in selector:
        raise ValueError('unsupported selector')
    xpath, spec, axis = '', 0, '//'
    for token in tokens:
        if token == '>':
            axis = '/'
            continue
        match = _COMPOUND.match(token)
        if not match:
            raise ValueError('bad compound %r' % token)
        conds, cspec = _compound_conditions(match.group('rest') or '')
        tag = match.group('tag') or '*'
        spec += cspec + (0 if tag == '*' else 1)
        xpath += '%s%s%s' % (axis, tag, ''.join('[%s]' % c for c in conds))
        axis = '//'
    return xpath, spec


def _parse_declarations(block):
    out = []
    for decl in re.split(r';(?![^()]*\))', block):
        if ':' not in decl:
            continue
        prop, value = decl.split(':', 1)
        prop = prop.strip().lower()
        value = re.sub(r'\s*!important\s*$', '', value.strip(), flags=re.I)
        if prop and value:
            out.append((prop, value))
    return out


def _inline_css(root):
    """Copy every ``<style>`` rule onto the matching elements as inline style
    (existing inline style wins), then drop the ``<style>`` elements."""
    styles = root.xpath('//style')
    rules = []
    for style in styles:
        css = re.sub(r'/\*.*?\*/|<!--|-->', '', style.text_content() or '',
                     flags=re.S)
        for match in re.finditer(r'([^{}]+)\{([^{}]*)\}', css):
            selectors, block = match.group(1).strip(), match.group(2)
            if selectors.startswith('@'):
                continue
            decls = _parse_declarations(block)
            if not decls:
                continue
            for sel in selectors.split(','):
                try:
                    xpath, spec = _selector_to_xpath(sel)
                except ValueError:
                    continue
                rules.append((spec, len(rules), xpath, decls))
    rules.sort(key=lambda rule: (rule[0], rule[1]))

    computed = {}
    for _spec, _idx, xpath, decls in rules:
        try:
            matched = root.xpath(xpath)
        except etree.XPathError:
            continue
        for el in matched:
            store = computed.setdefault(el, {})
            for prop, value in decls:
                store[prop] = value
    for el, props in computed.items():
        existing = dict(_parse_declarations(el.get('style') or ''))
        props.update(existing)
        el.set('style', ';'.join('%s:%s' % kv for kv in props.items()) + ';')
    for style in styles:
        if style.getparent() is not None:
            style.drop_tree()


class CBTReportWordController(http.Controller):
    """Serve the existing QWeb report design as a Word-compatible ``.doc``.

    URL: ``/cbt/report/word?report_ref=<xmlid|report_name>&res_id=<id>``.
    Several records: ``res_ids=1,2,3``.
    """

    # ------------------------------------------------------------------
    # Route
    # ------------------------------------------------------------------
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

        # Respect the report's own group restriction (e.g. Answer Key).
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
                    or request.httprequest.host_url).rstrip('/')
        lang = env.user.lang or 'en_US'
        rtl = env['res.lang']._lang_get(lang).direction == 'rtl'

        filename = self._filename(report, records)
        data = self._to_word_mhtml(
            html_str, base_url=base_url,
            title=filename.rsplit('.', 1)[0], lang=lang, rtl=rtl)

        response = request.make_response(data, headers=[
            ('Content-Type', 'application/msword'),
            ('Content-Disposition', content_disposition(filename)),
            ('Cache-Control', 'no-store'),
        ])
        if token:  # lets the web client stop its "downloading" spinner
            response.set_cookie('fileToken', token)
        return response

    # ------------------------------------------------------------------
    # File name
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # HTML -> Word MHTML
    # ------------------------------------------------------------------
    @classmethod
    def _to_word_mhtml(cls, html_str, base_url=None, title='Report',
                       lang='en_US', rtl=False):
        root = cls._parse(html_str)
        if base_url:
            root.make_links_absolute(base_url, resolve_base_href=False,
                                     handle_failures='ignore')

        cls._clean(root)
        _inline_css(root)
        images = cls._embed_images(root)
        header_html = cls._pop_block(root, ('o_cbt_report_header', 'header'))
        footer_html = cls._pop_block(
            root, ('o_cbt_report_footer', 'footer'), page_fields=True)
        if not footer_html:
            footer_html = (
                '<p style="text-align:center;font-size:8pt;color:#6b7785;'
                'margin:0">%s [[PAGE]] / [[NUMPAGES]]</p>'
                % html_escape(_("Page")))

        # One page break between records.
        for index, article in enumerate(root.xpath(_class_xpath('article'))):
            if index:
                _merge_style(article, 'page-break-before:always;')

        body = root.find('body')
        if body is None:
            body = root
        content = _inner_html(body)
        if _ESCAPED_TAG.search(content):
            content = html_unescape(content)

        document = cls._assemble(
            content, header_html, footer_html, title=title, lang=lang,
            rtl=rtl)
        document = (document.replace('[[PAGE]]', _PAGE_FIELD)
                    .replace('[[NUMPAGES]]', _NUMPAGES_FIELD))
        return cls._mhtml(document, images)

    # -- parsing ----------------------------------------------------------
    @staticmethod
    def _parse(html_str):
        """Parse the rendered report; repair markup that arrives HTML-escaped
        (``&lt;div&gt;``), which would otherwise be printed as literal text."""
        html_str = _unescape_report(html_str).strip()
        if not html_str:
            raise BadRequest(_("The report is empty."))
        try:
            root = lxml_html.document_fromstring(html_str)
        except (etree.ParserError, ValueError):
            raise BadRequest(_("The report could not be converted to Word."))
        _reify_markup_in_tree(root)
        return root

    # -- cleaning ---------------------------------------------------------
    @staticmethod
    def _clean(root):
        for el in root.xpath('//script|//noscript|//link|//iframe|//object'
                             '|//embed'):
            el.drop_tree()
        for token in ('d-none', 'd-print-none', 'o_no_print', 'no-print'):
            for el in root.xpath(_class_xpath(token)):
                if el.getparent() is not None:
                    el.drop_tree()

    # -- images -----------------------------------------------------------
    @classmethod
    def _embed_images(cls, root):
        """Embed ``data:`` images as MIME parts; return [(name, mime, raw)]."""
        parts, cache = [], {}
        for img in root.iter('img'):
            match = _DATA_URI.match((img.get('src') or '').strip())
            if not match:
                continue
            mime = match.group(1).lower()
            if mime == 'image/svg+xml':  # Word cannot render SVG
                continue
            try:
                raw = base64.b64decode(match.group(2))
            except (ValueError, TypeError):
                continue
            if mime not in _IMG_EXT:
                raw, mime = cls._to_png(raw)
                if not raw:
                    continue
            key = hashlib.sha1(raw).hexdigest()
            if key not in cache:
                cache[key] = 'image%03d.%s' % (len(cache) + 1, _IMG_EXT[mime])
                parts.append((cache[key], mime, raw))
            img.set('src', '%s/%s' % (_FILES_DIR, cache[key]))
            cls._fit_image(img, raw)
        return parts

    @staticmethod
    def _to_png(raw):
        if Image is None:
            return None, None
        try:
            out = BytesIO()
            Image.open(BytesIO(raw)).convert('RGBA').save(out, 'PNG')
            return out.getvalue(), 'image/png'
        except Exception:  # noqa: BLE001
            return None, None

    @staticmethod
    def _fit_image(img, raw):
        """Give the image explicit pixel size (Word ignores max-width/height)."""
        if Image is None:
            return
        try:
            nat_w, nat_h = Image.open(BytesIO(raw)).size
        except Exception:  # noqa: BLE001
            return
        if not nat_w or not nat_h:
            return
        ratio = nat_w / float(nat_h)
        style = img.get('style') or ''

        def css_px(prop):
            match = re.search(
                r'(?:^|[;\s])%s\s*:\s*([\d.]+)\s*(px|pt)?\s*(?:;|$)'
                % re.escape(prop), style, re.I)
            if not match:
                return None
            value = float(match.group(1))
            return value * 96 / 72 if (match.group(2) or '').lower() == 'pt' \
                else value

        def attr_px(name):
            match = re.match(r'^\s*([\d.]+)\s*(?:px)?\s*$', img.get(name) or '')
            return float(match.group(1)) if match else None

        height = attr_px('height') or css_px('height') or css_px('max-height')
        width = attr_px('width') or css_px('width') or css_px('max-width')
        if height and not width:
            width = height * ratio
        elif width and not height:
            height = width / ratio
        elif not width and not height:
            width, height = float(nat_w), float(nat_h)
        if width > _MAX_IMG_WIDTH_PX:
            height *= _MAX_IMG_WIDTH_PX / width
            width = _MAX_IMG_WIDTH_PX

        style = re.sub(r'(?:^|(?<=;))\s*(?:max-)?(?:width|height)\s*:[^;]*;?',
                       '', style, flags=re.I)
        img.set('width', str(int(round(width))))
        img.set('height', str(int(round(height))))
        img.set('style', 'width:%dpx;height:%dpx;%s'
                % (round(width), round(height), style))

    # -- Word header / footer --------------------------------------------
    @staticmethod
    def _pop_block(root, tokens, page_fields=False):
        """Remove the first matching block family from the body and return its
        HTML (to be used as a Word page header / footer)."""
        for token in tokens:
            found = root.xpath(_class_xpath(token))
            if not found:
                continue
            found_set = set(found)
            outer = [e for e in found
                     if not any(a in found_set for a in e.iterancestors())]
            first = outer[0]
            if page_fields:
                for span in first.xpath(
                        ".//span[contains(concat(' ', normalize-space(@class),"
                        " ' '), ' page ')]"):
                    span.attrib.clear()
                    span.text = '[[PAGE]]'
                for span in first.xpath(
                        ".//span[contains(concat(' ', normalize-space(@class),"
                        " ' '), ' topage ')]"):
                    span.attrib.clear()
                    span.text = '[[NUMPAGES]]'
            result = _outer_html(first)
            for el in outer:
                if el.getparent() is not None:
                    el.drop_tree()
            return result
        return ''

    # -- assembling -------------------------------------------------------
    @staticmethod
    def _assemble(content, header_html, footer_html, title, lang, rtl):
        page = [
            '@page WordSection1 {',
            'size:%s;' % _PAGE_SIZE,
            'margin:%s;' % _PAGE_MARGIN,
            'mso-header-margin:%s;' % _HEADER_MARGIN,
            'mso-footer-margin:%s;' % _FOOTER_MARGIN,
            'mso-paper-source:0;',
        ]
        if header_html:
            page.append('mso-header:h1;')
        if footer_html:
            page.append('mso-footer:f1;')
        page.append('}')
        if rtl:
            page.append('body { direction: rtl; }')

        header_div = (
            "<div style='mso-element:header' id=h1>%s</div>" % header_html
            if header_html else '')
        footer_div = (
            "<div style='mso-element:footer' id=f1>%s</div>" % footer_html
            if footer_html else '')

        return (
            '<html %(ns)s>\n<head>\n'
            '<meta http-equiv="Content-Type" content="text/html; charset=utf-8">\n'
            '<meta name="ProgId" content="Word.Document">\n'
            '<meta name="Generator" content="Microsoft Word 15">\n'
            '<title>%(title)s</title>\n'
            '<!--[if gte mso 9]><xml><w:WordDocument><w:View>Print</w:View>'
            '<w:Zoom>100</w:Zoom><w:DoNotOptimizeForBrowser/>'
            '</w:WordDocument></xml><![endif]-->\n'
            '<style>\n<!--\n%(page)s\n%(css)s\n-->\n</style>\n</head>\n'
            '<body lang="%(lang)s" dir="%(dir)s" '
            'style="tab-interval:36pt;word-wrap:break-word">\n'
            '<div class="WordSection1">\n%(content)s\n</div>\n'
            '%(header)s\n%(footer)s\n</body>\n</html>'
        ) % {
            'ns': _MSO_NS,
            'title': html_escape(title),
            'page': '\n'.join(page),
            'css': _BASE_CSS,
            'lang': lang.replace('_', '-'),
            'dir': 'rtl' if rtl else 'ltr',
            'content': content,
            'header': header_div,
            'footer': footer_div,
        }

    @staticmethod
    def _mhtml(document, images):
        """Pack the HTML and its images into one MHTML (multipart/related).

        Word is strict about the envelope: the top level must be
        ``multipart/related; type="text/html"`` and the first part must stay
        ``text/html`` (with a ``Content-Location``), otherwise Word shows the
        raw markup instead of the rendered report.
        """
        boundary = b'----=_NextPart_CBT_REPORT_01'
        crlf = b'\r\n'
        html_part = quopri.encodestring(
            document.encode('utf-8')).replace(b'\n', crlf).rstrip(crlf)
        chunks = [
            b'MIME-Version: 1.0',
            b'Content-Type: multipart/related; boundary="' + boundary
            + b'"; type="text/html"',
            b'',
            b'--' + boundary,
            b'Content-Type: text/html; charset="utf-8"',
            b'Content-Transfer-Encoding: quoted-printable',
            b'Content-Location: ' + _DOC_LOCATION.encode('ascii'),
            b'',
            html_part,
        ]
        for name, mime, raw in images:
            location = 'file:///C:/%s/%s' % (_FILES_DIR, name)
            chunks.extend([
                b'--' + boundary,
                b'Content-Type: ' + mime.encode('ascii'),
                b'Content-Transfer-Encoding: base64',
                b'Content-Location: ' + location.encode('ascii'),
                b'',
                base64.encodebytes(raw).replace(b'\n', crlf).rstrip(crlf),
            ])
        chunks.append(b'--' + boundary + b'--')
        chunks.append(b'')
        return b'\r\n'.join(chunks)
