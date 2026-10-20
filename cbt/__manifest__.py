# -*- coding: utf-8 -*-
{
    'name': "CBNET",
    'summary': 'University Online Entry Test Application',
    'category': 'OdooCMS',
    'sequence': 4,
    'author': "NUST & AARSOL",
    'website': "https://www.aarsol.com",
    'version': '0.1',
    'depends': [
        'base',
        'website_partner',
        'website_mail',
        # 'website_form',
        'website',
        'base_setup',
        'auth_signup', 'hr'
    ],

    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',

        'report/paper.xml',
        'report/report.xml',
        'wizard/report_print_wizard.xml',

        # 'wizard/export_data_wizard.xml',

        # 'views/assests.xml',
        'views/views.xml',
        'views/templates.xml',
        'views/faculty_roles.xml',
        'views/paper_criteria.xml',
        'views/paper_criteria_rules.xml',
        'views/paper_generation.xml',
        'views/papers.xml',
        'views/paper_replacement.xml',
        'views/paper_conduct.xml',
        'views/review_questions.xml',
        'views/test_schedule.xml',
        'views/student_setup.xml',
        'views/student_paper.xml',
        # 'views/instructions.xml',
        'views/res_config_setting_inherit.xml',
        # 'wizard/cbt_api_wizard_views.xml',
        # 'wizard/import_data_wizard.xml',
        # 'views/cbt_export.xml',
        # 'wizard/subject_result.xml',
    ],
    'application': True,

    'assets': {
        'web.assets_backend': [
            'cbt/static/src/js/sync_participants_action.js',
            'cbt/static/src/js/hide_review_action_menu.js',
        ],
    },
}
