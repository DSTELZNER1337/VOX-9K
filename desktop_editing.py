"""Native WebView2 editing menus only; no clipboard bridge or debug mode."""
import sys

APP_PAGES = {"http://127.0.0.1:5000", "http://127.0.0.1:5000/"}
EDIT_COMMANDS = {"undo", "redo", "cut", "copy", "paste", "pasteandmatchstyle", "selectall"}


def restrict_editing_menu(sender, args):
    target = args.ContextMenuTarget
    if not target.IsEditable or str(target.PageUri) not in APP_PAGES:
        args.Handled = True
        return
    # Keep WebView2's built-in commands and enabled state. The engine owns focus,
    # cursor/selection, clipboard permissions and text insertion/replacement.
    items = args.MenuItems
    for index in range(items.Count - 1, -1, -1):
        if str(items[index].Name).casefold() not in EDIT_COMMANDS:
            items.RemoveAt(index)
    if items.Count == 0:
        args.Handled = True


def configure_editing_menu(core):
    core.ContextMenuRequested += restrict_editing_menu
    core.Settings.AreDevToolsEnabled = False
    core.Settings.AreDefaultContextMenusEnabled = True


def install_editing_menu(window):
    """Attach once, after WebView2 initializes; marshal settings onto its UI thread."""
    if getattr(window, "_vox_editing_menu_installed", False) is True:
        return
    try:
        from System import Action
        form = window.native
        def configure():
            configure_editing_menu(form.webview.CoreWebView2)
            window._vox_editing_menu_installed = True
        form.Invoke(Action(configure))
    except Exception as error:
        # Shortcuts remain native. Fail visibly instead of enabling debug mode or
        # exposing unrestricted clipboard access as a fallback.
        print("VOX-9K editing menu could not initialize:", error, file=sys.stderr)
