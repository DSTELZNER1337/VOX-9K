"""Native menu policy tests; actual insertion is verified in WebView2 separately."""
import types
import unittest
from unittest.mock import Mock,patch
import desktop_editing as editing


class Items(list):
    @property
    def Count(self):return len(self)
    def RemoveAt(self,index):self.pop(index)


class Event:
    def __init__(self):self.handlers=[]
    def __iadd__(self,handler):self.handlers.append(handler);return self


def request(names,editable=True,page="http://127.0.0.1:5000/"):
    return types.SimpleNamespace(
        ContextMenuTarget=types.SimpleNamespace(IsEditable=editable,PageUri=page),
        MenuItems=Items(types.SimpleNamespace(Name=name,IsEnabled=True) for name in names),
        Handled=False)


class EditingTests(unittest.TestCase):
    def test_native_editing_commands_preserved_without_browser_debug_actions(self):
        args=request(["undo","redo","cut","copy","paste","pasteAndMatchStyle","selectAll","inspectElement","reload","separator"])
        editing.restrict_editing_menu(None,args)
        self.assertEqual([x.Name for x in args.MenuItems],["undo","redo","cut","copy","paste","pasteAndMatchStyle","selectAll"])
        self.assertFalse(args.Handled)

    def test_noneditable_read_view_and_buttons_have_no_new_context_menu(self):
        args=request(["copy","inspectElement"],editable=False)
        editing.restrict_editing_menu(None,args)
        self.assertTrue(args.Handled)

    def test_only_the_local_app_page_can_use_the_editing_menu(self):
        for page in ("https://external.example/","file:///C:/private","about:blank","http://127.0.0.1:5000/other"):
            with self.subTest(page=page):
                args=request(["paste"],page=page)
                editing.restrict_editing_menu(None,args)
                self.assertTrue(args.Handled)

    def test_unavailable_clipboard_action_stays_disabled(self):
        args=request(["paste","selectAll"]);args.MenuItems[0].IsEnabled=False
        editing.restrict_editing_menu(None,args)
        self.assertFalse(args.MenuItems[0].IsEnabled);self.assertFalse(args.Handled)

    def test_policy_does_not_change_selection_or_access_clipboard(self):
        args=request(["paste"])
        target=args.ContextMenuTarget;target.SelectionText="selected"
        editing.restrict_editing_menu(None,args)
        self.assertEqual(target.SelectionText,"selected")
        self.assertIs(args.ContextMenuTarget,target)

    def test_unknown_menu_items_do_not_expand_access(self):
        args=request(["openLink","saveImage"])
        editing.restrict_editing_menu(None,args)
        self.assertTrue(args.Handled);self.assertEqual(len(args.MenuItems),0)

    def test_context_menu_enabled_without_debug_or_accelerator_expansion(self):
        core=types.SimpleNamespace(Settings=types.SimpleNamespace(
            AreDefaultContextMenusEnabled=False,AreDevToolsEnabled=False,
            AreBrowserAcceleratorKeysEnabled=False),ContextMenuRequested=Event())
        editing.configure_editing_menu(core)
        self.assertTrue(core.Settings.AreDefaultContextMenusEnabled)
        self.assertFalse(core.Settings.AreDevToolsEnabled)
        self.assertFalse(core.Settings.AreBrowserAcceleratorKeysEnabled)
        self.assertEqual(core.ContextMenuRequested.handlers,[editing.restrict_editing_menu])

    def test_missing_native_event_fails_closed_before_enabling_menus(self):
        core=types.SimpleNamespace(Settings=types.SimpleNamespace(AreDefaultContextMenusEnabled=False,AreDevToolsEnabled=False))
        with self.assertRaises(AttributeError):editing.configure_editing_menu(core)
        self.assertFalse(core.Settings.AreDefaultContextMenusEnabled)
        self.assertFalse(core.Settings.AreDevToolsEnabled)

    def test_initialization_failure_preserves_shortcuts_without_debug_fallback(self):
        window=types.SimpleNamespace(native=None)
        with patch.dict("sys.modules",{"System":types.SimpleNamespace(Action=lambda action:action)}),patch("sys.stderr"):
            editing.install_editing_menu(window)
        self.assertFalse(getattr(window,"_vox_editing_menu_installed",False))

    def test_native_install_is_marshaled_and_idempotent(self):
        core=types.SimpleNamespace(Settings=types.SimpleNamespace(),ContextMenuRequested=Event())
        form=types.SimpleNamespace(webview=types.SimpleNamespace(CoreWebView2=core),Invoke=lambda action:action())
        window=types.SimpleNamespace(native=form)
        with patch.dict("sys.modules",{"System":types.SimpleNamespace(Action=lambda action:action)}):
            editing.install_editing_menu(window);editing.install_editing_menu(window)
        self.assertTrue(window._vox_editing_menu_installed)
        self.assertEqual(len(core.ContextMenuRequested.handlers),1)


if __name__=="__main__":unittest.main()
