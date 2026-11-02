# -*- coding: utf-8 -*-
"""CBT User Rights: per-user, per-menu access configuration.

The feature discovers every menu that belongs to the CBT application at
runtime, maps each menu to the model(s) it operates on, and stores an
explicit ``Visible / Read / Write / Create`` configuration per user and per
menu.

Enforcement is done with real Odoo security primitives:

* **Visible**  -> membership of a dedicated ``res.groups`` attached to the
  menu through ``ir.ui.menu.groups_id``.
* **Read / Write / Create** -> membership of dedicated ``res.groups`` that own
  an ``ir.model.access`` line granting exactly one permission on the mapped
  model.

Nothing is enforced from the client side only: hiding a button is never used
as a substitute for an access check.
"""

import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

# Root menu of the CBT application.
CBT_ROOT_XMLID = "cbt.cbt_menu_root"

# Legacy, broad CBT groups.  They are *removed* from managed (non admin)
# users so that the per menu configuration is the single source of truth.
LEGACY_CBT_GROUP_XMLIDS = [
    "cbt.group_cbt_faculty",
    "cbt.group_cbt_creator",
    "cbt.group_cbt_reviewer",
    "cbt.group_cbt_user",
    "cbt.group_cbt_admin",
]

GROUP_PREFIX = "CBT Access :: "

PERM_FIELDS = ("can_write", "can_create")


# --------------------------------------------------------------------------- #
# Helpers shared by the models below
# --------------------------------------------------------------------------- #
def _group_users(group):
    """Return every user that inherits ``group`` (direct + implied)."""
    users = group.users
    seen = group
    todo = group.implied_ids
    while todo:
        users |= todo.users
        seen |= todo
        todo = todo.implied_ids - seen
    return users


class CbtModelSecurity(models.Model):
    """One row per CBT model, holding the three permission groups + ACLs."""

    _name = "cbt.model.security"
    _description = "CBT Model Access Configuration"
    _order = "name"

    name = fields.Char("Technical Name", required=True)
    model_id = fields.Many2one(
        "ir.model", "Model", required=True, ondelete="cascade", index=True)
    model_name = fields.Char(related="model_id.model", store=True)
    group_read_id = fields.Many2one("res.groups", "Read Group", copy=False)
    group_write_id = fields.Many2one("res.groups", "Write Group", copy=False)
    group_create_id = fields.Many2one("res.groups", "Create Group", copy=False)
    access_read_id = fields.Many2one(
        "ir.model.access", "Read ACL", copy=False, ondelete="set null")
    access_write_id = fields.Many2one(
        "ir.model.access", "Write ACL", copy=False, ondelete="set null")
    access_create_id = fields.Many2one(
        "ir.model.access", "Create ACL", copy=False, ondelete="set null")
    menu_ids = fields.Many2many(
        "cbt.menu.security", "cbt_menu_model_rel",
        "model_security_id", "menu_security_id", string="Menus")
    menu_count = fields.Integer(compute="_compute_menu_count")

    _sql_constraints = [
        ("model_security_uniq", "unique(model_id)",
         "This CBT model is already configured."),
    ]

    def _compute_menu_count(self):
        for rec in self:
            rec.menu_count = len(rec.menu_ids)

    # -- group / ACL helpers ------------------------------------------------ #
    @api.model
    def _ensure_group(self, name):
        Group = self.env["res.groups"].sudo()
        group = Group.search([("name", "=", name)], limit=1)
        if not group:
            group = Group.create({"name": name})
        return group

    def _ensure_acl(self, model, perm, group):
        """Create (idempotently) a single-permission ACL line."""
        Access = self.env["ir.model.access"].sudo()
        name = "cbt_menu_access_%s_%s" % (model.model.replace(".", "_"), perm)
        vals = {
            "name": name,
            "model_id": model.id,
            "group_id": group.id,
            "perm_read": perm == "read",
            "perm_write": perm == "write",
            "perm_create": perm == "create",
            "perm_unlink": False,
        }
        acl = Access.search([("name", "=", name)], limit=1)
        if not acl:
            return Access.create(vals)
        # Only touch the ACL when a value really changed: writing an
        # ``ir.model.access`` row flushes and invalidates the whole ACL cache
        # and makes every following request very slow (the save appears to
        # hang when this happens on every write).
        if acl.group_id.id != group.id or acl.model_id.id != model.id or \
                acl.perm_read != vals["perm_read"] or \
                acl.perm_write != vals["perm_write"] or \
                acl.perm_create != vals["perm_create"] or \
                acl.perm_unlink != vals["perm_unlink"]:
            acl.write(vals)
        return acl

    def _provision(self):
        """Make sure groups and ACL lines exist for this model security."""
        self.ensure_one()
        model = self.model_id
        if not self.group_read_id:
            self.group_read_id = self._ensure_group(
                "%s%s (Read)" % (GROUP_PREFIX, model.model))
        if not self.group_write_id:
            self.group_write_id = self._ensure_group(
                "%s%s (Write)" % (GROUP_PREFIX, model.model))
        if not self.group_create_id:
            self.group_create_id = self._ensure_group(
                "%s%s (Create)" % (GROUP_PREFIX, model.model))
        if not self.access_read_id:
            self.access_read_id = self._ensure_acl(
                model, "read", self.group_read_id)
        if not self.access_write_id:
            self.access_write_id = self._ensure_acl(
                model, "write", self.group_write_id)
        if not self.access_create_id:
            self.access_create_id = self._ensure_acl(
                model, "create", self.group_create_id)
        return self

    @api.model
    def _related_models(self, model):
        """Models reachable from ``model`` through relational fields.

        A user who may read ``model`` must also be able to read the name of
        every record selectable on its fields (``many2one`` / ``many2many``)
        and the lines it contains (``one2many``), otherwise opening the form
        raises an "You are not allowed to access ... records" error as soon as
        a related value is displayed or selected.
        """
        IrModel = self.env["ir.model"].sudo()
        comodels = set()
        if model.model == 'cbt.paper.criteria':
            for mname in ['cbt.paper.criteria.rule', 'cbt.paper.criteria.rule.topic',
                          'cbt.paper.criteria.rule.difficulty', 'cbt.paper.criteria.rule.type']:
                comodels.add(mname)
        if model.model == 'cbt.center':
            comodels.add('cbt.slot')
        for field in model.field_id:
            comodel = getattr(field, "relation", False)
            if not comodel:
                continue
            if comodel in ("res.users", "res.partner", "ir.model",
                           "ir.model.fields", "ir.ui.menu",
                           "ir.actions.act_window", "ir.actions.actions"):
                continue
            # Skip the mail / framework plumbing: it is not part of the
            # business form and pulling it in would explode the read chain.
            if comodel.startswith(("mail.", "ir.", "base.", "web.")):
                continue
            comodels.add(comodel)
        if not comodels:
            return IrModel.browse()
        return IrModel.search([("model", "in", list(comodels))])

    def _related_models_editable(self, model):
        """Models reachable through one2many/many2many fields from ``model``."""
        IrModel = self.env["ir.model"].sudo()
        comodels = set()
        if model.model == 'cbt.paper.criteria':
            for mname in ['cbt.paper.criteria.rule', 'cbt.paper.criteria.rule.topic',
                          'cbt.paper.criteria.rule.difficulty', 'cbt.paper.criteria.rule.type']:
                comodels.add(mname)
        if model.model == 'cbt.center':
            comodels.add('cbt.slot')
        for field in model.field_id:
            if field.ttype not in ("one2many", "many2many"):
                continue
            comodel = getattr(field, "relation", False)
            if not comodel:
                continue
            if comodel in ("res.users", "res.partner", "ir.model",
                           "ir.model.fields", "ir.ui.menu",
                           "ir.actions.act_window", "ir.actions.actions"):
                continue
            if comodel.startswith(("mail.", "ir.", "base.", "web.")):
                continue
            comodels.add(comodel)
        if not comodels:
            return IrModel.browse()
        return IrModel.search([("model", "in", list(comodels))])

    def _ensure_write_chain(self, model, seen=None):
        """Ensure write/create groups/ACLs exist for editable related models."""
        model_security = self.env["cbt.model.security"].sudo()
        if seen is None:
            seen = set()
        if model.model in seen:
            return model_security.browse()
        seen.add(model.model)

        row = model_security.search([("model_id", "=", model.id)], limit=1)
        if not row:
            row = model_security.create(
                {"name": model.model, "model_id": model.id})
        row._provision()

        rows = row
        if model.model.startswith("cbt.") or model.model == 'cbt.paper.criteria':
            for related in self._related_models_editable(model):
                rows |= model_security._ensure_write_chain(related, seen)
        return rows

    def _ensure_read_chain(self, model, seen=None):
        """Ensure this model and every related model have a Read group/ACL.

        Returns the recordset of ``cbt.model.security`` rows that must be
        granted (read) to a user who is granted this model.

        The walk only recurses inside the ``cbt.`` namespace; external models
        (``hr.*``, ``res.*`` ...) are added as leaves so the chain stays small
        and provisioning does not explode on every save.
        """
        model_security = self.env["cbt.model.security"].sudo()
        if seen is None:
            seen = set()
        if model.model in seen:
            return model_security.browse()
        seen.add(model.model)

        row = model_security.search([("model_id", "=", model.id)], limit=1)
        if not row:
            row = model_security.create(
                {"name": model.model, "model_id": model.id})
        row._provision()

        rows = row
        if model.model.startswith("cbt.") or model.model == 'cbt.paper.criteria':
            for related in self._related_models(model):
                rows |= model_security._ensure_read_chain(related, seen)
        return rows


class CbtMenuSecurity(models.Model):
    """One row per CBT menu.  Auto discovered, never created by hand."""

    _name = "cbt.menu.security"
    _description = "CBT Menu Access Configuration"
    _order = "sequence, id"

    menu_id = fields.Many2one(
        "ir.ui.menu", "Menu", required=True, ondelete="cascade", index=True)
    name = fields.Char("Menu Name")
    complete_name = fields.Char("Full Menu Path")
    menu_label = fields.Char(
        "Indented Menu", compute="_compute_labels", store=True)
    parent_security_id = fields.Many2one(
        "cbt.menu.security", "Parent Menu", ondelete="cascade")
    sequence = fields.Integer(default=10)
    depth = fields.Integer(default=0)
    is_leaf = fields.Boolean("Has Action", default=False)
    group_visible_id = fields.Many2one(
        "res.groups", "Visibility Group", copy=False)
    model_security_ids = fields.Many2many(
        "cbt.model.security", "cbt_menu_model_rel",
        "menu_security_id", "model_security_id", string="Mapped Models")
    models_label = fields.Char(
        "Models", compute="_compute_labels", store=True)
    has_models = fields.Boolean(compute="_compute_labels", store=True)

    _sql_constraints = [
        ("menu_security_uniq", "unique(menu_id)",
         "This CBT menu is already configured."),
    ]

    @api.depends("complete_name", "depth", "model_security_ids")
    def _compute_labels(self):
        for rec in self:
            rec.menu_label = "%s%s" % ("    " * (rec.depth or 0),
                                       rec.complete_name or rec.name or "")
            models = rec.model_security_ids.mapped("model_name")
            rec.models_label = ", ".join(models) if models else ""
            rec.has_models = bool(models)

    @api.model
    def _cbt_default_right_rows(self):
        """Virtual permission rows for a brand new CBT user.

        They are returned as default values of the ``cbt_right_ids`` field so
        that the manager sees the whole CBT menu list on the new user form and
        can tick the menus before saving.  The rows are real records only once
        the user itself has been created.
        """
        rows = []
        seen_menus = set()
        secs = self.sudo().search(
            [("model_security_ids", "!=", False)], order="sequence, id")
        for sec in secs:
            menu_id = sec.menu_id.id
            # A menu may be described twice (duplicated security record):
            # keep a single permission row per menu, otherwise the unique
            # (user, menu) constraint rejects the whole batch.
            if not menu_id or menu_id in seen_menus:
                continue
            seen_menus.add(menu_id)
            rows.append({
                "menu_id": menu_id,
                "menu_security_id": sec.id,
                "menu_label": sec.menu_label,
                "models_label": sec.models_label,
                "has_models": sec.has_models,
                "can_see": False,
                "can_read": False,
                "can_write": False,
                "can_create": False,
            })
        return rows

    @api.model
    def _cbt_menu_subtree(self, secs):
        """Return ``secs`` plus every descendant (iterative, cycle safe)."""
        result = self.browse()
        seen = set()
        pending = self.browse(secs.ids)
        while pending:
            batch = pending
            pending = self.browse()
            for node in batch:
                if not node.id or node.id in seen:
                    continue
                seen.add(node.id)
                result |= node
                pending |= self.search([("parent_security_id", "=", node.id)])
        return result

    # ------------------------------------------------------------------ #
    # Menu discovery
    # ------------------------------------------------------------------ #
    @api.model
    def _cbt_root_menu(self):
        Menu = self.env["ir.ui.menu"].sudo()
        root = self.env.ref(CBT_ROOT_XMLID, raise_if_not_found=False)
        if root:
            return root

        # Fallback: top most ancestor shared by every cbt.* action menu.
        tops = {}
        for menu in Menu.search([("action", "!=", False)]):
            action = menu.action
            model = False
            model_id = getattr(action, "model_id", False) if action else False
            if model_id:
                model = model_id.model
            elif action and hasattr(action, "res_model"):
                model = action.res_model
            if not model or not model.startswith("cbt."):
                continue
            node = menu
            while node.parent_id:
                node = node.parent_id
            tops[node.id] = tops.get(node.id, 0) + 1
        if not tops:
            return Menu
        return Menu.browse(max(tops, key=tops.get))

    @api.model
    def _cbt_menus(self):
        """Every menu of the CBT application, parents first."""
        Menu = self.env["ir.ui.menu"].sudo()
        root = self._cbt_root_menu()
        if not root:
            return Menu
        menus = Menu.search([
            "|",
            ("id", "=", root.id),
            ("parent_path", "=like", (root.parent_path or "") + "%"),
        ])
        # The User Rights screen itself is an administration menu: it must
        # never become subject to the per user configuration it controls.
        # manager_group = self.env.ref("cbt.group_cbt_rights_manager",
        #                              raise_if_not_found=False)
        # if manager_group:
        #     menus = menus.filtered(
        #         lambda m: manager_group not in m.groups_id)
        return menus.sorted(
            key=lambda m: (m.parent_path or "", m.sequence or 0, m.id))

    @api.model
    def _cbt_configurable_menus(self):
        """Only the menus that operate on a model are configurable.

        Parent / container menus (no action, no model) are never offered as
        a permission row: they are granted automatically as soon as one of
        their children is granted.
        """
        return self._cbt_menus().filtered(
            lambda m: bool(self.sudo()._menu_models(m)))

    # ------------------------------------------------------------------ #
    # Menu -> model mapping
    # ------------------------------------------------------------------ #
    @api.model
    def _menu_models(self, menu):
        """Models actually used by the action attached to ``menu``."""
        IrModel = self.env["ir.model"].sudo()
        models = IrModel.browse()
        action = menu.action
        if not action:
            return models

        model_id = getattr(action, "model_id", False)
        if model_id:
            models |= model_id
        elif hasattr(action, "res_model") and action.res_model:
            models |= IrModel.search([("model", "=", action.res_model)],
                                     limit=1)

        # Wizards / transient models launched by the action.
        if hasattr(action, "binding_model_id") and action.binding_model_id:
            models |= action.binding_model_id
        return models

    # ------------------------------------------------------------------ #
    # Synchronisation
    # ------------------------------------------------------------------ #
    @api.model
    def _get_or_create_menu_security(self, menu):
        sec = self.sudo().search([("menu_id", "=", menu.id)], limit=1)
        if sec:
            return sec, False
        parent_sec = False
        if menu.parent_id:
            parent_sec = self.sudo().search(
                [("menu_id", "=", menu.parent_id.id)], limit=1)
            if not parent_sec:
                parent_sec, _ = self._get_or_create_menu_security(
                    menu.parent_id)
        depth = 0
        node = menu.parent_id
        while node:
            depth += 1
            node = node.parent_id
        sec = self.sudo().create({
            "menu_id": menu.id,
            "name": menu.name,
            "complete_name": menu.complete_name or menu.name,
            "parent_security_id": parent_sec and parent_sec.id or False,
            "sequence": menu.sequence or 10,
            "depth": depth,
            "is_leaf": bool(menu.action),
        })
        return sec, True

    @api.model
    def _ensure_menu_groups(self, menu, sec):
        """Attach the visibility group (and keep the admin group) on the menu.

        The original groups are preserved so that nobody loses access while
        the feature is being configured.
        """
        admin_group = self.env.ref("cbt.group_cbt_admin",
                                   raise_if_not_found=False)
        commands = []
        if sec.group_visible_id:
            commands.append((4, sec.group_visible_id.id))
        if admin_group:
            commands.append((4, admin_group.id))
        if commands:
            menu.sudo().write({"groups_id": commands})

    @api.model
    def _grant_initial_visibility(self, menu, sec):
        """Give the visibility group to everybody who can see the menu today.

        Without this step, attaching a group to a menu that previously had
        none would immediately hide it from every existing user.
        """
        if not sec.group_visible_id:
            return
        if menu.groups_id:
            viewers = self.env["res.users"].sudo().browse()
            for group in menu.groups_id:
                viewers |= _group_users(group)
        else:
            viewers = self.env.ref("base.group_user").users
        commands = [(4, u.id) for u in viewers]
        if commands:
            sec.group_visible_id.sudo().write({"users": commands})

    @api.model
    def sync_all(self, reapply=True):
        """(Re)discover CBT menus and refresh groups, ACLs and rights.

        When ``reapply`` is false only the menu discovery / provisioning part
        runs (cheap); the per user rights are left untouched.  Used when the
        User Rights form is opened, so the menu list is fresh without a full
        recomputation of every managed user.
        """
        MenuSec = self.sudo()
        menus = self._cbt_menus()
        if not menus:
            _logger.warning("CBT User Rights: no CBT menu found, skipping "
                            "synchronisation.")
            return False

        model_security = self.env["cbt.model.security"].sudo()
        created_menus = 0

        for menu in menus:
            sec, created = MenuSec._get_or_create_menu_security(menu)
            if created:
                created_menus += 1
            sec.menu_id = menu.id
            sec.name = menu.name
            sec.complete_name = menu.complete_name or menu.name

            if not sec.group_visible_id:
                sec.group_visible_id = self.env[
                    "cbt.model.security"]._ensure_group(
                        "%s%s (Visible)" % (GROUP_PREFIX,
                                            menu.complete_name or menu.name))

            # Map the models used by this menu.
            models = self._menu_models(menu)
            ms_rows = model_security.browse()
            for model in models:
                row = model_security.search(
                    [("model_id", "=", model.id)], limit=1)
                if not row:
                    row = model_security.create({
                        "name": model.model,
                        "model_id": model.id,
                    })
                row = row._provision()
                ms_rows |= row
            sec.model_security_ids = [(6, 0, ms_rows.ids)]

            # Grant the visibility group to today's viewers *before* the
            # group is attached to the menu, otherwise the freshly created
            # (empty) group would hide the menu from everybody.
            if created:
                self._grant_initial_visibility(menu, sec)
            self._ensure_menu_groups(menu, sec)

        # Drop rows for menus that disappeared from the CBT application.
        stale = MenuSec.search([("menu_id", "not in", menus.ids)])
        if stale:
            stale.unlink()

        # Only model bearing menus are configurable: remove any stored
        # permission row that points at a parent/container menu.
        configurable = self._cbt_configurable_menus()
        stale_rights = self.env["cbt.user.right"].sudo().search([
            ("menu_id", "not in", configurable.ids)])
        if stale_rights:
            stale_rights.unlink()

        if reapply:
            # The permission rows carry their own copy of the menu labels (they
            # are plain fields so the web client can use them on a new user
            # form): keep them in sync when a menu is renamed.
            rights_model = self.env["cbt.user.right"].sudo()
            rights_model._refresh_labels(rights_model.search([]))
            self._reapply_all_user_rights()
        _logger.info("CBT User Rights: synchronised %s menus (%s new).",
                     len(menus), created_menus)
        return True

    @api.model
    def _managed_groups(self):
        """Every group managed by this feature (visibility + permissions)."""
        groups = self.env["res.groups"].sudo().browse()
        for sec in self.sudo().search([]):
            if sec.group_visible_id:
                groups |= sec.group_visible_id
            for ms in sec.model_security_ids:
                groups |= ms.group_read_id
                groups |= ms.group_write_id
                groups |= ms.group_create_id
        managed = self.env.ref("cbt.group_cbt_managed",
                               raise_if_not_found=False)
        if managed:
            groups |= managed
        return groups

    @api.model
    def _legacy_groups(self):
        groups = self.env["res.groups"].sudo().browse()
        for xmlid in LEGACY_CBT_GROUP_XMLIDS:
            group = self.env.ref(xmlid, raise_if_not_found=False)
            if group:
                groups |= group
        return groups

    @api.model
    def _implied_closure(self, groups):
        """``groups`` plus every group they imply, directly or transitively."""
        todo = groups
        seen = self.env["res.groups"].sudo().browse()
        while todo:
            implied = todo.implied_ids
            seen |= todo
            todo = implied - seen
        return seen

    @api.model
    def _is_cbt_faculty_user(self, user):
        user = self.env["res.users"].sudo().browse(user.id)
        if not user:
            return False
        if (user.cbt_role or "admin") == "faculty":
            return True
        Role = self.env["cbt.employee.role"].sudo()
        try:
            return bool(Role.search_count(Role._cbt_user_domain(user)))
        except Exception:
            return False

    @api.model
    def _allowed_managed_groups(self, user, desired):
        """Groups a locked CBT user may keep.

        Anything the user is explicitly granted here (``desired``) plus the
        groups those imply, plus the strict minimum Odoo needs for an internal
        user to log in and reach the web client.  Everything else is stripped,
        so a user created from the User Rights screen can only move through the
        menus granted here.
        """
        allowed = self._implied_closure(desired)
        # Never strip the internal user prerequisite nor the base groups the
        # web client / login rely on.
        for xmlid in ("base.group_user",):
            group = self.env.ref(xmlid, raise_if_not_found=False)
            if group:
                allowed |= group
        # Faculty users must keep their faculty/creator/reviewer groups so the
        # CBT app and question bank menus remain accessible.
        if self._is_cbt_faculty_user(user):
            for xmlid in ("cbt.group_cbt_managed", "cbt.group_cbt_faculty",
                          "cbt.group_cbt_creator", "cbt.group_cbt_reviewer"):
                group = self.env.ref(xmlid, raise_if_not_found=False)
                if group:
                    allowed |= group
        else:
            managed = self.env.ref("cbt.group_cbt_managed",
                                   raise_if_not_found=False)
            if managed:
                allowed |= managed
        return allowed

    @api.model
    def _user_model_perm(self, user, model, perm):
        """Approximate Odoo's ACL check for ``user`` on ``model``/``perm``.

        Used only to snapshot a user's *current* effective access when the
        menus are loaded, so that moving the user to the managed permission
        scheme does not change what they can already do.
        """
        field = "perm_%s" % perm
        acls = self.env["ir.model.access"].sudo().search(
            [("model_id", "=", model.id), (field, "=", True)])
        for acl in acls:
            if not acl.group_id:
                return True
            if _group_users(acl.group_id) & user:
                return True
        return False

    @api.model
    def _user_can_see_menu(self, user, menu):
        """Whether ``user`` can currently see ``menu``."""
        if not menu.groups_id:
            return True
        for group in menu.groups_id:
            if _group_users(group) & user:
                return True
        return False

    @api.model
    def _is_protected_user(self, user):
        """Admins keep their legacy rights and are never re-scoped."""
        for xmlid in ("cbt.group_cbt_admin", "cbt.group_cbt_rights_manager",
                      "base.group_system"):
            group = self.env.ref(xmlid, raise_if_not_found=False)
            if group and group in user.groups_id:
                return True
        return False

    @api.model
    def _reapply_all_user_rights(self):
        users = self.env["res.users"].sudo().search(
            [("cbt_right_ids", "!=", False)])
        for user in users:
            self._apply_user_rights(user)

    @api.model
    def _apply_user_rights(self, user):
        """Recompute the managed group membership of ``user``."""
        user = self.env["res.users"].sudo().browse(user.id)
        rights = self.env["cbt.user.right"].sudo().search(
            [("user_id", "=", user.id)])

        # Make sure the permission groups / ACLs exist and the menus are
        # mapped to their *current* models before we compute the
        # memberships, so a freshly granted menu can never end up without
        # its Read group (or with a stale one).
        model_security = self.env["cbt.model.security"].sudo()
        related_rows = model_security.browse()
        for right in rights:
            sec = self.sudo().search(
                [("menu_id", "=", right.menu_id.id)], limit=1)
            if not (sec and right.can_see):
                continue
            models = self._menu_models(sec.menu_id)
            rows = model_security.browse()
            for model in models:
                row = model_security.search(
                    [("model_id", "=", model.id)], limit=1)
                if not row:
                    row = model_security.create({
                        "name": model.model, "model_id": model.id})
                rows |= row._provision()
                # A readable model must keep its related models readable too,
                # otherwise any many2one / one2many on the form raises an
                # access error when its value is displayed.
                if right.can_read:
                    related_rows |= model_security._ensure_read_chain(model)
            if set(rows.ids) != set(sec.model_security_ids.ids):
                sec.model_security_ids = [(6, 0, rows.ids)]

        desired = self.env["res.groups"].sudo().browse()
        home_action = self.env["ir.actions.actions"].sudo().browse()
        write_main_models = self.env["ir.model"].sudo().browse()
        create_main_models = self.env["ir.model"].sudo().browse()
        ordered_rights = rights.sorted(
            key=lambda r: (r.menu_security_id.sequence or 0,
                           r.menu_security_id.id or 0))
        for right in ordered_rights:
            sec = self.sudo().search(
                [("menu_id", "=", right.menu_id.id)], limit=1)
            if not sec:
                continue
            if right.can_see and sec.group_visible_id:
                desired |= sec.group_visible_id
                if not home_action and sec.menu_id.action:
                    home_action = sec.menu_id.action
                # Ancestors must stay visible for the child menu to show up.
                parent = sec.parent_security_id
                while parent:
                    if parent.group_visible_id:
                        desired |= parent.group_visible_id
                    parent = parent.parent_security_id
            # Parent menus have no mapped model: Read/Write/Create are no-ops.
            if not sec.has_models:
                continue
            for ms in sec.model_security_ids:
                if right.can_read and ms.group_read_id:
                    desired |= ms.group_read_id
                if right.can_write:
                    if ms.group_write_id:
                        desired |= ms.group_write_id
                    write_main_models |= ms.model_id
                if right.can_create:
                    if ms.group_create_id:
                        desired |= ms.group_create_id
                    create_main_models |= ms.model_id

        # Keep every model reachable from a readable form readable, so the
        # many2one / one2many values of granted menus never raise an access
        # error (e.g. selecting a Sub Topic on the Faculty Roles form).
        for row in related_rows:
            if row.group_read_id:
                desired |= row.group_read_id

        # Propagate to editable one2many/many2many - hardcode for paper criteria
        for model in write_main_models | create_main_models:
            if model.model == 'cbt.paper.criteria':
                for mname in ['cbt.paper.criteria.rule', 'cbt.paper.criteria.rule.topic',
                              'cbt.paper.criteria.rule.difficulty', 'cbt.paper.criteria.rule.type']:
                    im = self.env['ir.model'].sudo().search([('model', '=', mname)], limit=1)
                    if not im:
                        continue
                    rrow = model_security.search([('model_id', '=', im.id)], limit=1)
                    if not rrow:
                        rrow = model_security.create({'name': im.model, 'model_id': im.id})
                    rrow = rrow._provision()
                    if model in write_main_models and rrow.group_write_id:
                        desired |= rrow.group_write_id
                        if rrow.group_read_id:
                            desired |= rrow.group_read_id
                    if model in create_main_models:
                        if rrow.group_create_id:
                            desired |= rrow.group_create_id
                        if rrow.group_write_id:
                            desired |= rrow.group_write_id
                        if rrow.group_read_id:
                            desired |= rrow.group_read_id
            elif model.model == 'cbt.center':
                for mname in ['cbt.slot']:
                    im = self.env['ir.model'].sudo().search(
                        [('model', '=', mname)], limit=1)
                    if not im:
                        continue

                    rrow = model_security.search(
                        [('model_id', '=', im.id)], limit=1)

                    if not rrow:
                        rrow = model_security.create({
                            'name': im.model,
                            'model_id': im.id
                        })

                    rrow = rrow._provision()

                    if model in write_main_models and rrow.group_write_id:
                        desired |= rrow.group_write_id
                        if rrow.group_read_id:
                            desired |= rrow.group_read_id

                    if model in create_main_models:
                        if rrow.group_create_id:
                            desired |= rrow.group_create_id
                        if rrow.group_write_id:
                            desired |= rrow.group_write_id
                        if rrow.group_read_id:
                            desired |= rrow.group_read_id

        managed_group = self.env.ref(
            "cbt.group_cbt_managed", raise_if_not_found=False)
        if managed_group:
            desired |= managed_group

        current_managed = self._managed_groups() & user.groups_id
        to_add = desired - user.groups_id
        to_remove = current_managed - desired

        if not self._is_protected_user(user):
            # Managed non admin users must not keep broad legacy CBT rights,
            # otherwise the per menu configuration could not be enforced
            # (Odoo model access rights are additive).
            if self._is_cbt_faculty_user(user):
                # Do not strip faculty/creator/reviewer groups for faculty users
                faculty_groups = self.env["res.groups"].sudo().browse()
                for xmlid in ("cbt.group_cbt_faculty", "cbt.group_cbt_creator",
                              "cbt.group_cbt_reviewer"):
                    group = self.env.ref(xmlid, raise_if_not_found=False)
                    if group:
                        faculty_groups |= group
                to_remove = to_remove - faculty_groups
            else:
                to_remove |= self._legacy_groups() & user.groups_id
            # Users created from the User Rights screen are locked to CBT:
            # their only access is the one granted per menu here.  Every other
            # group (other applications, Settings, extra rights) is stripped,
            # and this is re-applied on every write so the user can never gain
            # anything outside the CBT menus.
            if user.cbt_managed_user:
                to_remove |= user.groups_id - self._allowed_managed_groups(user, desired)

        user_ctx = user.sudo().with_context(no_cbt_lockdown=True)
        if to_add:
            user_ctx.write({"groups_id": [(4, g.id) for g in to_add]})
        if to_remove:
            user_ctx.write({"groups_id": [(3, g.id) for g in to_remove]})

        # Managed users land straight on the CBT application (the first menu
        # they were granted) instead of the Odoo Apps dashboard.
        if not self._is_protected_user(user):
            target = home_action.id or False
            if user.action_id.id != target:
                user_ctx.write({"action_id": target})
        return True


class CbtUserRight(models.Model):
    """The stored configuration: one row per user and per CBT menu."""

    _name = "cbt.user.right"
    _description = "CBT User Menu Permission"
    _order = "menu_security_id, id"

    user_id = fields.Many2one(
        "res.users", "User",  ondelete="cascade", index=True)
    menu_id = fields.Many2one(
        "ir.ui.menu", "Menu", required=True, ondelete="cascade", index=True)
    menu_security_id = fields.Many2one(
        "cbt.menu.security", "Menu Configuration", ondelete="cascade")
    menu_label = fields.Char(
        string="Menu", store=True, readonly=True, index=True)
    models_label = fields.Char(string="Models", store=True, readonly=True)
    has_models = fields.Boolean(store=True, readonly=True)
    can_see = fields.Boolean("Visible / Read", default=False)
    can_read = fields.Boolean("Read", default=False)
    can_write = fields.Boolean("Write", default=False)
    can_create = fields.Boolean("Create", default=False)

    _sql_constraints = [
        ("user_menu_uniq", "unique(user_id, menu_id)",
         "A permission row already exists for this user and menu."),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        MenuSec = self.env["cbt.menu.security"].sudo()
        for vals in vals_list:
            # Granting a menu always grants Read: Visible and Read travel
            # together.  Write / Create stay optional and imply Visible.
            if any(vals.get(f) for f in PERM_FIELDS) or vals.get("can_read"):
                vals["can_see"] = True
            if vals.get("can_see"):
                vals["can_read"] = True
            if vals.get("menu_id") and not vals.get("menu_security_id"):
                sec = MenuSec.search(
                    [("menu_id", "=", vals["menu_id"])], limit=1)
                if not sec:
                    MenuSec.sync_all()
                    sec = MenuSec.search(
                        [("menu_id", "=", vals["menu_id"])], limit=1)
                vals["menu_security_id"] = sec.id if sec else False
            sec = MenuSec.browse(vals.get("menu_security_id"))
            if sec:
                # The labels are plain stored fields (not related) so that the
                # web client can carry them on the virtual rows of a brand new
                # user form; they are always refreshed from the menu.
                vals["menu_label"] = sec.menu_label
                vals["models_label"] = sec.models_label
                vals["has_models"] = sec.has_models
        records = super().create(vals_list)
        # When the record is created through the parent one2many, Odoo sets
        # the inverse relation (``user_id``) *after* this method returns.
        # Any write performed here would flush the record while its mandatory
        # user is still missing and raise "a mandatory field is not set", so
        # the post processing is deferred to the parent (res.users), which
        # runs it once the relation is in place.
        self._post_process(records)
        users = records.mapped("user_id")
        for user in users:
            try:
                self.env["cbt.menu.security"].sudo()._apply_user_rights(user)
            except Exception:
                pass
        return records

    @api.model
    def _post_process(self, records):
        """Normalise, cascade and apply the permissions of ``records``.

        Records whose user is not known yet (they were just created through
        the parent one2many and Odoo sets the inverse afterwards) are skipped:
        the parent calls this method again once the relation is established.
        """
        records = records.filtered(lambda r: r.user_id)
        if not records:
            return
        self._normalize(records)
        if not self.env.context.get("cbt_skip_cascade"):
            self._cascade_visibility(records.filtered("can_see"), True)
        if not self.env.context.get("no_cbt_apply"):
            self._apply(records)

    def write(self, vals):
        # Any permission granted implies Visible + Read.
        if any(vals.get(f) for f in PERM_FIELDS):
            vals["can_see"] = True
        if vals.get("can_see"):
            vals["can_read"] = True
        elif "can_see" in vals and not vals["can_see"]:
            # Hiding a menu drops every permission on it.
            vals.setdefault("can_read", False)
            vals.setdefault("can_write", False)
            vals.setdefault("can_create", False)
        res = super().write(vals)
        if "menu_security_id" in vals:
            self._refresh_labels(self)
        self._normalize(self)
        if "can_see" in vals and \
                not self.env.context.get("cbt_skip_cascade"):
            if vals["can_see"]:
                self._cascade_visibility(self.filtered("can_see"), True)
            else:
                self._cascade_visibility(self, False)
        if not self.env.context.get("no_cbt_apply"):
            self._apply(self)
        users = self.mapped("user_id")
        for user in users:
            try:
                self.env["cbt.menu.security"].sudo()._apply_user_rights(user)
            except Exception:
                pass
        return res

    def unlink(self):
        users = self.mapped("user_id")
        res = super().unlink()
        for user in users:
            try:
                self.env["cbt.menu.security"].sudo()._apply_user_rights(user)
            except Exception:
                pass
        return res

    @api.model
    def _refresh_labels(self, records):
        """Copy the menu labels onto the permission rows."""
        sec = self.env["cbt.menu.security"].sudo()
        for rec in records:
            if not rec.menu_security_id:
                values = {"menu_label": False, "models_label": False,
                          "has_models": False}
            else:
                menu = sec.browse(rec.menu_security_id)
                values = {
                    "menu_label": menu.menu_label,
                    "models_label": menu.models_label,
                    "has_models": menu.has_models,
                }
            if any(rec[field] != value for field, value in values.items()):
                super(CbtUserRight, rec).write(values)
        return records

    @api.constrains("can_see", "can_read")
    def _check_permissions(self):
        for rec in self:
            if rec.can_see != rec.can_read:
                raise ValidationError(_(
                    "Visible and Read are granted together: a menu that is "
                    "visible is always readable."))

    @api.model
    def _normalize(self, records):
        """Visible and Read are one single decision.

        A menu that is visible is always readable; a menu that is not visible
        never carries Read/Write/Create.
        """
        to_show = records.filtered(lambda r: r.can_see and not r.can_read)
        if to_show:
            to_show.sudo().write({"can_read": True})
        to_hide = records.filtered(
            lambda r: not r.can_see
            and (r.can_read or r.can_write or r.can_create))
        if to_hide:
            to_hide.sudo().write({
                "can_read": False, "can_write": False, "can_create": False,
            })

    def _cascade_visibility(self, records, visible):
        """Keep the parent/child menu visibility chain consistent.

        A child menu is only displayed by Odoo when every ancestor is visible
        too, so granting a menu also grants its whole parent path.  Hiding a
        menu hides its whole sub-tree.
        """
        Rights = self.sudo().with_context(
            no_cbt_apply=True, cbt_skip_cascade=True)
        MenuSec = self.env["cbt.menu.security"].sudo()
        for rec in records:
            sec = rec.menu_security_id
            if not sec:
                continue
            if visible:
                parent = sec.parent_security_id
                while parent:
                    rows = Rights.search([
                        ("user_id", "=", rec.user_id.id),
                        ("menu_security_id", "=", parent.id),
                    ])
                    if rows and not all(rows.mapped("can_see")):
                        rows.write({"can_see": True})
                    parent = parent.parent_security_id
            else:
                # ``cbt.menu.security`` uses ``parent_security_id`` as its
                # parent field, not ``parent_id``: ``child_of`` cannot be
                # used here (it builds a malformed domain), so the sub-tree
                # is collected by walking the relation.
                sub_tree = MenuSec._cbt_menu_subtree(sec)
                rows = Rights.search([
                    ("user_id", "=", rec.user_id.id),
                    ("menu_security_id", "in", sub_tree.ids),
                ])
                if rows:
                    rows.write({
                        "can_see": False, "can_read": False,
                        "can_write": False, "can_create": False,
                    })

    def _apply(self, records):
        users = records.mapped("user_id")
        for user in users:
            self.env["cbt.menu.security"].sudo()._apply_user_rights(user)

    # -- convenience helpers -------------------------------------------- #
    @api.model
    def auto_populate(self, users, snapshot=True):
        """Create one row per CBT menu for ``users``.

        When ``snapshot`` is true the permission columns are initialised with
        the user's *current* effective access, so enabling the managed scheme
        does not silently revoke (or grant) anything the user already had.
        When it is false (e.g. a freshly created user) every row is created
        unchecked, i.e. the user starts with access to zero menus.
        """
        MenuSec = self.env["cbt.menu.security"].sudo()
        if not MenuSec.search([], limit=1):
            MenuSec.sync_all()
        # Only model bearing menus are configurable: parent/container menus
        # are granted automatically with their children.
        secs = MenuSec.search([("model_security_ids", "!=", False)])
        # A duplicated security record must not produce two rows for the same
        # menu: the (user, menu) pair is unique.
        unique_secs = MenuSec.browse()
        seen_menus = set()
        for sec in secs:
            menu_id = sec.menu_id.id
            if not menu_id or menu_id in seen_menus:
                continue
            seen_menus.add(menu_id)
            unique_secs |= sec
        secs = unique_secs
        # Remove stale rows that point at a non configurable (parent) menu.
        # The menu is the real identity of a row, not the security record: a
        # duplicated security record must not invalidate a granted row.
        allowed_menus = secs.mapped("menu_id").ids
        if allowed_menus:
            stale = self.sudo().search([("menu_id", "not in", allowed_menus)])
            if stale:
                stale.unlink()
        created = 0
        for user in users:
            existing = self.sudo().search(
                [("user_id", "=", user.id)]).mapped("menu_id")
            missing = secs.filtered(lambda s: s.menu_id not in existing)
            vals_list = []
            for sec in missing:
                menu = sec.menu_id
                can_write = can_create = False
                can_see = False
                if snapshot:
                    models = sec.model_security_ids.mapped("model_id")
                    can_write = bool(models) and all(
                        MenuSec._user_model_perm(user, m, "write")
                        for m in models)
                    can_create = bool(models) and all(
                        MenuSec._user_model_perm(user, m, "create")
                        for m in models)
                    can_see = MenuSec._user_can_see_menu(user, menu) or \
                        can_write or can_create
                vals_list.append({
                    "user_id": user.id,
                    "menu_id": menu.id,
                    "menu_security_id": sec.id,
                    "can_see": can_see,
                    "can_read": can_see,
                    "can_write": can_write,
                    "can_create": can_create,
                })
            if vals_list:
                self.sudo().with_context(
                    no_cbt_apply=True, cbt_skip_cascade=True,
                    no_cbt_min_menu_check=True).create(vals_list)
                if not self.env.context.get("no_cbt_auto_apply"):
                    MenuSec._apply_user_rights(user)
                created += len(vals_list)
        return created


class ResUsers(models.Model):
    _inherit = ["res.users", "mail.thread", "mail.activity.mixin"]
    _name = "res.users"

    cbt_right_ids = fields.One2many(
        "cbt.user.right", "user_id", string="CBT Menu Permissions", tracking=True)
    cbt_rights_count = fields.Integer(
        compute="_compute_cbt_rights_count", string="CBT Menus")
    cbt_managed_user = fields.Boolean(
        "CBT Managed User", default=False, copy=False, tracking=True,
        help="Set when the user was created from the CBT User Rights screen. "
             "Only these users are shown in the User Rights list.")
    cbt_role = fields.Selection(
        [("admin", "Admin"), ("faculty", "Faculty")],
        string="CBT Role", default="admin", copy=False, tracking=True,
        help="Admin: manages the CBT application with the usual menus and "
             "permissions.\n"
             "Faculty: question creator / reviewer. The Faculty Roles page "
             "assigns the subjects, topics and sub topics the faculty may "
             "work on.")
    cbt_faculty_role_ids = fields.One2many(
        "cbt.employee.role", "user_id", string="Faculty Roles", tracking=True)
    login = fields.Char(tracking=True)
    password = fields.Char(tracking=True)

    def _compute_cbt_rights_count(self):
        for user in self:
            user.cbt_rights_count = len(user.cbt_right_ids)

    def _cbt_auto_load_menus(self):
        """Load all CBT menus in the Menu Assignment tab."""
        MenuSec = self.env["cbt.menu.security"].sudo()

        try:
            MenuSec.sync_all(reapply=False)
        except Exception:
            _logger.exception("CBT User Rights: menu sync failed.")

        for user in self:
            if (user.cbt_role or "admin") == "faculty":
                continue

            self.env["cbt.user.right"].sudo().with_context(
                no_cbt_auto_apply=True
            ).auto_populate(user, snapshot=False)

    def web_read(self, specification):
        # Load the menu rows *before* the record is read so the freshly
        # discovered menus show up straight away on the form.
        if self.env.context.get("cbt_user_rights_screen") and \
                not self.env.context.get("no_cbt_auto_load_menus") and \
                len(self) == 1 and (self.cbt_role or "admin") != "faculty":
            self._cbt_auto_load_menus()
        return super().web_read(specification)

    def _cbt_requires_menu(self):
        """Whether this user must keep at least one granted CBT menu."""
        self.ensure_one()
        if self.env.context.get("cbt_user_rights_screen") and (self.cbt_role or "admin") == "faculty":
            return False
        if not self.env.context.get("cbt_user_rights_screen"):
            return False
        managed = self.env.ref("cbt.group_cbt_managed",
                               raise_if_not_found=False)
        if not (managed and managed in self.groups_id):
            return False
        for xmlid in ("cbt.group_cbt_admin", "cbt.group_cbt_rights_manager",
                      "base.group_system"):
            group = self.env.ref(xmlid, raise_if_not_found=False)
            if group and group in self.groups_id:
                return False
        return True

    @api.constrains("cbt_right_ids")
    def _check_at_least_one_menu(self):
        for user in self:
            if self.env.context.get("no_cbt_min_menu_check"):
                continue
            if (user.cbt_role or "admin") == "faculty":
                continue
            if not user._cbt_requires_menu():
                continue
            if not any(r.can_see for r in user.cbt_right_ids):
                raise ValidationError(_(
                    "A CBT user must be granted access to at least one menu "
                    "before it can be saved."))

    @api.model
    def _cbt_complete_right_commands(self, commands):
        """Make sure every "create" command of a permission row carries its menu.

        The web client sends the whole row, but a row without ``menu_id``
        could not be stored (the field is mandatory).  The default rows, which
        describe the very same menu list, are used as a fallback.
        """
        default_rows = []
        result = []
        for index, item in enumerate(commands):
            # The web client normally sends real x2many commands, but when the
            # form is rendered from ``default_get`` it may echo the rows as
            # plain dictionaries: accept both shapes.
            if isinstance(item, dict):
                command = [0, 0, dict(item)]
            elif isinstance(item, (list, tuple)) and len(item) >= 3:
                command = item
            else:
                continue
            if command[0] != 0:
                result.append(tuple(command))
                continue
            values = dict(command[2] or {})
            if not values.get("menu_id"):
                if not default_rows:
                    default_rows = self.env["cbt.menu.security"].sudo().\
                        _cbt_default_right_rows()
                fallback = None
                label = values.get("menu_label")
                if label:
                    # A label is only usable as a key when it is unambiguous:
                    # several menus can share the same name ("Configuration"),
                    # and mapping them all onto one menu would insert duplicate
                    # (user, menu) rows.
                    matches = [row for row in default_rows
                               if row.get("menu_label") == label]
                    if len(matches) == 1:
                        fallback = matches[0]
                if fallback is None and index < len(default_rows):
                    fallback = default_rows[index]
                if fallback:
                    values.setdefault("menu_id", fallback.get("menu_id"))
                    values.setdefault("menu_security_id",
                                      fallback.get("menu_security_id"))
            result.append((0, 0, values))
        return result

    @api.model
    def _cbt_right_vals(self, user, commands):
        """Turn the client x2many commands into ``cbt.user.right`` values.

        Only "create" commands are meaningful here: the user does not exist
        yet when the form is submitted, so it cannot reference existing rows.
        """
        allowed = {
            "menu_id", "menu_security_id", "menu_label", "models_label",
            "has_models", "can_see", "can_read", "can_write", "can_create",
        }
        rows = {}
        order = []
        for command in commands:
            if not isinstance(command, (list, tuple)) or len(command) < 3:
                continue
            if command[0] != 0:
                continue
            values = {
                key: value
                for key, value in dict(command[2] or {}).items()
                if key in allowed
            }
            menu_id = values.get("menu_id")
            if not menu_id:
                raise ValidationError(_(
                    "A CBT menu is missing from the permission configuration."))
            values["user_id"] = user.id
            if menu_id in rows:
                # The same menu can be described several times (duplicated
                # security records or a repeated default row): keep the most
                # permissive description, the (user, menu) pair is unique.
                previous = rows[menu_id]
                for flag in ("can_see", "can_read", "can_write", "can_create"):
                    previous[flag] = bool(previous.get(flag) or values.get(flag))
                if values.get("menu_security_id"):
                    previous.setdefault("menu_security_id",
                                        values["menu_security_id"])
                continue
            rows[menu_id] = values
            order.append(menu_id)
        return [rows[menu_id] for menu_id in order]

    @api.model_create_multi
    def create(self, vals_list):
        from_screen = bool(self.env.context.get("cbt_user_rights_screen"))
        if from_screen:
            # Validate the login up-front so the manager gets a clear message
            # instead of a raw SQL/constraint error: the login must be present
            # and not already used by another user.
            for vals in vals_list:
                login = (vals.get("login") or "").strip()
                if not login:
                    raise ValidationError(_(
                        "A login is required to create a CBT user."))
                # A CBT user is created so it can sign in: leaving the password
                # empty would produce a user that can never authenticate.
                if not str(vals.get("password") or "").strip():
                    raise ValidationError(_(
                        "A password is required to create a CBT user."))
                existing = self.env["res.users"].sudo().with_context(
                    active_test=False).search(
                        [("login", "=", login)], limit=1)
                if existing:
                    raise ValidationError(_(
                        "A user with the login '%s' already exists.") % login)

        # The CBT permission rows are pulled out of the creation values and
        # applied *after* the user exists.  Creating them together with the
        # parent would insert the rows while their mandatory ``user_id`` is
        # still unknown, which makes Odoo raise "a mandatory field is not
        # set" on ``cbt.user.right``.
        rights_commands = []
        faculty_commands = []
        clean_vals = []
        for vals in vals_list:
            vals = dict(vals)
            commands = vals.pop("cbt_right_ids", None) or []
            rights_commands.append(self._cbt_complete_right_commands(commands))
            faculty = vals.pop("cbt_faculty_role_ids", None) or []
            faculty_commands.append(faculty)
            clean_vals.append(vals)

        # The "at least one menu" constraint is checked on every flush of
        # ``cbt_right_ids``.  While the rows are being assembled the user is
        # temporarily incomplete (the unchecked rows are created before the
        # ticked one is reached), so the constraint is disabled during the
        # assembly and enforced explicitly at the end of this method.
        original_env = self.env
        guarded = self.with_context(no_cbt_min_menu_check=True)
        Rights = guarded.env["cbt.user.right"].sudo()

        users = super(ResUsers, guarded).create(clean_vals)
        # Mark the users created from the User Rights screen *before* the menu
        # rights are applied: the lockdown strips every non CBT group and only
        # runs for flagged users, so the flag must be set first.
        if from_screen:
            users.sudo().write({"cbt_managed_user": True})
            users.invalidate_recordset(["cbt_managed_user"])

        # Now that the users exist, create every permission row in a single
        # batch so the parent never observes a partially configured list.
        for user, commands in zip(users, rights_commands):
            if not commands:
                continue
            rows_vals = self._cbt_right_vals(user, commands)
            if not rows_vals:
                continue
            deferred = Rights.with_context(
                no_cbt_apply=True, cbt_skip_cascade=True)
            existing = {
                row.menu_id.id: row
                for row in Rights.search([("user_id", "=", user.id)])
                if row.menu_id
            }
            to_create = []
            for values in rows_vals:
                row = existing.get(values.get("menu_id"))
                if not row:
                    to_create.append(values)
                    continue
                # A row already exists for this menu (a previous load, or a
                # duplicated command): update it instead of inserting a
                # second one, the (user, menu) pair is unique.
                flags = {
                    key: values[key]
                    for key in ("can_see", "can_read", "can_write", "can_create")
                    if key in values
                }
                if flags:
                    deferred.browse(row.id).write(flags)
            if to_create:
                deferred.create(to_create)
            Rights._post_process(Rights.search([("user_id", "=", user.id)]))

        # Faculty users: derive (or create) their hr.employee and store the
        # faculty roles that were entered on the form.  They cannot be created
        # with the user because ``cbt.employee.role`` needs the ``user_id`` of
        # the record being created.
        role_model = self.env["cbt.employee.role"]
        for user, commands in zip(users, faculty_commands):
            self._cbt_apply_faculty_roles(user, commands)
            if (user.cbt_role or "admin") == "faculty":
                role_model._sync_groups_for_users(user)
                faculty_group = self.env.ref("cbt.group_cbt_faculty",
                                             raise_if_not_found=False)
                if faculty_group and faculty_group not in user.groups_id:
                    user.sudo().write({"groups_id": [(4, faculty_group.id)]})
                self.env["cbt.menu.security"].sudo()._apply_user_rights(user)

        # Auto load the CBT menus when a new internal user is created from
        # the User Rights screen.
        if not self.env.context.get("install_mode") and \
                not self.env.context.get("no_cbt_auto_populate"):
            creator_is_manager = bool(
                self.env.user.has_group("cbt.group_cbt_rights_manager")
                or self.env.user.has_group("cbt.group_cbt_admin"))
            internal = self.env.ref("base.group_user", raise_if_not_found=False)
            for user in users:
                if not creator_is_manager:
                    continue
                # The dedicated CBT user form does not expose the Odoo groups
                # selector: make sure the user is a real internal user so the
                # managed (menu based) scheme actually applies.
                if internal and internal not in user.groups_id:
                    user.sudo().write({"groups_id": [(4, internal.id)]})
                    user.invalidate_recordset(["groups_id"])
                if internal and internal in user.groups_id:
                    if (user.cbt_role or "admin") != "faculty":
                        Rights.auto_populate(user, snapshot=False)
        # A user created from the User Rights screen must be granted at least
        # one menu; otherwise creation is refused.
        if from_screen:
            creator_is_manager = bool(
                self.env.user.has_group("cbt.group_cbt_rights_manager")
                or self.env.user.has_group("cbt.group_cbt_admin"))
            if creator_is_manager:
                for user in users:
                    if (user.cbt_role or "admin") == "faculty":
                        continue
                    granted = Rights.search_count([
                        ("user_id", "=", user.id), ("can_see", "=", True)])
                    if not granted:
                        raise ValidationError(_(
                            "Grant access to at least one CBT menu before "
                            "saving this user."))
        # Give the caller records that carry its own context back (the guard
        # above must not leak into later operations).
        return original_env["res.users"].browse(users.ids)

    def _cbt_apply_faculty_roles(self, user, commands):
        """Attach an employee to ``user`` and store its faculty role rows.

        Rows submitted through the User Rights form come as x2many commands
        but the user does not exist yet, so they are applied here, once it
        does.  ``hr.employee`` stays mandatory on ``cbt.employee.role``: it is
        reused when the user already has one and created otherwise.
        """
        if not user:
            return
        if user.cbt_role != "faculty" and not commands:
            return
        role_model = self.env["cbt.employee.role"]
        try:
            employee = role_model._cbt_employee_for_user(user.sudo())
        except Exception:
            employee = False
        allowed = {
            "subject_id", "topic_id", "subtopic_id",
            "subject_ids", "topic_ids", "subtopic_ids",
            "create_access", "review_access",
        }
        rows = []
        for command in commands or []:
            if isinstance(command, dict):
                values = dict(command)
            elif (isinstance(command, (list, tuple)) and len(command) >= 3
                    and command[0] == 0):
                values = dict(command[2] or {})
            else:
                continue
            values = {key: value for key, value in values.items()
                      if key in allowed}
            values["user_id"] = user.id
            if employee:
                values["employee_id"] = employee.id
            rows.append(values)
        if rows and employee:
            try:
                role_model.sudo().create(rows)
            except Exception:
                _logger.exception("Failed to create faculty role for user %s", user.login)
        elif rows and not employee:
            _logger.warning("Could not create faculty role for user %s: no employee", user.login)

    def _cbt_reload_action(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("User Rights"),
            "res_model": "res.users",
            "view_mode": "form",
            "res_id": self.id,
            "target": "current",
            "context": {"form_view_ref": "cbt.cbt_user_rights_form"},
        }

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        # Opening the User Rights screen must always show the current CBT menu
        # list: the menus are (re)discovered and loaded automatically instead
        # of requiring the "Load / Refresh" button.
        if self.env.context.get("cbt_user_rights_screen") and \
                (res.get("cbt_role") or "admin") == "faculty":
            fields_list = [f for f in fields_list if f not in ("cbt_right_ids",)]
        if self.env.context.get("cbt_user_rights_screen") and \
                "cbt_right_ids" in fields_list and (res.get("cbt_role") or "admin") != "faculty":
            MenuSec = self.env["cbt.menu.security"].sudo()
            try:
                MenuSec.sync_all(reapply=False)
            except Exception:
                _logger.exception("CBT User Rights: menu sync failed.")
            # A brand new user: expose the CBT menu list right away so the
            # manager can tick the menus before saving.  Those rows are
            # virtual, they only become records when the user is created.
            # They must be returned as x2many *commands*: the web client
            # replays them as-is in the ``onchange`` call (plain dictionaries
            # make the web layer raise ``KeyError: 0``).
            if not res.get("cbt_right_ids"):
                res["cbt_right_ids"] = [
                    (0, 0, row)
                    for row in MenuSec._cbt_default_right_rows()
                ]
        return res

    def action_cbt_load_menus(self):
        """(Re)discover the CBT menus and load them for this user.

        Menus are loaded unchecked: granting access is always an explicit
        decision taken by ticking the checkboxes.
        """
        self.ensure_one()
        self.env["cbt.menu.security"].sudo().sync_all()
        self.env["cbt.user.right"].sudo().auto_populate(self, snapshot=False)
        return self._cbt_reload_action()

    def action_cbt_select_all(self):
        self.ensure_one()
        if not self.cbt_right_ids:
            self.env["cbt.user.right"].sudo().auto_populate(self, snapshot=False)
        self.cbt_right_ids.sudo().write({
            "can_see": True, "can_read": True,
            "can_write": True, "can_create": True,
        })
        return self._cbt_reload_action()

    def action_cbt_deselect_all(self):
        self.ensure_one()
        self.cbt_right_ids.sudo().write({
            "can_see": False, "can_read": False,
            "can_write": False, "can_create": False,
        })
        return self._cbt_reload_action()

    def write(self, vals):
        res = super().write(vals)
        # A user switched to Faculty must own an hr.employee: the faculty
        # roles are attached to it.
        if vals.get("cbt_role") == "faculty" or "cbt_faculty_role_ids" in vals or \
                vals.get("login") or vals.get("password") or vals.get("email"):
            role_model = self.env["cbt.employee.role"]
            for user in self:
                if vals.get("email"):
                    try:
                        if user.partner_id and not user.partner_id.email:
                            user.partner_id.sudo().write({'email': vals.get('email')})
                    except Exception:
                        pass
                if (user.cbt_role or "admin") == "faculty":
                    try:
                        role_model._cbt_employee_for_user(user.sudo())
                    except Exception:
                        pass
                    faculty_group = self.env.ref("cbt.group_cbt_faculty",
                                                 raise_if_not_found=False)
                    if faculty_group and faculty_group not in user.groups_id:
                        user.sudo().write({"groups_id": [(4, faculty_group.id)]})
                    role_model._sync_groups_for_users(user)
                    if user.cbt_managed_user:
                        try:
                            self.env["cbt.menu.security"].sudo()._apply_user_rights(user)
                        except Exception:
                            pass
        # Enforce the CBT-only lockdown "afterward": whenever the group
        # membership of a user created from the User Rights screen is changed
        # (directly on the user, by an import, a script, ...), recompute its
        # access so it falls back to exactly the menus granted here and can
        # never keep anything else.
        if self.env.context.get("no_cbt_lockdown"):
            return res
        if "groups_id" in vals or "cbt_managed_user" in vals:
            managed = self.filtered(
                lambda u: u.cbt_managed_user
                and not self.env["cbt.menu.security"]._is_protected_user(u))
            if managed:
                MenuSec = self.env["cbt.menu.security"].sudo().with_context(
                    no_cbt_lockdown=True)
                for user in managed:
                    MenuSec._apply_user_rights(user)
        return res
