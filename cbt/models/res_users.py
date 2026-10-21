# -*- coding: utf-8 -*-
"""Portal participant single-session support.

The active-session marker lives on ``res.users`` (one token per user) instead
of a separate model: it is a strict 1:1 relation, it needs no extra join, and
it cannot leave orphan session rows.  The token is kept in PostgreSQL so the
check is shared by every worker; no in-memory/global state is used.
"""
import logging
import secrets

from odoo import _, SUPERUSER_ID, api, fields, models
from odoo.exceptions import AccessDenied
from odoo.http import request

_logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 120
_TOUCH_INTERVAL = 30

_SESSION_FIELDS = (
    'cbt_session_token', 'cbt_last_seen', 'cbt_login_ip', 'cbt_user_agent',
)


class ResUsers(models.Model):
    _inherit = 'res.users'

    cbt_session_token = fields.Char(
        string='CBT Session Token', index=True, copy=False,
        groups='base.group_system',
        help='Random token of the single active portal session.',
    )
    cbt_last_seen = fields.Datetime(
        string='CBT Last Seen', copy=False, groups='base.group_system',
        help='Last request timestamp of the active portal session.',
    )
    cbt_login_ip = fields.Char(
        string='CBT Login IP', copy=False, groups='base.group_system',
    )
    cbt_user_agent = fields.Char(
        string='CBT User Agent', copy=False, groups='base.group_system',
    )

    # ------------------------------------------------------------------ helpers
    def _cbt_is_portal_only(self):
        """True for portal participants only; internal/admin users are exempt."""
        self.ensure_one()
        return (self.has_group('base.group_portal')
                and not self.has_group('base.group_user'))

    def _cbt_timeout(self):
        value = self.env['ir.config_parameter'].sudo().get_param(
            'cbt.session_timeout_seconds', _DEFAULT_TIMEOUT)
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return _DEFAULT_TIMEOUT

    def _cbt_session_matches(self, token):
        self.ensure_one()
        return bool(token) and token == (self.cbt_session_token or '')

    def _cbt_claim_session(self, timeout=None, ip=None, user_agent=None):
        """Atomically claim the session token for this user.

        The conditional ``UPDATE`` is evaluated by PostgreSQL under a row lock,
        so two concurrent logins cannot both win: the loser waits for the
        winner, then sees a fresh token/last_seen and updates 0 rows.
        """
        self.ensure_one()
        timeout = timeout if timeout is not None else self._cbt_timeout()
        token = secrets.token_urlsafe(32)
        self.env.cr.execute(
            """
            UPDATE res_users
               SET cbt_session_token = %s,
                   cbt_last_seen = (NOW() AT TIME ZONE 'UTC'),
                   cbt_login_ip = %s,
                   cbt_user_agent = %s
             WHERE id = %s
               AND (
                    cbt_session_token IS NULL
                    OR cbt_session_token = ''
                    OR cbt_last_seen IS NULL
                    OR cbt_last_seen < (NOW() AT TIME ZONE 'UTC')
                                      - make_interval(secs => %s)
               )
            RETURNING id
            """,
            [token, (ip or '')[:255], (user_agent or '')[:255], self.id,
             int(timeout)],
        )
        if not self.env.cr.fetchone():
            self.invalidate_recordset(_SESSION_FIELDS)
            return False
        self.invalidate_recordset(_SESSION_FIELDS)
        return token

    def _cbt_touch_session(self, token, interval=_TOUCH_INTERVAL):
        """Refresh last_seen, throttled to at most once per ``interval`` s."""
        self.ensure_one()
        self.env.cr.execute(
            """
            UPDATE res_users
               SET cbt_last_seen = (NOW() AT TIME ZONE 'UTC')
             WHERE id = %s
               AND cbt_session_token = %s
               AND (
                    cbt_last_seen IS NULL
                    OR cbt_last_seen < (NOW() AT TIME ZONE 'UTC')
                                      - make_interval(secs => %s)
               )
            """,
            [self.id, token, int(interval)],
        )
        if self.env.cr.rowcount:
            self.invalidate_recordset(['cbt_last_seen'])

    def _cbt_clear_session(self):
        """Force logout: forget the token and last activity."""
        for user in self:
            user.sudo().write({
                'cbt_session_token': False,
                'cbt_last_seen': False,
                'cbt_login_ip': False,
                'cbt_user_agent': False,
            })

    # ------------------------------------------------------------- login hook
    @classmethod
    def _login(cls, db, login, password, user_agent_env):
        """Enforce one active session, on every authentication entry point.

        ``session.authenticate`` is used by ``/web/login``, the JSON
        ``/web/session/authenticate`` route, signup and OAuth, so this single
        hook covers them all.
        """
        uid = super()._login(db, login, password, user_agent_env)
        if not uid:
            return uid

        token = None
        try:
            with cls.pool.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                user = env['res.users'].browse(uid)
                if not user.exists() or not user._cbt_is_portal_only():
                    return uid

                current = request.session.get('cbt_token') if request else None
                if current and user._cbt_session_matches(current):
                    # Same browser/session re-authenticating: keep the token.
                    user._cbt_touch_session(current, interval=0)
                    token = current
                else:
                    ip = ua = None
                    if request:
                        ip = request.httprequest.environ.get('REMOTE_ADDR')
                        agent = request.httprequest.user_agent
                        ua = agent.string if agent else None
                    token = user._cbt_claim_session(
                        timeout=user._cbt_timeout(), ip=ip, user_agent=ua)
                    if not token:
                        raise AccessDenied(_(
                            "This account is already logged in on another "
                            "device. Please log out there or contact the exam "
                            "administrator."))
        except AccessDenied:
            raise
        except Exception:
            _logger.exception("CBT: unable to claim the login session.")
            raise AccessDenied(_(
                "The session could not be started. Please try again."))

        if request and request.session and request.db == db:
            request.session['cbt_token'] = token
        return uid
