# -*- coding: utf-8 -*-
"""Per-request validation of the portal participant single session."""
from urllib.parse import urlencode

from werkzeug.exceptions import HTTPException
from werkzeug.utils import redirect

from odoo import models
from odoo.http import request

# Routes that must stay reachable while a session is being established/closed.
_SKIP_EXACT = {
    '/', '/web', '/web/login', '/web/login_successful', '/web/health',
    '/web/signup', '/web/reset_password', '/favicon.ico', '/robots.txt',
}
_SKIP_PREFIXES = (
    '/web/session/',       # authenticate / logout / destroy / check / ...
    '/web/assets/', '/web/static/', '/static/',
    '/web/image', '/web/content', '/web/database',
    '/auth_oauth/', '/auth_signup/',
    '/cbt_portal/static/',
    # Heartbeats answer with JSON instead of an HTML redirect.
    '/cbt/time/remaining', '/cbt/paper/currentState',
)


class CBTSessionEnded(HTTPException):
    """Valid 303 redirect that also lets Odoo save the cleared session.

    ``code = None`` makes ``odoo.http.Application.__call__`` run
    ``post_dispatch`` (and therefore ``_save_session``) before returning the
    response, so the logout performed in ``_authenticate`` is persisted.
    """
    code = None

    def __init__(self, location):
        super().__init__()
        self.location = location

    def get_response(self, environ=None, scope=None):
        return redirect(self.location, code=303)


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    @classmethod
    def _authenticate(cls, endpoint):
        super()._authenticate(endpoint)
        cls._cbt_enforce_session()

    @classmethod
    def _cbt_enforce_session(cls):
        if not request or not request.env or not request.session:
            return
        path = request.httprequest.path
        if path in _SKIP_EXACT or path.startswith(_SKIP_PREFIXES):
            return

        uid = request.session.uid
        if not uid:
            return

        user = request.env['res.users'].sudo().browse(uid).exists()
        if not user or not user._cbt_is_portal_only():
            return

        token = request.session.get('cbt_token')
        if not token or not user._cbt_session_matches(token):
            request.session.logout(keep_db=True)
            query = urlencode({
                'cbt_session_ended': 1,
                'redirect': request.httprequest.full_path,
            })
            raise CBTSessionEnded('/web/login?' + query)

        user._cbt_touch_session(token)
