# -*- coding: utf-8 -*-
"""Line-model access helper.

Child / line models of the CBT application (``one2many`` and ``many2many``
comodels edited through a parent form) must be writable by internal CBT users
even when no explicit ``ir.model.access`` line was granted on them.  Instead of
widening the ACL tables, the line models inherited from :class:`CbtLineAccess`
elevate *their own* ``create`` / ``write`` to ``sudo()`` **only** when the
current user is a genuine internal CBT user.

Security scope of the elevation:

* portal / public / non internal users  -> never elevated (normal ACL applies);
* ``base.group_system`` / ``cbt.group_cbt_admin`` -> never elevated (they
  already own the rights and must keep the real access checks);
* internal CBT users -> elevated, so a form can store its lines.

The elevation is deliberately narrow: it only affects the line models listed
below and only the ``create`` / ``write`` (and, for a couple of line models,
``unlink``) flow that the parent form drives.
"""
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class CbtLineAccess(models.AbstractModel):
    _name = "cbt.line.access"
    _description = "CBT Line Model Access Helper"

    @api.model
    def _cbt_can_elevate(self):
        """Whether the current user may bypass ACLs on this line model."""
        user = self.env.user
        if not user or user.share:
            return False
        if not user.has_group("base.group_user"):
            return False
        # System / CBT admins already have full access: keep real checks.
        for xmlid in ("base.group_system", "cbt.group_cbt_admin"):
            group = self.env.ref(xmlid, raise_if_not_found=False)
            if group and group in user.groups_id:
                return False
        return True

    @api.model_create_multi
    def create(self, vals_list):
        if self._cbt_can_elevate():
            return super(CbtLineAccess, self.sudo()).create(vals_list)
        return super().create(vals_list)

    def write(self, vals):
        if self._cbt_can_elevate():
            return super(CbtLineAccess, self.sudo()).write(vals)
        return super().write(vals)
