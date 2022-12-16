# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
import sys
import gtk
import gettext

from tryton.common import get_toplevel_window, IconFactory
from tryton.common.underline import set_underline
from tryton.config import TRYTON_ICON, CONFIG
from tryton.gui import Main

_ = gettext.gettext


class Limit(object):
    'Set Search Limit'

    def __init__(self):
        self.parent = get_toplevel_window()
        self.win = gtk.Dialog(_('Limit'), self.parent,
            gtk.DIALOG_MODAL | gtk.DIALOG_DESTROY_WITH_PARENT)
        Main().add_window(self.win)
        cancel_button = self.win.add_button(
            set_underline(_("Cancel")), gtk.RESPONSE_CANCEL)
        cancel_button.set_image(IconFactory.get_image(
                'tryton-cancel', gtk.ICON_SIZE_BUTTON))
        cancel_button.set_always_show_image(True)
        ok_button = self.win.add_button(
            set_underline(_("OK")), gtk.RESPONSE_OK)
        ok_button.set_image(IconFactory.get_image(
                'tryton-ok', gtk.ICON_SIZE_BUTTON))
        ok_button.set_always_show_image(True)
        self.win.set_default_response(gtk.RESPONSE_OK)
        self.win.set_icon(TRYTON_ICON)
        self.win.vbox.set_spacing(3)
        self.win.vbox.pack_start(gtk.Label(
            _('Search Limit Settings')), expand=False, fill=True)
        self.win.vbox.pack_start(gtk.HSeparator())
        hbox = gtk.HBox(spacing=3)
        label = gtk.Label(_('Limit:'))
        hbox.pack_start(label, expand=True, fill=True)
        adjustment = gtk.Adjustment(value=CONFIG['client.limit'],
            lower=1, upper=sys.maxsize, step_incr=10, page_incr=100)
        self.spin_limit = gtk.SpinButton()
        self.spin_limit.configure(adjustment, climb_rate=1, digits=0)
        self.spin_limit.set_numeric(False)
        self.spin_limit.set_activates_default(True)
        label.set_mnemonic_widget(self.spin_limit)
        hbox.pack_start(self.spin_limit, expand=True, fill=True)
        self.win.vbox.pack_start(hbox, expand=True, fill=True)

        self.win.show_all()

    def run(self):
        'Run the window'
        res = self.win.run()
        if res == gtk.RESPONSE_OK:
            CONFIG['client.limit'] = self.spin_limit.get_value_as_int()
            CONFIG.save()
        self.parent.present()
        self.win.destroy()
        return res
