"""API keys screen: list, create (shown once), revoke with confirmation."""
import time
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

        MDBoxLayout:
            orientation: "horizontal"
            adaptive_height: True
            spacing: dp(8)

            MDButton:
                style: "filled"
                height: dp(48)
                on_release: root.show_create_dialog()
                MDButtonIcon:
                    icon: "key-plus"
                MDButtonText:
                    text: "New key"

            MDButton:
                style: "tonal"
                height: dp(48)
                on_release: root.show_webhooks_dialog()
                MDButtonIcon:
                    icon: "webhook"
                MDButtonText:
                    text: "Webhooks"

            MDButton:
                style: "tonal"
                height: dp(48)
                on_release: root.show_quick_connect_dialog()
                MDButtonIcon:
                    icon: "link-variant"
                MDButtonText:
                    text: "Connect"

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
                                 input_type="text", size_hint_y=None, height=dp(56))
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

    def show_quick_connect_dialog(self):
        self._app().show_quick_connect_dialog()

    # ------------------------------------------------------------ webhooks
    def show_webhooks_dialog(self):
        app = self._app()
        db = self._db()
        hooks = db.list_webhooks()

        content = MDDialogContentContainer(orientation="vertical", spacing=dp(8))
        if not hooks:
            content.add_widget(MDLabel(
                text="No webhooks registered.\nAdd a webhook endpoint to receive real-time notifications on delivery reports and status changes.",
                theme_text_color="Secondary",
                font_style="Body",
                role="medium",
                adaptive_height=True
            ))
        else:
            for h in hooks:
                h_box = MDBoxLayout(orientation="vertical", adaptive_height=True, spacing=dp(4), padding=dp(8))
                h_url = MDLabel(text=h.get("url", ""), font_style="Title", role="small", adaptive_height=True)
                evs = ", ".join(h.get("events") or [])
                h_sub = MDLabel(text=f"Events: {evs}", font_style="Body", role="small", theme_text_color="Secondary", adaptive_height=True)
                btn_row = MDBoxLayout(orientation="horizontal", adaptive_height=True, spacing=dp(8))
                test_b = MDButton(MDButtonText(text="Test"), style="text")
                test_b.bind(on_release=lambda *_, hid=h["id"]: self._test_webhook(hid))
                del_b = MDButton(MDButtonText(text="Delete", theme_text_color="Custom", text_color="red"), style="text")
                del_b.bind(on_release=lambda *_, hid=h["id"], hurl=h.get("url", ""): self._confirm_delete_webhook(hid, hurl))
                btn_row.add_widget(test_b)
                btn_row.add_widget(del_b)
                h_box.add_widget(h_url)
                h_box.add_widget(h_sub)
                h_box.add_widget(btn_row)
                content.add_widget(h_box)

        buttons = MDDialogButtonContainer(
            Widget(),
            MDButton(
                MDButtonText(text="Add Webhook"),
                style="text",
                on_release=lambda *_: (app.txt_dialog_closer(), self.show_add_webhook_dialog())
            ),
            MDButton(
                MDButtonText(text="Close"),
                style="text",
                on_release=app.txt_dialog_closer
            ),
            spacing="8dp",
        )
        app.show_text_dialog("Delivery Webhooks", "Notify your HTTP service on message delivery.", content, buttons)

    def show_add_webhook_dialog(self):
        app = self._app()
        url_field = MDTextField(
            MDTextFieldHintText(text="Webhook URL (https://...)"),
            mode="outlined",
            size_hint_y=None,
            height=dp(56)
        )
        secret_field = MDTextField(
            MDTextFieldHintText(text="Secret key (optional, for HMAC signature)"),
            mode="outlined",
            size_hint_y=None,
            height=dp(56)
        )
        error_lbl = MDLabel(
            text="",
            theme_text_color="Custom",
            text_color=(0.85, 0.25, 0.25, 1),
            font_style="Label",
            role="medium",
            adaptive_height=True
        )

        content = MDDialogContentContainer(orientation="vertical", spacing=dp(8))
        content.add_widget(url_field)
        content.add_widget(secret_field)
        content.add_widget(error_lbl)

        def do_add(*_):
            raw_url = url_field.text.strip()
            if not (raw_url.startswith("http://") or raw_url.startswith("https://")):
                error_lbl.text = "URL must start with http:// or https://"
                return
            try:
                secret = secret_field.text.strip() or None
                self._db().add_webhook(url=raw_url, events=["sms.sent", "sms.delivered", "sms.failed"], secret=secret)
                app.txt_dialog_closer()
                app.show_toast_msg("Webhook added successfully")
                self.show_webhooks_dialog()
            except Exception as e:
                error_lbl.text = f"Failed to add webhook: {e}"

        buttons = MDDialogButtonContainer(
            Widget(),
            MDButton(
                MDButtonText(text="Cancel"),
                style="text",
                on_release=lambda *_: (app.txt_dialog_closer(), self.show_webhooks_dialog())
            ),
            MDButton(
                MDButtonText(text="Save", theme_text_color="Custom", text_color="green"),
                style="text",
                on_release=do_add
            ),
            spacing="8dp",
        )
        app.show_text_dialog("Add Webhook", "Deliver SMS status updates via HTTP POST.", content, buttons)

    def _test_webhook(self, webhook_id: str):
        app = self._app()
        def worker():
            from services.webhookSvc import send_webhook_request
            wh = self._db().get_webhook(webhook_id, include_secret=True)
            if not wh:
                Clock.schedule_once(lambda dt: app.show_toast_msg("Webhook not found", is_error=True), 0)
                return
            payload = {
                "event": "test.ping",
                "timestamp": int(time.time()),
                "message": {"id": "test-id", "status": "delivered", "text": "Test ping from OpenSMS"}
            }
            ok, status_code, err = send_webhook_request(wh["url"], payload, wh.get("secret"))
            if ok:
                msg = f"Test webhook delivered successfully (HTTP {status_code})"
                is_err = False
            else:
                msg = f"Test failed: HTTP {status_code or 'error'} ({err})"
                is_err = True
            Clock.schedule_once(lambda dt: app.show_toast_msg(msg, is_error=is_err), 0)

        Thread(target=worker, daemon=True).start()

    def _confirm_delete_webhook(self, webhook_id: str, url: str):
        app = self._app()
        def do_delete(*_):
            app.txt_dialog_closer()
            self._db().delete_webhook(webhook_id)
            app.show_toast_msg("Webhook deleted")
            self.show_webhooks_dialog()

        buttons = MDDialogButtonContainer(
            Widget(),
            MDButton(MDButtonText(text="Cancel"), style="text", on_release=lambda *_: (app.txt_dialog_closer(), self.show_webhooks_dialog())),
            MDButton(MDButtonText(text="Delete", theme_text_color="Custom", text_color="red"), style="text", on_release=do_delete),
            spacing="8dp",
        )
        app.show_text_dialog("Delete Webhook?", f"Delete webhook destination:\n{url}", None, buttons)

