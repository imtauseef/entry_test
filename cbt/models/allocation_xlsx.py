# -*- coding: utf-8 -*-
"""Offline allocation workbook helpers.

Odoo 17 writes XLSX with XlsxWriter (``odoo.tools.misc.xlsxwriter``, also
listed in the official requirements). XlsxWriter cannot read workbooks, and
openpyxl is not an Odoo 17 runtime dependency. The reader below uses the
stdlib zip container plus lxml (already required by Odoo) to parse the simple
worksheets this module generates.
"""
import base64
import hashlib
import html
import io
import json
import re
import zipfile

from lxml import etree
try:
    import msoffcrypto
    from msoffcrypto.format.ooxml import OOXMLFile
except ImportError:
    msoffcrypto = None
    OOXMLFile = None

from odoo.exceptions import AccessDenied, UserError
from odoo.tools.misc import xlsxwriter
from odoo.tools.translate import _

_SPREADSHEET_NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
_REL_NS = 'http://schemas.openxmlformats.org/package/2006/relationships'
_OFFICE_REL_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
_NS = {'m': _SPREADSHEET_NS, 'r': _OFFICE_REL_NS, 'pr': _REL_NS}
_XML_PARSER = etree.XMLParser(resolve_entities=False, huge_tree=False, remove_blank_text=False)
_IMAGE_SRC_RE = re.compile(
    r'(?P<prefix><img\b[^>]*?\bsrc\s*=\s*)'
    r'(?P<quote>["\'])(?P<src>.*?)(?P=quote)',
    re.IGNORECASE | re.DOTALL,
)
_MIN_XLSX_PASSWORD_LENGTH = 12


class AllocationWorkbook:
    """Minimal workbook API compatible with the import wizard's sheet access."""

    def __init__(self, sheets):
        self._sheets = sheets
        self.sheetnames = list(sheets)

    def __getitem__(self, name):
        if name not in self._sheets:
            raise KeyError(name)
        return self._sheets[name]


class AllocationWorksheet:
    def __init__(self, title, rows):
        self.title = title
        self._rows = rows
        self.max_row = len(rows)

    def iter_rows(self, values_only=True):
        for row in self._rows:
            yield tuple(row)


def transform_html_image_sources(value, transform):
    """Apply a callback to quoted ``img[src]`` values without reserializing HTML."""
    return _IMAGE_SRC_RE.sub(
        lambda match: '%s%s%s%s' % (
            match.group('prefix'),
            match.group('quote'),
            html.escape(transform(html.unescape(match.group('src'))), quote=True),
            match.group('quote'),
        ),
        value or '',
    )


def offline_image_key(mimetype, image_data):
    """Return a stable content key that also distinguishes image MIME types."""
    digest = hashlib.sha256()
    digest.update(mimetype.encode('ascii'))
    digest.update(b'\0')
    digest.update(image_data)
    return digest.hexdigest()


def offline_image_placeholder(image_key):
    return 'cbt-offline-image:%s' % image_key


def normalize_inline_image_sources(value):
    """Replace embedded data-image sources with their stable workbook markers."""
    def to_placeholder(source):
        header, separator, encoded = source.partition(',')
        if not separator or not header.startswith('data:image/') or ';base64' not in header:
            return source
        mimetype = header[5:].split(';', 1)[0].lower()
        try:
            image_data = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            return source
        return offline_image_placeholder(offline_image_key(mimetype, image_data))

    return transform_html_image_sources(value, to_placeholder)


def build_allocation_xlsx(sheets):
    """Write named worksheets (list of (name, rows)) to an XLSX byte string."""
    if xlsxwriter is None:
        raise UserError(_(
            'The XlsxWriter library is required to generate the allocation '
            'workbook. It is part of the standard Odoo 17 runtime.'
        ))
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {
        'in_memory': True,
        'strings_to_formulas': False,
        'strings_to_urls': False,
        'nan_inf_to_errors': True,
    })
    try:
        for name, rows in sheets:
            worksheet = workbook.add_worksheet(name)
            for row_index, row in enumerate(rows):
                if row_index >= worksheet.xls_rowmax:
                    raise UserError(_(
                        'The allocation is too large for a single Excel worksheet.'
                    ))
                for column, value in enumerate(row):
                    _write_cell(worksheet, row_index, column, value)
    finally:
        workbook.close()
    return output.getvalue()


def encrypt_xlsx(content, password):
    if not password or len(password) < _MIN_XLSX_PASSWORD_LENGTH:
        raise UserError(_(
            'The workbook password must contain at least 12 characters.'))
    _require_xlsx_encryption_library()
    output = io.BytesIO()
    OOXMLFile(io.BytesIO(content)).encrypt(password, output)
    return output.getvalue()


def decrypt_xlsx(content, password=None):
    source = io.BytesIO(content)
    if zipfile.is_zipfile(source):
        return content
    _require_xlsx_encryption_library()
    try:
        office_file = msoffcrypto.OfficeFile(io.BytesIO(content))
    except msoffcrypto.exceptions.FileFormatError as exc:
        raise UserError(_(
            'The uploaded file is not a valid XLSX workbook.')) from exc
    if not office_file.is_encrypted():
        raise UserError(_(
            'The uploaded file is not a valid XLSX workbook.'))
    if not password:
        raise UserError(_(
            'This workbook is password-protected. Enter its workbook password.'))
    try:
        office_file.load_key(password=password, verify_password=True)
        output = io.BytesIO()
        office_file.decrypt(output, verify_integrity=True)
    except msoffcrypto.exceptions.InvalidKeyError as exc:
        raise UserError(_('The workbook password is incorrect.')) from exc
    except msoffcrypto.exceptions.DecryptionError as exc:
        raise UserError(_(
            'The workbook could not be decrypted. Check its password and file.')) from exc
    return output.getvalue()


def _require_xlsx_encryption_library():
    if not msoffcrypto or not OOXMLFile:
        raise UserError(_(
            'Install msoffcrypto-tool in the Odoo Python environment to '
            'encrypt or import password-protected workbooks.'))


def verify_excel_admin_password(env, password):
    if not env.user.has_group('cbt.group_cbt_admin'):
        raise UserError(_(
            'Only CBT administrators may import or export Excel workbooks.'))
    if not password:
        raise UserError(_(
            'Enter your Odoo login password to continue.'))
    try:
        env.user._check_credentials(password, {'interactive': True})
    except AccessDenied as exc:
        raise UserError(_(
            'The Odoo login password is incorrect.')) from exc


def excel_password_prompt_action(record, method, operation, title):
    record.ensure_one()
    if not record.env.user.has_group('cbt.group_cbt_admin'):
        raise UserError(_(
            'Only CBT administrators may import or export Excel workbooks.'))
    record.check_access_rights('read')
    record.check_access_rule('read')
    return {
        'type': 'ir.actions.client',
        'tag': 'cbt_excel_password_prompt',
        'params': {
            'model': record._name,
            'method': method,
            'res_id': record.id,
            'operation': operation,
            'title': title,
            'context': dict(record.env.context),
        },
    }


def offline_result_payload_hash(papers, answers):
    payload = {'papers': papers, 'answers': answers}
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def load_allocation_xlsx(content):
    """Parse an XLSX byte string produced for CBT allocation transfer."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except (zipfile.BadZipFile, TypeError, ValueError) as exc:
        raise ValueError('The uploaded file is not a valid XLSX workbook.') from exc
    try:
        workbook_xml = _read_xml(archive, 'xl/workbook.xml')
        rels_xml = _read_xml(archive, 'xl/_rels/workbook.xml.rels')
    except KeyError as exc:
        raise ValueError('The uploaded file is not a valid XLSX workbook.') from exc

    shared_strings = _read_shared_strings(archive)
    targets = {}
    for rel in rels_xml.findall('{%s}Relationship' % _REL_NS):
        targets[rel.get('Id')] = rel.get('Target')

    sheets = {}
    for sheet_el in workbook_xml.findall('m:sheets/m:sheet', _NS):
        name = sheet_el.get('name')
        rel_id = sheet_el.get('{%s}id' % _OFFICE_REL_NS)
        target = targets.get(rel_id)
        if not name or not target:
            raise ValueError('The uploaded file is not a valid XLSX workbook.')
        path = _worksheet_path(target)
        try:
            sheet_xml = _read_xml(archive, path)
        except KeyError as exc:
            raise ValueError('The uploaded file is not a valid XLSX workbook.') from exc
        sheets[name] = AllocationWorksheet(name, _read_sheet_rows(sheet_xml, shared_strings))
    if not sheets:
        raise ValueError('The uploaded file is not a valid XLSX workbook.')
    return AllocationWorkbook(sheets)


def _write_cell(worksheet, row, column, value):
    if value is None:
        return
    if isinstance(value, bool):
        worksheet.write_boolean(row, column, value)
        return
    if isinstance(value, int):
        worksheet.write_number(row, column, value)
        return
    if isinstance(value, float):
        worksheet.write_number(row, column, value)
        return
    text = str(value)
    if len(text) > worksheet.xls_strmax:
        raise UserError(_(
            "A workbook cell exceeds Excel's maximum text length."
        ))
    worksheet.write_string(row, column, text)


def _read_xml(archive, path):
    with archive.open(path) as handle:
        return etree.parse(handle, _XML_PARSER)


def _read_shared_strings(archive):
    try:
        root = _read_xml(archive, 'xl/sharedStrings.xml')
    except KeyError:
        return []
    values = []
    for si in root.findall('{%s}si' % _SPREADSHEET_NS):
        texts = [
            node.text or ''
            for node in si.findall('.//{%s}t' % _SPREADSHEET_NS)
        ]
        values.append(''.join(texts))
    return values


def _worksheet_path(target):
    target = (target or '').lstrip('/')
    if target.startswith('xl/'):
        path = target
    else:
        path = 'xl/%s' % target
    if '..' in path.split('/'):
        raise ValueError('The uploaded file is not a valid XLSX workbook.')
    return path


def _read_sheet_rows(sheet_xml, shared_strings):
    rows = []
    for row_el in sheet_xml.findall('m:sheetData/m:row', _NS):
        cells = {}
        next_col = 1
        for cell_el in row_el.findall('{%s}c' % _SPREADSHEET_NS):
            column = _cell_column(cell_el.get('r'), next_col)
            cells[column] = _cell_value(cell_el, shared_strings)
            next_col = column + 1
        if not cells:
            rows.append([])
            continue
        width = max(cells)
        rows.append([cells.get(index) for index in range(1, width + 1)])
    return rows


def _cell_column(reference, fallback):
    if not reference:
        return fallback
    letters = []
    for char in reference:
        if char.isalpha():
            letters.append(char.upper())
        else:
            break
    if not letters:
        return fallback
    column = 0
    for char in letters:
        column = column * 26 + (ord(char) - 64)
    return column


def _cell_value(cell_el, shared_strings):
    cell_type = cell_el.get('t')
    if cell_type == 's':
        index = _node_text(cell_el.find('{%s}v' % _SPREADSHEET_NS))
        try:
            return shared_strings[int(index)]
        except (TypeError, ValueError, IndexError) as exc:
            raise ValueError('The uploaded file is not a valid XLSX workbook.') from exc
    if cell_type == 'inlineStr':
        texts = [
            node.text or ''
            for node in cell_el.findall('.//{%s}t' % _SPREADSHEET_NS)
        ]
        return ''.join(texts)
    if cell_type == 'b':
        raw = _node_text(cell_el.find('{%s}v' % _SPREADSHEET_NS))
        return raw in ('1', 'true', 'TRUE')
    raw = _node_text(cell_el.find('{%s}v' % _SPREADSHEET_NS))
    if raw in (None, ''):
        return None
    if cell_type in ('str', 'e'):
        return raw
    try:
        number = float(raw)
    except ValueError:
        return raw
    if number.is_integer():
        return int(number)
    return number


def _node_text(node):
    if node is None:
        return None
    return node.text
