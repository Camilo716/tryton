==========================================
Account Statement Origin Invoices Scenario
==========================================

Imports::

    >>> import datetime as dt
    >>> from decimal import Decimal

    >>> from proteus import Model
    >>> from trytond.modules.account.tests.tools import (
    ...     create_chart, create_fiscalyear, get_accounts)
    >>> from trytond.modules.account_invoice.tests.tools import (
    ...     set_fiscalyear_invoice_sequences)
    >>> from trytond.modules.company.tests.tools import create_company
    >>> from trytond.tests.tools import activate_modules, assertEqual

    >>> today = dt.date.today()

Activate modules::

    >>> config = activate_modules('account_statement', create_company, create_chart)

Create fiscal year::

    >>> fiscalyear = set_fiscalyear_invoice_sequences(
    ...     create_fiscalyear(today=today))
    >>> fiscalyear.click('create_period')

Get accounts::

    >>> accounts = get_accounts()
    >>> receivable = accounts['receivable']
    >>> revenue = accounts['revenue']
    >>> cash = accounts['cash']

Create parties::

    >>> Party = Model.get('party.party')
    >>> customer = Party(name="Customer")
    >>> customer.save()

Create 2 customer invoices::

    >>> Invoice = Model.get('account.invoice')
    >>> customer_invoice1 = Invoice(type='out')
    >>> customer_invoice1.party = customer
    >>> invoice_line = customer_invoice1.lines.new()
    >>> invoice_line.quantity = 1
    >>> invoice_line.unit_price = Decimal('100')
    >>> invoice_line.account = revenue
    >>> invoice_line.description = 'Test'
    >>> customer_invoice1.click('post')
    >>> customer_invoice1.state
    'posted'

    >>> customer_invoice2 = Invoice(type='out')
    >>> customer_invoice2.party = customer
    >>> invoice_line = customer_invoice2.lines.new()
    >>> invoice_line.quantity = 1
    >>> invoice_line.unit_price = Decimal('150')
    >>> invoice_line.account = revenue
    >>> invoice_line.description = 'Test'
    >>> customer_invoice2.click('post')
    >>> customer_invoice2.state
    'posted'

Create a statement with origins::

    >>> AccountJournal = Model.get('account.journal')
    >>> StatementJournal = Model.get('account.statement.journal')
    >>> Statement = Model.get('account.statement')
    >>> account_journal, = AccountJournal.find([('code', '=', 'STA')], limit=1)
    >>> journal_number = StatementJournal(name="Number",
    ...     journal=account_journal,
    ...     account=cash,
    ...     validation='number_of_lines',
    ...     )
    >>> journal_number.save()

    >>> statement = Statement(name="number origins")
    >>> statement.journal = journal_number
    >>> statement.number_of_lines = 1
    >>> origin = statement.origins.new()
    >>> origin.date = today
    >>> origin.amount = Decimal('180.00')
    >>> statement.click('validate_statement')

Pending amount is used to fill all invoices::

    >>> origin, = statement.origins
    >>> line = origin.lines.new()
    >>> line.related_to = customer_invoice1
    >>> line.amount
    Decimal('100.00')
    >>> assertEqual(line.party, customer)
    >>> assertEqual(line.account, receivable)
    >>> origin.pending_amount
    Decimal('80.00')
    >>> line = origin.lines.new()
    >>> line.related_to = customer_invoice2
    >>> line.amount
    Decimal('80.00')
    >>> assertEqual(line.party, customer)
    >>> assertEqual(line.account, receivable)
