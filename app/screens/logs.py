from threading import Thread

from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.button import MDButton, MDButtonIcon, MDButtonText

from kivy.lang import Builder
from kivy.uix.widget import Widget
from kivy.core.clipboard import Clipboard
from kivy.properties import StringProperty, NumericProperty, ObjectProperty, ColorProperty
from kivy.metrics import dp, sp
from kivy.utils import platform

# local imports
from services.logSvc import LogService

Builder.load_string('''

<LogBox>:
    orientation: "vertical"
    spacing: dp(8)

    # Filter Bar
    MDBoxLayout:
        orientation: "horizontal"
        adaptive_height: True
        spacing: dp(8)
        padding: dp(8), dp(4)
        pos_hint: {"center_x": .5}

        MDButton:
            id: filter_all_btn
            style: "filled"
            on_release: root.set_filter("all")
            MDButtonText:
                text: "All"

        MDButton:
            id: filter_err_btn
            style: "outlined"
            on_release: root.set_filter("error")
            MDButtonText:
                text: "Errors"

        MDButton:
            id: filter_sms_btn
            style: "outlined"
            on_release: root.set_filter("sms")
            MDButtonText:
                text: "SMS"

    MDScrollView:
        do_scroll_x: False

        MDBoxLayout:
            id: log_box
            orientation: "vertical"
            adaptive_height: True
            padding: dp(8), dp(4)

            MDLabel:
                id: log_container
                adaptive_height: True
                valign: "top"
                text: "No logs yet!"
                font_style: "Label"
                role: "small"
                theme_text_color: "Primary"

''')

class LogBox(MDBoxLayout):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.app_name = "opensms"
        self.current_filter = "all"
        self.top_menu = None
        self.top_menu_items = {
            "Refresh": {
                "icon": "refresh",
                "action": "refresh",
            },
            "Copy Logs": {
                "icon": "content-copy",
                "action": "copy-logs",
            },
            "Clear Logs": {
                "icon": "broom",
                "action": "clear-logs",
            }
        }
        self.logger = LogService(self.app_name, platform)

    def set_filter(self, filter_name: str):
        self.current_filter = filter_name
        # Update button styles
        try:
            self.ids.filter_all_btn.style = "filled" if filter_name == "all" else "outlined"
            self.ids.filter_err_btn.style = "filled" if filter_name == "error" else "outlined"
            self.ids.filter_sms_btn.style = "filled" if filter_name == "sms" else "outlined"
        except Exception:
            pass
        self.log_show()

    def log_show(self, instance=None, top_back_btn=None):
        container = self.ids.log_container
        raw_logs = self.logger.get_api_logs()

        # Bounded memory rendering: keep only the latest 200 entries to prevent OpenGL texture crash
        recent_logs = raw_logs[-200:]

        filtered_lines = []
        for line in reversed(recent_logs):
            clean_line = line.strip()
            if not clean_line:
                continue

            lower_line = clean_line.lower()
            if self.current_filter == "error":
                if "error" in lower_line or "failed" in lower_line or "401" in lower_line or "429" in lower_line:
                    filtered_lines.append(clean_line)
            elif self.current_filter == "sms":
                if "sms" in lower_line or "batch" in lower_line:
                    filtered_lines.append(clean_line)
            else:
                filtered_lines.append(clean_line)

        if filtered_lines:
            container.text = "\n".join(filtered_lines)
        else:
            container.text = f"No logs matching filter '{self.current_filter}'."

        if instance:
            if top_back_btn:
                top_back_btn.opacity = 1
                top_back_btn.disabled = False
            # Setup top menu cleanly without memory leak
            instance.opacity = 1
            instance.disabled = False
            if not self.top_menu:
                menu_items = [
                    {
                        "text": menu_key,
                        "leading_icon": self.top_menu_items[menu_key]["icon"],
                        "on_release": lambda x=menu_key: self.top_menu_callback(x),
                        "font_size": sp(16)
                    } for menu_key in self.top_menu_items
                ]
                self.top_menu = MDDropdownMenu(
                    items=menu_items,
                    caller=instance
                )
            instance.on_release = self.show_top_menu

    def show_top_menu(self, instance=None):
        if self.top_menu:
            self.top_menu.open()

    def top_menu_callback(self, text_item: str):
        if self.top_menu:
            self.top_menu.dismiss()
        menu = self.top_menu_items.get(text_item)
        action = menu.get("action", None) if menu else None
        if action:
            if action == "clear-logs":
                self.clear_logs()
            elif action == "copy-logs":
                self.copy_logs()
            elif action == "refresh":
                self.log_show()

    def copy_logs(self):
        container = self.ids.log_container
        Clipboard.copy(container.text)

    def clear_logs(self, instance=None):
        container = self.ids.log_container
        container.text = "Logs cleared."
        Thread(target=self.logger.clear_logs, daemon=True).start()

    def on_log_scr_exit(self, instance=None):
        if self.top_menu:
            self.top_menu.dismiss()
        if instance:
            instance.opacity = 0
            instance.disabled = True
