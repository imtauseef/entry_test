from odoo import http, tools, _, SUPERUSER_ID
from odoo.http import request

from odoo.addons.portal.controllers.web import Home
from odoo.addons.website.controllers.main import Website

class MyWebsite(Home):
    @http.route(website=True, auth="public", sitemap=False)
    def web_login(self, redirect=None, *args, **kw):
        response = super(MyWebsite, self).web_login(redirect=redirect, *args, **kw)
        if not redirect and request.params['login_success']:
            user = request.env['res.users'].browse(request.uid)

            # employee = request.env['odoocms.faculty.staff'].sudo().search([('user_id', '=', user.id)])
            # student = request.env['odoocms.student'].sudo().search([('user_id', '=', user.id)])
            if user.has_group('base.group_portal'):
                return request.redirect('/' + 'cbt' + '/home')

            redirect = '/web?' + request.httprequest.query_string.decode()
            return request.redirect(redirect)

        # if user.has_group('base.group_portal') and user.user_type == 'faculty':
        # 	return request.redirect('/faculty/dashboard')
        # if user.has_group('base.group_portal') and user.user_type == 'student':
        # 	return request.redirect('/student/dashboard')
        # if user.has_group('base.group_portal') and user.user_type == 'employee':
        # 	return request.redirect('/employee/dashboard')
        # if user.has_group('base.group_portal') and user.user_type == 'external':
        # 	return request.redirect('/external/dashboard')

        # return http.redirect(self._login_redirect(uid, redirect=redirect))

        # if request.env['res.users'].browse(request.uid).has_group('base.group_user'):
        # 	redirect = b'/web?' + request.httprequest.query_string
        # else:
        # 	redirect = '/my'
        # return http.redirect(redirect)
        return response