# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
import base64
import datetime
import logging
import posixpath
from collections import defaultdict

from oauthlib.oauth2 import BackendApplicationClient, TokenExpiredError
from requests_oauthlib import OAuth2Session
from sql.functions import CharLength

from trytond.config import config
from trytond.i18n import gettext
from trytond.model import ModelSQL, ModelView, Unique, fields
from trytond.model.exceptions import AccessError
from trytond.modules.company.model import CompanyValueMixin
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Bool, Eval, If
from trytond.transaction import Transaction

from .exceptions import InvoiceChorusValidationError

OAUTH_TOKEN_URL = {
    'service-qualif': 'https://sandbox-oauth.piste.gouv.fr/api/oauth/token',
    'service': 'https://oauth.piste.gouv.fr/api/oauth/token',
    }
API_URL = {
    'service-qualif': 'https://sandbox-api.piste.gouv.fr',
    'service': 'https://api.piste.gouv.fr',
    }
EDOC2SYNTAX = {
    'edocument.uncefact.invoice': 'IN_DP_E1_CII_16B',
    }
EDOC2FILENAME = {
    'edocument.uncefact.invoice': 'UNCEFACT-%s.xml',
    }
TIMEOUT = config.getfloat('account_fr_chorus', 'requests_timeout', default=300)
logger = logging.getLogger(__name__)


class _SyntaxMixin(object):
    __slots__ = ()

    @classmethod
    def get_syntaxes(cls):
        pool = Pool()
        syntaxes = [(None, "")]
        try:
            doc = pool.get('edocument.uncefact.invoice')
        except KeyError:
            pass
        else:
            syntaxes.append((doc.__name__, "CII"))
        return syntaxes


class Configuration(_SyntaxMixin, metaclass=PoolMeta):
    __name__ = 'account.configuration'

    _states = {
        'required': Bool(Eval('chorus_login')),
        }

    chorus_piste_client_id = fields.MultiValue(
        fields.Char("Piste Client ID", strip=False))
    chorus_piste_client_secret = fields.MultiValue(
        fields.Char("Piste Client Secret", strip=False, states=_states))
    chorus_login = fields.MultiValue(fields.Char("Login", strip=False))
    chorus_password = fields.MultiValue(fields.Char(
            "Password", strip=False, states=_states))
    chorus_service = fields.MultiValue(fields.Selection([
                (None, ""),
                ('service-qualif', "Qualification"),
                ('service', "Production"),
                ], "Service", states=_states))
    chorus_syntax = fields.Selection(
        'get_syntaxes', "Syntax", states=_states)

    del _states

    @classmethod
    def multivalue_model(cls, field):
        pool = Pool()
        if field in {
                'chorus_piste_client_id', 'chorus_piste_client_secret',
                'chorus_login', 'chorus_password', 'chorus_service'}:
            return pool.get('account.credential.chorus')
        return super(Configuration, cls).multivalue_model(field)


class CredentialChorus(ModelSQL, CompanyValueMixin):
    "Account Credential Chorus"
    __name__ = 'account.credential.chorus'

    chorus_piste_client_id = fields.Char("Piste Client ID", strip=False)
    chorus_piste_client_secret = fields.Char(
        "Piste Client Secret", strip=False)
    chorus_login = fields.Char("Login", strip=False)
    chorus_password = fields.Char("Password", strip=False)
    chorus_service = fields.Selection([
            (None, ""),
            ('service-qualif', "Qualification"),
            ('service', "Production"),
            ], "Service")

    @classmethod
    def get_session(cls):
        pool = Pool()
        Configuration = pool.get('account.configuration')
        config = Configuration(1)
        client = BackendApplicationClient(
            client_id=config.chorus_piste_client_id)
        session = OAuth2Session(client=client)
        cls._get_token(session)
        return session

    @classmethod
    def _get_token(cls, session):
        pool = Pool()
        Configuration = pool.get('account.configuration')
        config = Configuration(1)
        return session.fetch_token(
            OAUTH_TOKEN_URL[config.chorus_service],
            client_id=config.chorus_piste_client_id,
            client_secret=config.chorus_piste_client_secret)

    @classmethod
    def post(cls, path, payload, session=None):
        pool = Pool()
        Configuration = pool.get('account.configuration')
        config = Configuration(1)
        if not session:
            session = cls.get_session()
        base_url = API_URL[config.chorus_service]
        url = posixpath.join(base_url, path)
        account = f'{config.chorus_login}:{config.chorus_password}'
        headers = {
            'cpro-account': base64.b64encode(account.encode('utf-8')),
            }
        try:
            resp = session.post(
                url, headers=headers, json=payload,
                verify=True, timeout=TIMEOUT)
        except TokenExpiredError:
            cls._get_token(session)
            resp = session.post(
                url, headers=headers, json=payload,
                verify=True, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()


class Invoice(metaclass=PoolMeta):
    __name__ = 'account.invoice'

    @classmethod
    def _post(cls, invoices):
        pool = Pool()
        InvoiceChorus = pool.get('account.invoice.chorus')
        posted_invoices = {
            i for i in invoices if i.state in {'draft', 'validated'}}
        super()._post(invoices)
        invoices_chorus = []
        for invoice in posted_invoices:
            if invoice.type == 'out' and invoice.party.chorus:
                invoices_chorus.append(InvoiceChorus(invoice=invoice))
        InvoiceChorus.save(invoices_chorus)


class InvoiceChorus(ModelSQL, ModelView, _SyntaxMixin, metaclass=PoolMeta):
    "Invoice Chorus"
    __name__ = 'account.invoice.chorus'

    invoice = fields.Many2One(
        'account.invoice', "Invoice", required=True,
        domain=[
            ('type', '=', 'out'),
            ('state', 'in', If(Bool(Eval('number')),
                    ['posted', 'paid'],
                    ['posted'])),
            ])
    syntax = fields.Selection('get_syntaxes', "Syntax", required=True)
    number = fields.Char("Number", readonly=True, strip=False)
    date = fields.Date("Date", readonly=True)

    @classmethod
    def __setup__(cls):
        cls.number.search_unaccented = False
        super(InvoiceChorus, cls).__setup__()

        t = cls.__table__()
        cls._sql_constraints = [
            ('invoice_unique', Unique(t, t.invoice),
                'account_fr_chorus.msg_invoice_unique'),
            ]

    @classmethod
    def default_syntax(cls):
        pool = Pool()
        Configuration = pool.get('account.configuration')
        config = Configuration(1)
        return config.chorus_syntax

    @classmethod
    def order_number(cls, tables):
        table, _ = tables[None]
        return [CharLength(table.number), table.number]

    @classmethod
    def validate(cls, records):
        super(InvoiceChorus, cls).validate(records)
        for record in records:
            addresses = [
                record.invoice.company.party.address_get('invoice'),
                record.invoice.invoice_address]
            for address in addresses:
                if not address.siret:
                    raise InvoiceChorusValidationError(
                        gettext('account_fr_chorus'
                            '.msg_invoice_address_no_siret',
                            invoice=record.invoice.rec_name,
                            address=address.rec_name))

    @classmethod
    def delete(cls, records):
        for record in records:
            if record.number:
                raise AccessError(
                    gettext('account_fr_chorus.msg_invoice_delete_sent',
                        invoice=record.invoice.rec_name))
        super(InvoiceChorus, cls).delete(records)

    def _send_context(self):
        return {
            'company': self.invoice.company.id,
            }

    @classmethod
    def send(cls, records=None):
        """Send invoice to Chorus

        The transaction is committed after each invoice.
        """
        pool = Pool()
        Credential = pool.get('account.credential.chorus')
        transaction = Transaction()

        if not records:
            records = cls.search(['OR',
                    ('number', '=', None),
                    ('number', '=', ''),
                    ('invoice.company', '=',
                        transaction.context.get('company')),
                    ])

        sessions = defaultdict(Credential.get_session)
        cls.lock(records)
        for record in records:
            # Use clear cache after a commit
            record = cls(record.id)
            record.lock()
            context = record._send_context()
            with transaction.set_context(**context):
                payload = record.get_payload()
                resp = Credential.post(
                    'cpro/factures/v1/deposer/flux', payload,
                    session=sessions[tuple(context.items())])
                if resp['codeRetour']:
                    logger.error(
                        "Error when sending invoice %d to chorus: %s",
                        record.id, resp['libelle'])
                else:
                    record.number = resp['numeroFluxDepot']
                    record.date = datetime.datetime.strptime(
                        resp['dateDepot'], '%Y-%m-%d').date()
                    record.save()
            Transaction().commit()

    def get_payload(self):
        pool = Pool()
        Doc = pool.get(self.syntax)
        with Transaction().set_context(account_fr_chorus=True):
            data = Doc(self.invoice).render(None)
        filename = EDOC2FILENAME[self.syntax] % self.invoice.number
        filename = filename.replace('/', '-')
        return {
            'fichierFlux': base64.b64encode(data).decode('ascii'),
            'nomFichier': filename,
            'syntaxeFlux': EDOC2SYNTAX[self.syntax],
            'avecSignature': False,
            }
