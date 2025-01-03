# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.

from trytond.model import ModelSQL, fields
from trytond.pool import Pool


class Text(ModelSQL):
    __name__ = 'test.text'
    text = fields.Text(string='Text', size=None, help='Test text',
            required=False)


class TextDefault(ModelSQL):
    __name__ = 'test.text_default'
    text = fields.Text(string='Text', size=None, help='Test text',
            required=False)

    @staticmethod
    def default_text():
        return 'Test'


class TextRequired(ModelSQL):
    __name__ = 'test.text_required'
    text = fields.Text(string='Text', size=None, help='Test text',
            required=True)


class TextSize(ModelSQL):
    __name__ = 'test.text_size'
    text = fields.Text(string='Text', size=5, help='Test text',
            required=False)


class TextTranslate(ModelSQL):
    __name__ = 'test.text_translate'
    text = fields.Text(string='Text', size=None, help='Test text',
            required=False, translate=True)


class FullText(ModelSQL):
    __name__ = 'test.text_full'
    full_text = fields.FullText("Full Text")


def register(module):
    Pool.register(
        Text,
        TextDefault,
        TextRequired,
        TextSize,
        TextTranslate,
        FullText,
        module=module, type_='model')
