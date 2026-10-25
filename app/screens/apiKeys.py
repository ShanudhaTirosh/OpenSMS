"""API keys screen: list, create (shown once), revoke with confirmation."""
from threading import Thread

from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDButton, MDButtonText, MDButtonIcon
from kivymd.uix.dialog import MDDialogButtonContainer, MDDialogContentContainer
from kivymd.uix.label import MDLabel
from kivymd.uix.textfield import MDTextField, MDTextFieldHintText

from kivy.clock import Clock
from kivy.core.clipboard import Clipboard
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import StringProperty, BooleanProperty, ListProperty
from kivy.uix.widget import Widget

from services.dbMgr import DatabaseManager
from services import uiFormat as U
from services import authSvc
from screens.components import StatusChip, EmptyState, SkeletonRow, card_color  # noqa: F401

Builder.load_string('''
<KeyRow>:
    orientation: "vertical"
    adaptive_height: True
    padding: dp(14), dp(12)
    spacing: dp(6)
    radius: [dp(12)]
    theme_bg_color: "Custom"
    md_bg_color: root.bg_color

    MDBoxLayout:
        orientation: "horizontal"
        adaptive_height: True
        spacing: dp(8)

        MDLabel:
            text: root.title
            font_style: "Title"
            role: "small"
            adaptive_height: True
            shorten: True
            shorten_from: "right"
            pos_hint: {"center_y": 0.5}

        StatusChip:
            text: root.state_text
            icon: "check-circle-outline" if root.active else "cancel"
            chip_color: [0.15, 0.65, 0.30, 1] if root.active else [0.60, 0.60, 0.65, 1]

    MDLabel:
        text: root.prefix + "   \u2022   " + root.scopes
        font_style: "Body"
        role: "small"
        theme_text_color: "Secondary"
        adaptive_height: True

    MDLabel:
        text: "Created " + root.created + "   \u2022   Last used: " + root.last_used
        font_style: "Label"
        role: "medium"
        theme_text_color: "Secondary"
        adaptive_height: True

    MDBoxLayout:
        id: actions
        adaptive_height: True
        padding: 0, dp(4), 0, 0

        Widget:

        MDButton:
            style: "outlined"
            height: dp(48)
            on_release: root.on_revoke(root.key_id)
            MDButtonIcon:
                icon: "key-remove"
            MDButtonText:
                text: "Revoke"

<ApiKeysBox>:
    orientation: "vertical"
    spacing: dp(8)

    MDBoxLayout:
        orientation: "vertical"
        adaptive_height: True
        padding: dp(14)
        spacing: dp(8)
        radius: [dp(16)]
        theme_bg_color: "Custom"
        md_bg_color: [0.08, 0.28, 0.52, 0.16] if app.theme_style == "Light" else [0.09, 0.22, 0.38, 0.8]

        MDLabel:
            text: "API keys"
            font_style: "Title"
            role: "medium"
            adaptive_height: True

        MDLabel:
            text: root.info_text
            font_style: "Body"
            role: "small"
            theme_text_color: "Secondary"
            adaptive_height: True

        MDButton:
            style: "filled"
            height: dp(48)
            on_release: root.show_create_dialog()
            MDButtonIcon:
                icon: "key-plus"
            MDButtonText:
                text: "New key"

    MDScrollView:
        do_scroll_x: False

        MDBoxLayout:
            id: list_box
            orientation: "vertical"
            adaptive_height: True
            spacing: dp(8)
            padding: dp(4), dp(4), dp(4), dp(16)
''')


class KeyRow(MDBoxLayout):
    key_id = StringProperty("")
    title = StringProperty("")
    prefix = StringProperty("")
    scopes = StringProperty("")
    created = StringProperty("")
    last_used = StringProperty("")
    state_text = StringProperty("")
    active = BooleanProperty(True)
    bg_color = ListProperty([0.1, 0.1, 0.1, 0.1])

    def __init__(self, row: dict, on_revoke, theme_style="Light", **kw):
        super().__init__(**kw)
        self.key_id, self.title, self.prefix = row["id"], row["title"], row["prefix"]
        self.scopes, self.created, self.last_used = row["scopes"], row["created"], row["last_used"]
        self.state_text, self.active = row["state"], row["active"]
        self.bg_color = card_color(theme_style)
        self._on_revoke = on_revoke
        if not row["active"]:   # revoked keys have no actions: remove the row instead of leaving dead space
            self.remove_widget(self.ids.actions)

    def on_revoke(self, key_id):
        self._on_revoke(key_id, self.title)


class ApiKeysBox(MDBoxLayout):
    info_text = StringProperty("")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._busy = False
        self.info_text = (
            "A key is shown once when created; only its hash is stored. Revoking takes effect immediately. "
            f"Send limit: {authSvc.SEND_RATE_PER_MINUTE} messages per minute per key."
            if authSvc.SEND_RATE_PER_MINUTE > 0 else
            "A key is shown once when created; only its hash is stored. Revoking takes effect immediately.")

    # ------------------------------------------------------------ helpers
    def _app(self):
        return MDApp.get_running_app()

    def _db(self):
        return DatabaseManager.get_instance(self._app().config_dir)

    def _theme(self):
        return getattr(self._app(), "theme_style", "Light")

    # ------------------------------------------------------------ list
    def reload(self):
        box = self.ids.list_box
        box.clear_widgets()
        for _ in range(2):
            box.add_widget(SkeletonRow())

        def worker():
            try:
                rows = [U.key_row(k) for k in self._db().list_api_keys()]
                err = None
            except Exception as e:
                rows, err = [], str(e)
            Clock.schedule_once(lambda dt: self._apply(rows, err), 0)
        Thread(target=worker, daemon=True).start()

    def _apply(self, rows, err):
        box = self.ids.list_box
        box.clear_widgets()
        if err:
            box.add_widget(EmptyState(icon="alert-circle-outline", title="Could not load keys", subtitle=err))
            retry = MDButton(MDButtonText(text="Retry"), style="tonal", pos_hint={"center_x": 0.5})
            retry.bind(on_release=lambda *_: self.reload())
            box.add_widget(retry)
            return
        if not rows:
            box.add_widget(EmptyState(
                icon="key-outline", title="No API keys yet",
                subtitle="Create a key so your apps can call the gateway. Without one every request is refused."))
            return
        theme = self._theme()
        # active keys first, then revoked
        for row in sorted(rows, key=lambda r: not r["active"]):
            box.add_widget(KeyRow(row, self._confirm_revoke, theme_style=theme))

    # ------------------------------------------------------------ create
    def show_create_dialog(self):
        app = self._app()
        state = {"scopes": {"sms:write", "sms:read"}}

        name_field = MDTextField(MDTextFieldHintText(text="Key name (e.g. Home server)"), mode="outlined",
                                 size_hint_y=None, height=dp(56))
        error_lbl = MDLabel(text="", theme_text_color="Custom", text_color=(0.85, 0.25, 0.25, 1),
                            font_style="Label", role="medium", adaptive_height=True)
        note_lbl = MDLabel(text="", theme_text_color="Secondary", font_style="Label", role="medium", adaptive_height=True)
        toggles = {}

        def refresh_toggles():
            for scope, btn in toggles.items():
                btn.style = "filled" if scope in state["scopes"] else "outlined"
            note_lbl.text = ("Admin keys can create and revoke keys and call /control/. Keep them private."
                             if "admin" in state["scopes"] else "")

        def toggle(scope):
            if scope in state["scopes"]:
                if len(state["scopes"]) > 1:
                    state["scopes"].discard(scope)
                else:
                    error_lbl.text = "A key needs at least one permission."
                    return
            else:
                state["scopes"].add(scope)
            error_lbl.text = ""
            refresh_toggles()

        row = MDBoxLayout(orientation="horizontal", adaptive_height=True, spacing=dp(6))
        for scope, label in (("sms:write", "Send"), ("sms:read", "Read"), ("admin", "Admin")):
            b = MDButton(MDButtonText(text=label), style="outlined")
            b.bind(on_release=lambda _b, s=scope: toggle(s))
            toggles[scope] = b
            row.add_widget(b)
        refresh_toggles()

        content = MDDialogContentContainer(orientation="vertical", spacing=dp(10))
        content.add_widget(name_field)
        content.add_widget(row)
        content.add_widget(note_lbl)
        content.add_widget(error_lbl)

        create_btn = MDButton(MDButtonText(text="Create", theme_text_color="Custom", text_color="green"), style="text")

        def do_create(*_):
            if self._busy:           # prevent duplicate submissions
                return
            err = U.valid_key_name(name_field.text)
            if err:
                error_lbl.text = err   # inline validation; the dialog and typed input stay
                return
            self._busy = True
            create_btn.disabled = True
            try:
                from services import postApi
                if postApi.db_mgr is None:
                    postApi.set_config_path(app.config_dir)
                raw = postApi.generate_new_api_key(name_field.text.strip(), sorted(state["scopes"]))
            except Exception as e:
                self._busy = False
                create_btn.disabled = False
                error_lbl.text = f"Could not create the key: {e}"
                return
            self._busy = False
            app.txt_dialog_closer()
            self.reload()
            self._show_new_key(raw, name_field.text.strip())

        create_btn.bind(on_release=do_create)
        buttons = MDDialogButtonContainer(
            Widget(),
            MDButton(MDButtonText(text="Cancel"), style="text", on_release=app.txt_dialog_closer),
            create_btn,
            spacing="8dp",
        )
        app.show_text_dialog("New API key", "Choose what this key may do.", content, buttons)

    def _show_new_key(self, raw: str, name: str):
        app = self._app()

        def close(*_):
            app.txt_dialog_closer()

        buttons = MDDialogButtonContainer(
            Widget(),
            MDButton(MDButtonText(text="Copy key"), style="text",
                     on_release=lambda *_: (Clipboard.copy(raw), app.show_toast_msg("Key copied"))),
            MDButton(MDButtonText(text="Done"), style="text", on_release=close),
            spacing="8dp",
        )
        app.show_text_dialog(
            f"Key '{name}' created",
            f"{raw}\n\nCopy it now and store it safely. It will not be shown again.",
            None, buttons)

    # ------------------------------------------------------------ revoke
    def _confirm_revoke(self, key_id: str, name: str):
        app = self._app()

        def do_revoke(*_):
            app.txt_dialog_closer()
            try:
                ok = self._db().revoke_api_key(key_id)
            except Exception as e:
                app.show_toast_msg(f"Could not revoke: {e}", is_error=True)
                return
            app.show_toast_msg("Key revoked" if ok else "Key not found", is_error=not ok)
            self.reload()

        buttons = MDDialogButtonContainer(
            Widget(),
            MDButton(MDButtonText(text="Cancel"), style="text", on_release=app.txt_dialog_closer),
            MDButton(MDButtonText(text="Revoke", theme_text_color="Custom", text_color="red"), style="text",
                     on_release=do_revoke),
            spacing="8dp",
        )
        app.show_text_dialog(f"Revoke '{name}'?",
                             "Every client using this key will stop working immediately. This cannot be undone.",
                             None, buttons)
