"""System screen: diagnostics with plain-language hints, a copyable report and safe history maintenance."""
import json
import os
import sys
import time
from threading import Thread

from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDButton, MDButtonText, MDButtonIcon
from kivymd.uix.dialog import MDDialogButtonContainer

from kivy.clock import Clock
from kivy.core.clipboard import Clipboard
from kivy.lang import Builder
from kivy.properties import StringProperty, ListProperty
from kivy.uix.widget import Widget

from app_version import __version__, UPDATE_REPO
from services.dbMgr import DatabaseManager
from services import diagnostics as D
from services.lifecycle import resp_is_fresh
from services.smsApi import get_active_sims_with_status
from services.tailscaleSvc import TailscaleService
from screens.components import EmptyState, SkeletonRow, card_color  # noqa: F401 (registers KV rules)

_LEVEL = {
    D.OK: ("check-circle-outline", (0.15, 0.65, 0.30, 1)),
    D.INFO: ("information-outline", (0.45, 0.50, 0.60, 1)),
    D.WARN: ("alert-outline", (0.85, 0.60, 0.10, 1)),
    D.ERROR: ("close-circle-outline", (0.80, 0.25, 0.25, 1)),
}

Builder.load_string('''
<DiagRow>:
    orientation: "horizontal"
    adaptive_height: True
    spacing: dp(10)

    MDIcon:
        icon: root.icon
        theme_icon_color: "Custom"
        icon_color: root.icon_color
        size_hint: None, None
        size: dp(20), dp(20)
        pos_hint: {"top": 1}

    MDBoxLayout:
        orientation: "vertical"
        adaptive_height: True
        spacing: dp(2)

        MDLabel:
            text: root.text
            font_style: "Body"
            role: "medium"
            adaptive_height: True

        MDLabel:
            text: root.hint
            font_style: "Body"
            role: "small"
            theme_text_color: "Secondary"
            adaptive_height: True
            opacity: 1 if root.hint else 0
            size_hint_y: None
            height: self.texture_size[1] if root.hint else 0

<SystemBox>:
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
            text: root.overall_text
            font_style: "Title"
            role: "medium"
            adaptive_height: True

        MDGridLayout:
            cols: 2
            adaptive_height: True
            spacing: dp(8)

            MDButton:
                style: "filled"
                height: dp(48)
                on_release: root.refresh()
                MDButtonIcon:
                    icon: "refresh"
                MDButtonText:
                    text: "Refresh"

            MDButton:
                style: "tonal"
                height: dp(48)
                on_release: root.copy_report()
                MDButtonIcon:
                    icon: "content-copy"
                MDButtonText:
                    text: "Copy report"

    MDScrollView:
        do_scroll_x: False

        MDBoxLayout:
            id: list_box
            orientation: "vertical"
            adaptive_height: True
            spacing: dp(8)
            padding: dp(4), dp(4), dp(4), dp(16)
''')


class DiagRow(MDBoxLayout):
    text = StringProperty("")
    hint = StringProperty("")
    icon = StringProperty("information-outline")
    icon_color = ListProperty([0.5, 0.5, 0.5, 1])

    def __init__(self, row: dict, **kw):
        super().__init__(**kw)
        self.icon, color = _LEVEL.get(row["level"], _LEVEL[D.INFO])
        self.icon_color = list(color)
        self.text = f"{row['label']}: {row['value']}"
        self.hint = row.get("hint") or ""


def gather_facts(app) -> dict:
    """Collect raw facts. Every probe is guarded: a failing probe must never break the screen."""
    from kivy.utils import platform
    facts = {"android": platform == "android", "version": __version__, "repo": UPDATE_REPO,
             "platform_text": f"{platform}, Python {sys.version.split()[0]}"}
    cfg = getattr(app, "config_template", {})
    facts["server_desired"] = cfg.get("server_desired")
    facts["bind"] = cfg.get("bind_mode", "all")
    facts["wakelock_setting"] = cfg.get("wakelock", True)

    resp = {}
    try:
        with open(app.resp_path, "r", encoding="utf-8") as f:
            resp = json.load(f)
    except (OSError, ValueError, AttributeError):
        pass
    fresh = resp_is_fresh(resp)
    facts["service_alive"] = fresh
    facts["heartbeat_age"] = (time.time() - resp["ts"]) if fresh else None
    for k in ("server", "port", "host", "error"):
        facts[k] = resp.get(k) if fresh else None
    if fresh and resp.get("bind"):
        facts["bind"] = resp["bind"]
    facts["diag"] = resp.get("diag") or {} if fresh else {}

    if facts["android"]:
        try:
            from android.permissions import check_permission, Permission
            facts["perm_sms"] = bool(check_permission(Permission.SEND_SMS))
            facts["perm_phone"] = bool(check_permission(Permission.READ_PHONE_STATE))
        except Exception:
            pass
        try:
            sims, reliable = get_active_sims_with_status()
            facts["sims"] = {"reliable": reliable, "count": len(sims) if reliable else 0}
        except Exception:
            facts["sims"] = {"reliable": False}
        try:
            from jnius import autoclass
            facts["platform_text"] = f"Android {autoclass('android.os.Build$VERSION').RELEASE} " \
                                     f"(API {autoclass('android.os.Build$VERSION').SDK_INT}), Python {sys.version.split()[0]}"
        except Exception:
            pass
    try:
        st = TailscaleService.get_status(bind_mode=facts["bind"])
        facts["tailscale"] = {"state": st["state"], "ip": st["ip"]}
        facts["local_ip"] = st.get("local_ip")
    except Exception:
        pass
    try:
        facts["db"] = DatabaseManager.get_instance(app.config_dir).storage_stats()
    except Exception:
        facts["db"] = {}
    return facts


class SystemBox(MDBoxLayout):
    overall_text = StringProperty("Checking...")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.sections = []

    def _app(self):
        return MDApp.get_running_app()

    def refresh(self):
        box = self.ids.list_box
        box.clear_widgets()
        for _ in range(3):
            box.add_widget(SkeletonRow())
        app = self._app()

        def worker():
            try:
                sections = D.build_sections(gather_facts(app))
                err = None
            except Exception as e:
                sections, err = [], str(e)
            Clock.schedule_once(lambda dt: self._apply(sections, err), 0)
        Thread(target=worker, daemon=True).start()

    def _apply(self, sections, err):
        box = self.ids.list_box
        box.clear_widgets()
        if err:
            self.overall_text = "Diagnostics unavailable"
            box.add_widget(EmptyState(icon="alert-circle-outline", title="Could not collect diagnostics", subtitle=err))
            return
        self.sections = sections
        self.overall_text = {D.OK: "Everything looks fine", D.WARN: "Needs attention", D.ERROR: "Problems found"}[D.overall_level(sections)]
        theme = getattr(self._app(), "theme_style", "Light")
        for section in sections:
            card = MDBoxLayout(orientation="vertical", adaptive_height=True, padding=dp_(14), spacing=dp_(8),
                               radius=[dp_(14)], theme_bg_color="Custom", md_bg_color=card_color(theme))
            card.add_widget(_title(section["title"]))
            for row in section["rows"]:
                card.add_widget(DiagRow(row))
            box.add_widget(card)
        box.add_widget(self._maintenance_card(theme))

    # ------------------------------------------------------------ maintenance
    def _maintenance_card(self, theme):
        card = MDBoxLayout(orientation="vertical", adaptive_height=True, padding=dp_(14), spacing=dp_(8),
                           radius=[dp_(14)], theme_bg_color="Custom", md_bg_color=card_color(theme))
        card.add_widget(_title("Maintenance"))
        for text, icon, handler in (
                ("Clear messages older than 30 days", "delete-clock-outline", lambda *_: self._confirm_clear(30)),
                ("Clear all finished messages", "delete-sweep-outline", lambda *_: self._confirm_clear(None)),
                ("Battery settings", "battery-heart-variant", lambda *_: self._app().open_battery_settings())):
            b = MDButton(MDButtonIcon(icon=icon), MDButtonText(text=text), style="outlined", height=dp_(48))
            b.bind(on_release=handler)
            card.add_widget(b)
        return card

    def _confirm_clear(self, days):
        app = self._app()
        what = "all finished messages" if days is None else f"finished messages older than {days} days"

        def do_clear(*_):
            app.txt_dialog_closer()
            cutoff = None if days is None else time.time() - days * 86400

            def worker():
                try:
                    n = DatabaseManager.get_instance(app.config_dir).purge_messages(cutoff)
                    msg, err = f"Removed {n} message(s)", False
                except Exception as e:
                    msg, err = f"Could not clear messages: {e}", True
                Clock.schedule_once(lambda dt: (app.show_toast_msg(msg, is_error=err), self.refresh()), 0)
            Thread(target=worker, daemon=True).start()

        buttons = MDDialogButtonContainer(
            Widget(),
            MDButton(MDButtonText(text="Cancel"), style="text", on_release=app.txt_dialog_closer),
            MDButton(MDButtonText(text="Delete", theme_text_color="Custom", text_color="red"), style="text", on_release=do_clear),
            spacing="8dp",
        )
        app.show_text_dialog(f"Delete {what}?",
                             "This cannot be undone. Messages that are still being sent are never deleted, and API keys are not affected.",
                             None, buttons)

    # ------------------------------------------------------------ report
    def copy_report(self):
        app = self._app()
        if not self.sections:
            app.show_toast_msg("Nothing to copy yet", is_error=True)
            return
        Clipboard.copy(D.to_text(self.sections, f"OpenSMS {__version__} diagnostics"))
        app.show_toast_msg("Report copied (contains no keys, numbers or message text)")


def dp_(v):
    from kivy.metrics import dp
    return dp(v)


def _title(text):
    from kivymd.uix.label import MDLabel
    return MDLabel(text=text, font_style="Title", role="small", adaptive_height=True)
