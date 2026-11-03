def post_init_hook(env):
    """Grant CBT administrator access to Odoo's main admin on first install."""
    user = env.ref("base.user_admin").sudo()
    group = env.ref("cbt.group_cbt_admin")
    if group not in user.groups_id:
        user.write({"groups_id": [(4, group.id)]})
