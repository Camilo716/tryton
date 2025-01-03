# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
from trytond.pool import Pool

from . import account, ir, sale


def register():
    Pool.register(
        ir.Cron,
        sale.Sale,
        account.Payment,
        account.Invoice,
        module='sale_payment', type_='model')
