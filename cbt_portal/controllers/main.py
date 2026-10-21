from odoo import http
from odoo.http import request
from datetime import date


def cbt_session_valid(request):
	"""Validate the CBT single-session token for portal participants.

	Internal/admin users are always valid.  On mismatch the session is
	destroyed so the next navigation lands on the login page.
	"""
	uid = request.session.uid
	if not uid:
		return False
	user = request.env['res.users'].sudo().browse(uid).exists()
	if not user:
		return False
	if not user._cbt_is_portal_only():
		return True
	token = request.session.get('cbt_token')
	stored = user.sudo().cbt_session_token
	if not token or not stored or token != stored:
		request.session.logout(keep_db=True)
		return False
	user.sudo()._cbt_touch_session(token)
	return True


def prepare_portal_values(request):
	company = request.env.user.company_id
	partner = request.env.user.partner_id

	participant = request.env.user
	if not participant:
		values = {
			'error_message' : 'Unauthorized Access',
		}
		return values, False, False
	else:
		values = {
			# 'menus': menus,
			'participant': participant,
			'partner': partner,
			'name': partner.name,
			'company': company or False,
			# 'notifications': noti,
			# 'config_term': config_term,
			# 'alerts':alerts,
			# 'color': color,
			'user': request.env.user,
			# 'term': term,
		}
	return values, True, participant