# -*- coding: utf-8 -*-
from odoo import fields
from odoo.tests.common import TransactionCase

IMG_DATA_URI = (
    'data:image/png;base64,'
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8z8BQDwAEhQ'
    'GAhKmMIQAAAABJRU5ErkJggg=='
)


class TestPaperReport(TransactionCase):
    """Tests for the printable Question Paper / Answer Key reports."""

    def setUp(self):
        super().setUp()
        self.subject = self.env['cbt.subject'].create({'name': 'Physics'})
        self.subject2 = self.env['cbt.subject'].create({'name': 'Chemistry'})
        self.topic = self.env['cbt.subject.topic'].create({
            'name': 'Mechanics',
            'subject_id': self.subject.id,
        })
        self.stopic = self.env['cbt.subject.subtopic'].create({
            'name': 'Kinematics',
            'topic_id': self.topic.id,
        })
        self.difficulty = self.env['cbt.question.difficulty.level'].create({
            'name': 'Easy',
        })
        self.qtype = self.env['cbt.question.type'].create({'name': 'MCQ'})
        self.skill = self.env['cbt.question.skill'].create({'name': 'Basic'})
        self.qtime = self.env['cbt.question.time'].create({'name': '60'})
        self.slot = self.env['cbt.slot'].create({
            'name': 'Morning',
            'date': fields.Date.today(),
            'time': 9.0,
        })
        self.criteria = self.env['cbt.paper.criteria'].create({
            'name': 'Criteria',
            'duration': '90',
        })
        self.generator = self.env['cbt.paper.generator'].create({
            'name': 'Generator',
            'criteria_id': self.criteria.id,
            'slot_id': self.slot.id,
        })
        self.paper = self.env['cbt.paper'].create({
            'name': 'Midterm Paper',
            'generator_id': self.generator.id,
            'slot_id': self.slot.id,
            'questions': [(6, 0, [
                self._create_question(
                    subject=self.subject, topic=self.topic, long=True).id,
                self._create_question(subject=self.subject2).id,
            ])],
        })

    def _create_question(self, subject, topic=None, long=False):
        question = '<p>What is the answer?</p>'
        if long:
            question = (
                '<p>' + ('Lorem ipsum dolor sit amet. ' * 60) + '</p>'
                '<img src="%s"/>' % IMG_DATA_URI +
                '<table><tr><td>a</td><td>b</td></tr>'
                '<tr><td>c</td><td>d</td></tr></table>'
            )
        return self.env['cbt.mcqs'].create({
            'subject_id': subject.id,
            'topic_id': (topic or self.topic).id,
            'stopic_id': self.stopic.id,
            'type_id': self.qtype.id,
            'skill_id': self.skill.id,
            'difficulty_level_id': self.difficulty.id,
            'time_id': self.qtime.id,
            'question': question,
            'ans1': '<p>Option A</p>',
            'ans2': '<p>Option B</p>',
            'ans3': '<p>Option C</p>',
            'ans4': '<p>Option D</p>',
            'ans2_correct': True,
            'state': 'approved',
        })

    # ------------------------------------------------------------------ helpers
    def _render_html(self, report_xmlid, records):
        html, report_type = self.env['ir.actions.report']._render_qweb_html(
            report_xmlid, records.ids)
        self.assertEqual(report_type, 'html')
        return html

    # ------------------------------------------------------------------ tests
    def test_question_paper_html_render(self):
        html = self._render_html('cbt.entry_test_paper', self.paper)
        self.assertIn(b'Question Paper', html)
        self.assertIn(b'Midterm Paper', html)
        self.assertIn(b'Physics', html)
        self.assertIn(b'Chemistry', html)
        self.assertIn(b'Page', html)
        self.assertIn(b'Marks', html)

    def test_multiple_papers_render_one_section_each(self):
        paper2 = self.env['cbt.paper'].create({
            'name': 'Second Paper',
            'generator_id': self.generator.id,
            'slot_id': self.slot.id,
            'questions': [(6, 0, [
                self._create_question(subject=self.subject).id])],
        })
        html = self._render_html(
            'cbt.entry_test_paper', self.paper + paper2)
        self.assertIn(b'Midterm Paper', html)
        self.assertIn(b'Second Paper', html)
        # One article wrapper per printed record.
        self.assertEqual(html.count(b'class="article"'), 2)

    def test_empty_options_are_not_rendered(self):
        html = self._render_html('cbt.entry_test_paper', self.paper)
        self.assertIn(b'A.</td>', html)
        self.assertIn(b'D.</td>', html)
        self.assertNotIn(b'E.</td>', html)
        self.assertNotIn(b'F.</td>', html)

    def test_long_html_and_image_are_rendered(self):
        html = self._render_html('cbt.entry_test_paper', self.paper)
        self.assertIn(b'<img', html)
        self.assertIn(IMG_DATA_URI.encode(), html)
        self.assertIn(b'<table>', html)

    def test_answer_key_html_render(self):
        html = self._render_html('cbt.paper_answer_key_report', self.paper)
        self.assertIn(b'Answer Key', html)
        # ans2 is the correct option of every generated question.
        self.assertIn(b'>B<', html)

    def test_student_paper_html_render(self):
        participant = self.env['cbt.participant'].create({
            'name': 'Ali Khan',
            'login': 'ali.khan',
            'slot_id': self.slot.id,
        })
        student_paper = self.env['cbt.student.paper'].create({
            'main_paper_id': self.paper.id,
            'participant_id': participant.id,
            'questions': [(6, 0, self.paper.questions.ids)],
        })
        html = self._render_html(
            'cbt.student_paper_question_report', student_paper)
        self.assertIn(b'Ali Khan', html)
        self.assertIn(b'ali.khan', html)

    def _word_html(self, html, title='Question Paper'):
        from email import message_from_bytes, policy

        from odoo.addons.cbt.controllers.report_word import (
            CBTReportWordController)

        if isinstance(html, bytes):
            html = html.decode()
        data = CBTReportWordController._to_word_mhtml(html, title=title)
        self.assertIsInstance(data, bytes)
        message = message_from_bytes(data, policy=policy.default)
        return message.get_body(preferencelist=('html',)).get_content()

    def test_word_export_handles_escaped_html(self):
        # Some deployments return the rendered report HTML-escaped while the
        # header/footer stay as real markup.  The Word export must unescape it
        # instead of printing the tags as text.
        from html import escape

        html = self._render_html('cbt.entry_test_paper', self.paper)
        document = self._word_html(escape(html.decode() if isinstance(
            html, bytes) else html))
        self.assertIn('<div id="wrapwrap"', document)
        self.assertNotIn('&lt;div', document)
        self.assertNotIn('&lt;meta', document)
        self.assertIn('mso-element:header', document)
        self.assertIn('o_cbt_report_header', document)
        self.assertIn('cbt-question', document)

    def test_word_export_mixed_escaped_body_keeps_real_header(self):
        # Production files showed a real <header>/<footer> plus an escaped
        # wrapwrap body (``&lt;div id=&#34;wrapwrap&#34;&gt;``). Word then
        # printed every tag. The body must be reparsed into elements.
        html = '''<!DOCTYPE html>
<html>
<head><meta charset="utf-8"/><title>t</title></head>
<body>
                &lt;div id=&#34;wrapwrap&#34;&gt;
                    &lt;main&gt;
            &lt;div class=&#34;article&#34; data-oe-model=&#34;cbt.paper&#34;&gt;
                        &lt;div class=&#34;page cbt-report&#34;&gt;
                            &lt;div class=&#34;cbt-paper&#34;&gt;
                                &lt;h3 class=&#34;cbt-title&#34;&gt;Question Paper&lt;/h3&gt;
                                &lt;div class=&#34;cbt-question&#34;&gt;What is 2+2?&lt;/div&gt;
                            &lt;/div&gt;
                        &lt;/div&gt;
            &lt;/div&gt;
                    &lt;/main&gt;
                &lt;/div&gt;
<div class="header o_cbt_report_header"><span>Company</span></div>
<div class="footer o_cbt_report_footer">Page
    <span class="page"/> of <span class="topage"/>
</div>
</body>
</html>'''
        document = self._word_html(html)
        self.assertIn('id="wrapwrap"', document.replace("'", '"'))
        self.assertIn('cbt-question', document)
        self.assertIn('What is 2+2?', document)
        self.assertIn('Question Paper', document)
        self.assertIn('mso-element:header', document)
        self.assertIn('o_cbt_report_header', document)
        self.assertNotIn('&lt;div', document)
        self.assertNotIn('&lt;meta', document)
        self.assertNotIn('&lt;h3', document)

    def test_pdf_render(self):
        state = self.env['ir.actions.report'].get_wkhtmltopdf_state()
        if state != 'ok':
            # wkhtmltopdf is not available in this environment: fall back to
            # the HTML render to at least exercise the template.
            self._render_html('cbt.entry_test_paper', self.paper)
            return
        pdf, report_type = self.env['ir.actions.report']._render_qweb_pdf(
            'cbt.entry_test_paper', self.paper.ids)
        self.assertEqual(report_type, 'pdf')
        self.assertTrue(pdf.startswith(b'%PDF'))

    def test_report_actions_configuration(self):
        question = self.env.ref('cbt.entry_test_paper')
        answer_key = self.env.ref('cbt.paper_answer_key_report')
        self.assertEqual(question.report_type, 'qweb-pdf')
        self.assertEqual(answer_key.report_type, 'qweb-pdf')
        self.assertEqual(question.paperformat_id.format, 'A4')
        self.assertEqual(question.report_name, 'cbt.paper')
        self.assertEqual(answer_key.report_name, 'cbt.paper_answer_key')

        reviewer = self.env.ref('cbt.group_cbt_reviewer')
        admin = self.env.ref('cbt.group_cbt_admin')
        creator = self.env.ref('cbt.group_cbt_creator')
        self.assertIn(reviewer, answer_key.groups_id)
        self.assertIn(admin, answer_key.groups_id)
        self.assertNotIn(creator, answer_key.groups_id)

    def test_reports_bound_to_both_models(self):
        question = self.env.ref('cbt.entry_test_paper')
        student_question = self.env.ref('cbt.student_paper_question_report')
        answer_key = self.env.ref('cbt.paper_answer_key_report')
        student_answer_key = self.env.ref(
            'cbt.student_paper_answer_key_report')
        self.assertEqual(question.binding_model_id.model, 'cbt.paper')
        self.assertEqual(
            student_question.binding_model_id.model, 'cbt.student.paper')
        self.assertEqual(answer_key.binding_model_id.model, 'cbt.paper')
        self.assertEqual(
            student_answer_key.binding_model_id.model, 'cbt.student.paper')
