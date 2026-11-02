# -*- coding: utf-8 -*-
"""CBNET 0.2: faculty roles become multi-select.

The former ``cbt.employee.role`` rows only stored a single
``subject_id`` / ``topic_id`` / ``subtopic_id`` and were linked to the user
through ``hr.employee.user_id``.  They are copied into the new many2many
relation tables and the ``user_id`` of each role is filled so the question
permission checks keep granting the same access.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        # Fresh install: the tables are empty and the user flag gets its
        # default value from the field definition.
        return

    _logger.info("CBT: migrating faculty roles to the multi-select fields.")

    cr.execute("""
        INSERT INTO cbt_employee_role_subject_rel (role_id, subject_id)
        SELECT id, subject_id
          FROM cbt_employee_role
         WHERE subject_id IS NOT NULL
        ON CONFLICT DO NOTHING
    """)
    cr.execute("""
        INSERT INTO cbt_employee_role_topic_rel (role_id, topic_id)
        SELECT id, topic_id
          FROM cbt_employee_role
         WHERE topic_id IS NOT NULL
        ON CONFLICT DO NOTHING
    """)
    cr.execute("""
        INSERT INTO cbt_employee_role_subtopic_rel (role_id, subtopic_id)
        SELECT id, subtopic_id
          FROM cbt_employee_role
         WHERE subtopic_id IS NOT NULL
        ON CONFLICT DO NOTHING
    """)
    cr.execute("""
        UPDATE cbt_employee_role role
           SET user_id = employee.user_id
          FROM hr_employee employee
         WHERE role.employee_id = employee.id
           AND role.user_id IS NULL
           AND employee.user_id IS NOT NULL
    """)
    # Existing users keep today's behaviour: they are administrators.
    cr.execute("""
        UPDATE res_users
           SET cbt_role = 'admin'
         WHERE cbt_role IS NULL
    """)
