"""The status item on AppKit: the Bar the menu bar process draws with. Imported only by menubar.main(), so
the model and the process logic stay importable without a window server."""

import objc
from AppKit import (
    NSApplication, NSApplicationActivationPolicyAccessory, NSImage, NSMenu, NSMenuItem, NSStatusBar, NSTimer,
    NSVariableStatusItemLength,
)
from Foundation import NSObject
from PyObjCTools import AppHelper

from lavalier.menubar import SEPARATOR, MenuItem


class _Target(NSObject):
    """An Objective-C object a menu item or a timer can call: fire: runs the Python handler."""

    def initWithHandler_(self, handler):
        self = objc.super(_Target, self).init()
        if self is None:
            return None
        self._handler = handler
        return self

    def fire_(self, sender):
        self._handler()


class CocoaBar:
    def __init__(self):
        self.app = NSApplication.sharedApplication()
        self.app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
        self.item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
        self._targets: list = []  # the targets AppKit calls; kept alive here
        self._timers: list = []

    def set_icon(self, symbol: str, description: str) -> None:
        image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(symbol, description)
        if image is not None:
            image.setTemplate_(True)
            self.item.button().setImage_(image)
        self.item.button().setToolTip_(description)

    def set_menu(self, items: list[MenuItem], on_action) -> None:
        menu = NSMenu.alloc().init()
        menu.setAutoenablesItems_(False)
        targets: list = []
        for it in items:
            if it is SEPARATOR or it.title == "-":
                menu.addItem_(NSMenuItem.separatorItem())
                continue
            mi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(it.title, None, "")
            if it.action:
                target = _Target.alloc().initWithHandler_(lambda action=it.action: on_action(action))
                targets.append(target)
                mi.setTarget_(target)
                mi.setAction_("fire:")
                mi.setEnabled_(it.enabled)
            else:
                mi.setEnabled_(False)
            menu.addItem_(mi)
        self.item.setMenu_(menu)
        self._targets = targets

    def every(self, seconds: float, fn) -> None:
        target = _Target.alloc().initWithHandler_(fn)
        timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(seconds, target, "fire:", None, True)
        self._timers.append((timer, target))

    def call_soon(self, fn) -> None:
        AppHelper.callAfter(fn)

    def run(self) -> None:
        AppHelper.runEventLoop(installInterrupt=True)

    def stop(self) -> None:
        AppHelper.stopEventLoop()
