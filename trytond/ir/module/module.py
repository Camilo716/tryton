#This file is part of Tryton.  The COPYRIGHT file at the top level of
#this repository contains the full copyright notices and license terms.
"Module"
import os
import re
import zipfile
import urllib
import zipimport
from trytond.osv import fields, OSV
import trytond.tools as tools
from trytond.modules import MODULES_PATH, create_graph, get_module_list
from trytond.wizard import Wizard, WizardOSV
from trytond.pooler import get_db, restart_pool

VER_REGEXP = re.compile(
    "^(\\d+)((\\.\\d+)*)([a-z]?)((_(pre|p|beta|alpha|rc)\\d*)*)(-r(\\d+))?$")
SUFFIX_VALUE = {"pre": -2, "p": 0, "alpha": -4, "beta": -3, "rc": -1}
SUFFIX_REGEXP = re.compile("^(alpha|beta|rc|pre|p)(\\d*)$")


def vercmp(ver1, ver2):
    """
    Compare two versions
    Take from portage_versions.py
    @param ver1: version to compare with
    @type ver1: string (example "1.2-r3")
    @param ver2: version to compare again
    @type ver2: string (example "2.1-revision1")
    @rtype: None or float
    @return:
    1. position if ver1 is greater than ver2
    2. negative if ver1 is less than ver2
    3. 0 if ver1 equals ver2
    4. None if ver1 or ver2 are invalid
    """

    match1 = VER_REGEXP.match(ver1)
    match2 = VER_REGEXP.match(ver2)

    if not match1 or not match1.groups():
        return None
    if not match2 or not match2.groups():
        return None

    list1 = [int(match1.group(1))]
    list2 = [int(match2.group(1))]

    if len(match1.group(2)) or len(match2.group(2)):
        vlist1 = match1.group(2)[1:].split(".")
        vlist2 = match2.group(2)[1:].split(".")
        for i in range(0, max(len(vlist1), len(vlist2))):
            # Implicit .0 is given -1, so 1.0.0 > 1.0
            # would be ambiguous if two versions that aren't literally equal
            # are given the same value (in sorting, for example).
            if len(vlist1) <= i or len(vlist1[i]) == 0:
                list1.append(-1)
                list2.append(int(vlist2[i]))
            elif len(vlist2) <= i or len(vlist2[i]) == 0:
                list1.append(int(vlist1[i]))
                list2.append(-1)
            # Let's make life easy and use integers
            # unless we're forced to use floats
            elif (vlist1[i][0] != "0" and vlist2[i][0] != "0"):
                list1.append(int(vlist1[i]))
                list2.append(int(vlist2[i]))
            # now we have to use floats so 1.02 compares correctly against 1.1
            else:
                list1.append(float("0."+vlist1[i]))
                list2.append(float("0."+vlist2[i]))
    # and now the final letter
    if len(match1.group(4)):
        list1.append(ord(match1.group(4)))
    if len(match2.group(4)):
        list2.append(ord(match2.group(4)))

    for i in range(0, max(len(list1), len(list2))):
        if len(list1) <= i:
            return -1
        elif len(list2) <= i:
            return 1
        elif list1[i] != list2[i]:
            return list1[i] - list2[i]

    # main version is equal, so now compare the _suffix part
    list1 = match1.group(5).split("_")[1:]
    list2 = match2.group(5).split("_")[1:]

    for i in range(0, max(len(list1), len(list2))):
        # Implicit _p0 is given a value of -1, so that 1 < 1_p0
        if len(list1) <= i:
            suffix1 = ("p","-1")
        else:
            suffix1 = SUFFIX_REGEXP.match(list1[i]).groups()
        if len(list2) <= i:
            suffix2 = ("p","-1")
        else:
            suffix2 = SUFFIX_REGEXP.match(list2[i]).groups()
        if suffix1[0] != suffix2[0]:
            return SUFFIX_VALUE[suffix1[0]] - SUFFIX_VALUE[suffix2[0]]
        if suffix1[1] != suffix2[1]:
            # it's possible that the s(1|2)[1] == ''
            # in such a case, fudge it.
            try:
                revision1 = int(suffix1[1])
            except ValueError:
                revision1 = 0
            try:
                revision2 = int(suffix2[1])
            except ValueError:
                revision2 = 0
            if revision1 - revision2:
                return revision1 - revision2

    # the suffix part is equal to, so finally check the revision
    if match1.group(9):
        revision1 = int(match1.group(9))
    else:
        revision1 = 0
    if match2.group(9):
        revision2 = int(match2.group(9))
    else:
        revision2 = 0
    return revision1 - revision2


class Module(OSV):
    "Module"
    _name = "ir.module.module"
    _description = __doc__
    name = fields.Char("Name", readonly=True, required=True)
    category = fields.Many2One('ir.module.category', 'Category',
        readonly=True)
    shortdesc = fields.Char('Short description', readonly=True)
    description = fields.Text("Description", readonly=True)
    author = fields.Char("Author", readonly=True)
    website = fields.Char("Website", readonly=True)
    version = fields.Function('get_version', string='Version', type='char')
    url = fields.Char('URL')
    dependencies = fields.One2Many('ir.module.module.dependency',
        'module', 'Dependencies', readonly=True)
    state = fields.Selection([
        ('uninstallable', 'Not Installable'),
        ('uninstalled', 'Not Installed'),
        ('installed', 'Installed'),
        ('to upgrade', 'To be upgraded'),
        ('to remove', 'To be removed'),
        ('to install', 'To be installed'),
        ], string='State', readonly=True)

    def __init__(self):
        super(Module, self).__init__()
        self._sql_constraints = [
            ('name_uniq', 'unique (name)',
                'The name of the module must be unique!'),
        ]
        self._order.insert(0, ('name', 'ASC'))
        self._rpc_allowed += [
            'button_install',
            'button_install_cancel',
            'button_uninstall',
            'button_uninstall_cancel',
            'button_upgrade',
            'button_upgrade_cancel',
            'button_update_translations',
        ]
        self._error_messages.update({
            'delete_state': 'You can not remove a module that is installed ' \
                    'or will be installed',
            'missing_dep': 'Missing dependencies %s for module "%s"',
            'uninstall_dep': 'The modules you are trying to uninstall ' \
                    'depends on installed modules:',
            })

    def default_state(self, cursor, user, context=None):
        return 'uninstalled'

    def default_license(self, cursor, user, context=None):
        return 'GPL-3'

    @staticmethod
    def get_module_info(name):
        "Return the content of the __tryton__.py"
        try:
            if name in ['ir', 'workflow', 'res', 'webdav']:
                file_p = tools.file_open(os.path.join(
                    os.path.dirname(MODULES_PATH), name, '__tryton__.py'))
            else:
                file_p = tools.file_open(os.path.join(MODULES_PATH, name,
                    '__tryton__.py'))
            data = file_p.read()
            info = eval(data)
            file_p.close()
        except:
            return {}
        return info

    def get_version(self, cursor, user, ids, name, arg,
            context=None):
        res = {}
        for module in self.browse(cursor, user, ids, context=context):
            res[module.id] = Module.get_module_info(
                    module.name).get('version', '')
        return res

    def delete(self, cursor, user, ids, context=None):
        if not ids:
            return True
        if isinstance(ids, (int, long)):
            ids = [ids]
        for module in self.browse(cursor, user, ids, context=context):
            if module.state in (
                    'installed',
                    'to upgrade',
                    'to remove',
                    'to install',
                    ):
                self.raise_user_error(cursor, 'delete_state', context=context)
        return super(Module, self).delete(cursor, user, ids, context=context)

    def state_install(self, cursor, user, ids, context=None):
        graph, packages, later = create_graph(get_module_list())
        for module in self.browse(cursor, user, ids, context=context):
            if module.name not in graph:
                missings = []
                for package, deps, datas in packages:
                    if package == module.name:
                        missings = [x for x in deps if x not in graph]
                self.raise_user_error(cursor, 'missing_dep',
                        (missings, module.name), context=context)
            def get_parents(name, graph):
                parents = []
                for node in graph:
                    if graph[name] in node.childs:
                        if node.name not in parents:
                            parents.append(node.name)
                for parent in parents:
                    for parent2 in get_parents(parent, graph):
                        if parent2 not in parents:
                            parents.append(parent2)
                return parents
            dependencies = get_parents(module.name, graph)
            module_install_ids = self.search(cursor, user, [
                ('name', 'in', dependencies),
                ('state', '=', 'uninstalled'),
                ], context=context)
            self.write(cursor, user, module_install_ids + [module.id], {
                'state': 'to install',
                }, context=context)

    def state_upgrade(self, cursor, user, ids, context=None):
        graph, packages, later = create_graph(get_module_list())
        for module in self.browse(cursor, user, ids):
            if module.name not in graph:
                missings = []
                for package, deps, datas in packages:
                    if package == module.name:
                        missings = [x for x in deps if x not in graph]
                self.raise_user_error(cursor, user, 'missing_dep',
                        (missings, module.name), context=context)
            def get_childs(name, graph):
                childs = [x.name for x in graph[name].childs]
                childs2 = []
                for child in childs:
                    childs2 += get_childs(child, graph)
                return childs + childs2
            dependencies = get_childs(module.name, graph)
            module_installed_ids = self.search(cursor, user, [
                ('name', 'in', dependencies),
                ('state', '=', 'installed'),
                ], context=context)
            self.write(cursor, user, module_installed_ids + [module.id], {
                'state': 'to upgrade',
                }, context=context)

    def button_install(self, cursor, user, ids, context=None):
        return self.state_install(cursor, user, ids, context=context)

    def button_install_cancel(self, cursor, user, ids, context=None):
        self.write(cursor, user, ids, {
            'state': 'uninstalled',
            }, context=context)
        return True

    def button_uninstall(self, cursor, user, ids, context=None):
        for module in self.browse(cursor, user, ids, context=context):
            cursor.execute('SELECT m.state, m.name ' \
                    'FROM ir_module_module_dependency d ' \
                    'JOIN ir_module_module m on (d.module = m.id) ' \
                    'WHERE d.name = %s ' \
                        'AND m.state not in ' \
                        '(\'uninstalled\',\'uninstallable\',\'to remove\')',
                            (module.name,))
            res = cursor.fetchall()
            if res:
                self.raise_user_error(cursor, 'uninstall_dep',
                        error_description='\n'.join(
                            ['\t%s: %s' % (x[0], x[1]) for x in res]),
                        context=context)
        self.write(cursor, user, ids, {'state': 'to remove'})
        return True

    def button_uninstall_cancel(self, cursor, user, ids, context=None):
        self.write(cursor, user, ids, {'state': 'installed'}, context=context)
        return True

    def button_upgrade(self, cursor, user, ids, context=None):
        return self.state_upgrade(cursor, user, ids, context)

    def button_upgrade_cancel(self, cursor, user, ids, context=None):
        self.write(cursor, user, ids, {'state': 'installed'}, context=context)
        return True

    def button_update_translations(self, cursor, user, ids, context=None):
        lang_obj = self.pool.get('ir.lang')
        lang_ids = lang_obj.search(cursor, user, [('translatable', '=', True)],
                context=context)
        langs = lang_obj.browse(cursor, user, lang_ids, context=context)
        for module in self.browse(cursor, user, ids, context=context):
            files = Module.get_module_info(module.name).get('translations', {})
            for lang in langs:
                if files.has_key(lang.code):
                    filepath = os.path.join(MODULES_PATH, module.name,
                            files[lang.code])
                    tools.trans_load(filepath, lang.code)
        return True

    # update the list of available packages
    def update_list(self, cursor, user, context=None):
        res = 0

        module_names = ['ir', 'workflow', 'res', 'webdav']
        if os.path.isdir(MODULES_PATH):
            module_names += os.listdir(MODULES_PATH)

        # iterate through installed modules and mark them as being so
        for name in module_names:
            mod_name = name
            if name[-4:] == '.zip':
                mod_name = name[:-4]
            ids = self.search(cursor, user, [('name', '=', mod_name)],
                    context=context)
            if ids:
                module_id = ids[0]
                mod = self.browse(cursor, user, module_id)
                tryton = Module.get_module_info(mod_name)
                if tryton.get('installable', True) \
                        and mod.state == 'uninstallable':
                    self.write(cursor, user, module_id, {
                        'state': 'uninstalled'}, context=context)
                self.write(cursor, user, module_id, {
                    'description': tryton.get('description', ''),
                    'shortdesc': tryton.get('name', ''),
                    'author': tryton.get('author', ''),
                    'website': tryton.get('website', ''),
                    })
                self._update_dependencies(cursor, user, module_id,
                        tryton.get('depends', []))
                self._update_category(cursor, user, module_id,
                        tryton.get('category', 'None'))
                continue
            if name in ['ir', 'workflow', 'res', 'webdav']:
                mod_path = os.path.join(
                        os.path.dirname(MODULES_PATH), name)
            else:
                mod_path = os.path.join(MODULES_PATH, name)
            if os.path.isdir(mod_path) \
                    or os.path.islink(mod_path) \
                    or zipfile.is_zipfile(mod_path):
                tryton = Module.get_module_info(mod_name)
                if not tryton or not tryton.get('installable', True):
                    continue
                new_id = self.create(cursor, user, {
                    'name': mod_name,
                    'state': 'uninstalled',
                    'description': tryton.get('description', ''),
                    'shortdesc': tryton.get('name', ''),
                    'author': tryton.get('author', 'Unknown'),
                    'website': tryton.get('website', ''),
                })
                res += 1
                self._update_dependencies(cursor, user, new_id,
                        tryton.get('depends', []))
                self._update_category(cursor, user, new_id,
                        tryton.get('category', 'None'))
        return res

    def _update_dependencies(self, cursor, user, module_id, depends=None):
        dependency_obj = self.pool.get('ir.module.module.dependency')
        dependency_ids = dependency_obj.search(cursor, user, [
            ('module', '=', module_id),
            ])
        dependency_obj.delete(cursor, user, dependency_ids)
        if depends is None:
            depends = []
        for depend in depends:
            dependency_obj.create(cursor, user, {
                'module': module_id,
                'name': depend,
                })

    def _update_category(self, cursor, user, module_id, category='None'):
        category_obj = self.pool.get('ir.module.category')
        categs = category.split('/')
        parent_id = None
        while categs:
            if parent_id is not None:
                category_ids = category_obj.search(cursor, user, [
                    ('name', '=', categs[0]),
                    ('parent', '=', parent_id),
                    ])
            else:
                category_ids = category_obj.search(cursor, user, [
                    ('name', '=', categs[0]),
                    ('parent', '=', False),
                    ])
            if not category_ids:
                parent_id = category_obj.create(cursor, user, {
                    'name': categs[0],
                    'parent': parent_id,
                    })
            else:
                parent_id = category_ids[0]
            categs = categs[1:]
        self.write(cursor, user, module_id, {'category': parent_id})

Module()

class ModuleDependency(OSV):
    "Module dependency"
    _name = "ir.module.module.dependency"
    _description = __doc__
    name = fields.Char('Name')
    module = fields.Many2One('ir.module.module', 'Module', select=1,
       ondelete='cascade')
    state = fields.Function('get_state', type='selection',
       selection=[
       ('uninstallable','Uninstallable'),
       ('uninstalled','Not Installed'),
       ('installed','Installed'),
       ('to upgrade','To be upgraded'),
       ('to remove','To be removed'),
       ('to install','To be installed'),
       ('unknown', 'Unknown'),
       ], string='State', readonly=True)

    def get_state(self, cursor, user, ids, name, args, context=None):
        result = {}
        module_obj = self.pool.get('ir.module.module')
        for dependency in self.browse(cursor, user, ids):
            ids = module_obj.search(cursor, user, [
                ('name', '=', dependency.name),
                ], context=context)
            if ids:
                result[dependency.id] = module_obj.browse(cursor, user, ids[0],
                        context=context).state
            else:
                result[dependency.id] = 'unknown'
        return result

ModuleDependency()


class ModuleConfigWizardItem(OSV):
    "Config wizard to run after installing module"
    _name = 'ir.module.module.config_wizard.item'
    _description = __doc__
    name = fields.Char('Name', required=True, readonly=True)
    sequence= fields.Integer('Sequence')
    state = fields.Selection([
        ('open', 'Open'),
        ('done', 'Done'),
        ], string='State', required=True)

    def __init__(self):
        super(ModuleConfigWizardItem, self).__init__()
        self._order.insert(0, ('sequence', 'ASC'))

    def default_state(self, cursor, user, context=None):
        return 'open'

    def default_sequence(self, cursor, user, context=None):
        return 10

ModuleConfigWizardItem()


class ModuleConfigWizardFirst(WizardOSV):
    _name = 'ir.module.module.config_wizard.first'

ModuleConfigWizardFirst()


class ModuleConfigWizard(Wizard):
    'Run config wizards'
    _name = 'ir.module.module.config_wizard'
    states = {
        'init': {
            'result': {
                'type': 'choice',
                'next_state': '_first',
            },
        },
        'first': {
            'result': {
                'type': 'form',
                'object': 'ir.module.module.config_wizard.first',
                'state': [
                    ('end', 'Cancel', 'tryton-cancel'),
                    ('wizard', 'Ok', 'tryton-ok', True),
                ],
            },
        },
        'wizard': {
            'result': {
                'type': 'action',
                'action': '_action_wizard',
                'state': 'next',
            },
        },
        'next': {
            'result': {
                'type': 'choice',
                'next_state': '_next',
            },
        },
    }

    def _first(self, cursor, user, data, context=None):
        res = self._next(cursor, user, data, context=context)
        if res == 'wizard':
            return 'first'
        return res

    def _action_wizard(self, cursor, user, data, context=None):
        item_obj = self.pool.get('ir.module.module.config_wizard.item')
        item_ids = item_obj.search(cursor, user, [
            ('state', '=', 'open'),
            ], limit=1, context=context)
        if item_ids:
            item = item_obj.browse(cursor, user, item_ids[0], context=context)
            item_obj.write(cursor, user, item.id, {
                'state': 'done',
                }, context=context)
            return {
                    'type': 'ir.action.wizard',
                    'wiz_name': item.name,
                    }
        return {}

    def _next(self, cursor, user, data, context=None):
        item_obj = self.pool.get('ir.module.module.config_wizard.item')
        item_ids = item_obj.search(cursor, user, [
            ('state', '=', 'open'),
            ], context=context)
        if item_ids:
            return 'wizard'
        return 'end'

ModuleConfigWizard()


class ModuleInstallUpgradeInit(WizardOSV):
    _name = 'ir.module.module.install_upgrade.init'
    module_info = fields.Text('Modules to update', readonly=True)

ModuleInstallUpgradeInit()


class ModuleInstallUpgradeStart(WizardOSV):
    _name = 'ir.module.module.install_upgrade.start'

ModuleInstallUpgradeStart()


class ModuleInstallUpgrade(Wizard):
    "Install / Upgrade modules"
    _name = 'ir.module.module.install_upgrade'

    def _get_install(self, cursor, user, data, context):
        module_obj = self.pool.get('ir.module.module')
        module_ids = module_obj.search(cursor, user, [
            ('state', 'in', ['to upgrade', 'to remove', 'to install']),
            ], context=context)
        modules = module_obj.browse(cursor, user, module_ids, context=context)
        return {
            'module_info': '\n'.join([x.name + ': ' + x.state \
                    for x in modules]),
        }

    def _upgrade_module(self, cursor, user, data, context):
        module_obj = self.pool.get('ir.module.module')
        lang_obj = self.pool.get('ir.lang')
        dbname = cursor.dbname
        db = get_db(dbname)
        cursor = db.cursor()
        module_ids = module_obj.search(cursor, user, [
            ('state', 'in', ['to upgrade', 'to remove', 'to install']),
            ], context=context)
        lang_ids = lang_obj.search(cursor, user, [
            ('translatable', '=', True),
            ], context=context)
        lang = [x.code for x in lang_obj.browse(cursor, user, lang_ids,
            context=context)]
        cursor.commit()
        cursor.close()
        if module_ids:
            restart_pool(dbname, update_module=True, lang=lang)
        return {}

    states = {
        'init': {
            'actions': ['_get_install'],
            'result': {
                'type': 'form',
                'object': 'ir.module.module.install_upgrade.init',
                'state': [
                    ('end', 'Cancel', 'tryton-cancel'),
                    ('start', 'Start Upgrade', 'tryton-ok', True),
                ],
            },
        },
        'start': {
            'actions': ['_upgrade_module'],
            'result': {
                'type': 'form',
                'object': 'ir.module.module.install_upgrade.start',
                'state': [
                    ('config', 'Ok', 'tryton-ok', True),
                ],
            },
        },
        'config': {
            'result': {
                'type': 'action',
                'action': '_config',
                'state': 'end',
            },
        },
    }

    def _config(self, cursor, user, data, context=None):
        return {
                'type': 'ir.action.wizard',
                'wiz_name': 'ir.module.module.config_wizard',
                }

ModuleInstallUpgrade()


class ModuleConfig(Wizard):
    'Configure Modules'
    _name = 'ir.module.module.config'
    states = {
        'init': {
            'result': {
                'type': 'action',
                'action': '_action_open',
                'state': 'end',
            },
        },
    }

    def _action_open(self, cursor, user, datas, context=None):
        model_data_obj = self.pool.get('ir.model.data')
        act_window_obj = self.pool.get('ir.action.act_window')

        model_data_ids = model_data_obj.search(cursor, user, [
            ('fs_id', '=', 'act_module_form'),
            ('module', '=', 'ir'),
            ('inherit', '=', False),
            ], limit=1, context=context)
        model_data = model_data_obj.browse(cursor, user, model_data_ids[0],
                context=context)
        res = act_window_obj.read(cursor, user, model_data.db_id, context=context)
        return res

ModuleConfig()
