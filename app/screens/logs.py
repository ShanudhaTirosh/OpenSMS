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

    MDScrollView:
        do_scroll_x: False

        MDBoxLayout:
            id: log_box
            orientation: "vertical"
            adaptive_height: True

            MDLabel:
                id: log_container
                adaptive_height: True
                valign: "top"
                text: "No logs yet!"
                font_style: "Label"
                role: "small"

''')

class LogBox(MDBoxLayout):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.app_name = "opensms"
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

    def log_show(self, instance=None, top_back_btn=None):
        text_log = ""
        container = self.ids.log_container
        logs = self.logger.get_api_logs()
        for line in reversed(logs):
            clean_line = line.strip()
            if clean_line:
                text_log = text_log + f"{clean_line}\n"
        container.text = text_log if text_log else "No logs yet!"


        if instance:
            if top_back_btn:
                top_back_btn.opacity = 1
                top_back_btn.disabled = False
            # hamburger menu
            instance.opacity = 1
            instance.disabled = False
            menu_items = [
                {
                    "text": menu_key,
                    "leading_icon": self.top_menu_items[menu_key]["icon"],
                    "on_release": lambda x=menu_key: self.top_menu_callback(x),
                    "font_size": sp(36)
                } for menu_key in self.top_menu_items
            ]
            self.top_menu = MDDropdownMenu(
                items=menu_items,
                caller=instance
            )
            instance.on_release = self.show_top_menu

    def show_top_menu(self, instance=None):
        self.top_menu.open()

    def top_menu_callback(self, text_item:str):
        self.top_menu.dismiss()
        menu = self.top_menu_items.get(text_item)
        action = menu.get("action", None)
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
        container.text = ""
        Thread(target=self.logger.clear_logs, daemon=True).start()

    def on_log_scr_exit(self, instance=None):
        if instance:
            # hamburger menu
            instance.opacity = 0
            instance.disabled = True
