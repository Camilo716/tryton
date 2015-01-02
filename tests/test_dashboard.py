# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
import unittest
import trytond.tests.test_tryton
from trytond.tests.test_tryton import test_view, test_depends, test_menu_action


class DashboardTestCase(unittest.TestCase):
    'Test Dashboard module'

    def setUp(self):
        trytond.tests.test_tryton.install_module('dashboard')

    def test0005views(self):
        'Test views'
        test_view('dashboard')

    def test0006depends(self):
        'Test depends'
        test_depends()

    def test0007menu_actions(self):
        'Test menu actions'
        test_menu_action('dashboard')


def suite():
    suite = trytond.tests.test_tryton.suite()
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(
        DashboardTestCase))
    return suite
