# -*- coding: utf-8 -*-
"""Release the CBT single-session token on logout."""
from odoo import http
from odoo.http import request
from odoo.addons.web.controllers.session import Session as WebSession


class CBTSession(WebSession):

    def _cbt_release_if_current(self):
        # ``/web/session/logout`` is auth="none", so request.env.user is the
        # public user; the participant is identified by the session uid.
        uid = request.session.uid
        if not uid:
            return
        user = request.env['res.users'].sudo().browse(uid).exists()
        if not user or not user._cbt_is_portal_only():
            return
        token = request.session.get('cbt_token')
        # Only clear the token that belongs to *this* session; otherwise a
        # stale tab logging out would kill the new device's session.
        if token and user.sudo()._cbt_session_matches(token):
            user.sudo()._cbt_clear_session()

    @http.route()
    def logout(self, redirect='/web'):
        self._cbt_release_if_current()
        return super().logout(redirect=redirect)

    @http.route()
    def destroy(self):
        self._cbt_release_if_current()
        return super().destroy()
