from odoo import http
from odoo.http import request
from datetime import date


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