from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    group_migrations = (
        ('cbt.group_cbt_user', 'cbt_portal.group_cbt_user'),
        ('cbt.group_cbt_admin', 'cbt_portal.group_cbt_admin'),
    )
    for source_xmlid, target_xmlid in group_migrations:
        source_group = env.ref(source_xmlid, raise_if_not_found=False)
        target_group = env.ref(target_xmlid, raise_if_not_found=False)
        if source_group and target_group:
            users = env['res.users'].sudo().with_context(
                active_test=False).search([
                ('groups_id', 'in', source_group.id),
            ])
            users.write({'groups_id': [(4, target_group.id)]})
