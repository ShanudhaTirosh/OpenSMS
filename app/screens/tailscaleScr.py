from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDButton, MDButtonIcon, MDButtonText
from kivymd.uix.scrollview import MDScrollView
from kivymd.uix.textfield import MDTextField

from kivy.lang import Builder
from kivy.uix.widget import Widget
from kivy.core.clipboard import Clipboard
from kivy.properties import StringProperty, BooleanProperty
from kivy.metrics import dp, sp

from services.tailscaleSvc import TailscaleService

Builder.load_string('''
<TailscaleBox>:
    orientation: 'vertical'
    spacing: dp(8)

    MDScrollView:
        do_scroll_x: False

        MDBoxLayout:
            orientation: 'vertical'
            adaptive_height: True
            spacing: dp(14)
            padding: dp(8), dp(4), dp(8), dp(16)

            # Tailscale Hero Card
            MDBoxLayout:
                orientation: 'vertical'
                adaptive_height: True
                radius: [dp(16)]
                padding: dp(16)
                spacing: dp(10)
                theme_bg_color: "Custom"
                md_bg_color: [0.05, 0.25, 0.45, 0.15] if app.theme_cls.theme_style == "Light" else [0.08, 0.2, 0.35, 0.7]

                MDBoxLayout:
                    orientation: 'horizontal'
                    adaptive_height: True
                    spacing: dp(8)

                    MDButtonIcon:
                        id: ts_status_icon
                        icon: "shield-check" if root.is_ts_connected else "shield-alert"
                        theme_icon_color: "Custom"
                        icon_color: [0.1, 0.7, 0.3, 1] if root.is_ts_connected else [0.9, 0.6, 0.1, 1]
                        pos_hint: {"center_y": 0.5}

                    MDLabel:
                        id: ts_status_lbl
                        text: "Tailscale Mesh: Connected" if root.is_ts_connected else "Tailscale Mesh: Standby"
                        font_style: "Title"
                        role: "medium"
                        adaptive_height: True
                        pos_hint: {"center_y": 0.5}

                MDDivider:
                    size_hint_x: 1

                MDLabel:
                    text: "Enables direct cross-network SMS dispatching between 2 different networks (e.g. mobile 4G/5G and a remote server/laptop) with zero port forwarding."
                    font_style: "Body"
                    role: "small"
                    theme_text_color: "Secondary"
                    adaptive_height: True

                # Tailscale IP & Endpoint Info
                MDBoxLayout:
                    orientation: 'vertical'
                    adaptive_height: True
                    spacing: dp(4)

                    MDLabel:
                        text: "Tailscale Mesh IP:"
                        font_style: "Label"
                        role: "small"
                        theme_text_color: "Secondary"
                        adaptive_height: True

                    MDLabel:
                        id: ts_ip_lbl
                        text: root.ts_ip_text
                        font_style: "Title"
                        role: "small"
                        theme_text_color: "Primary"
                        adaptive_height: True

                    MDLabel:
                        id: ts_endpoint_lbl
                        text: root.ts_endpoint_text
                        font_style: "Label"
                        role: "medium"
                        theme_text_color: "Secondary"
                        adaptive_height: True

                # Action Buttons
                MDBoxLayout:
                    orientation: 'horizontal'
                    adaptive_height: True
                    spacing: dp(8)
                    pos_hint: {"center_x": 0.5}

                    MDButton:
                        style: "filled"
                        on_release: root.copy_mesh_endpoint()
                        MDButtonIcon:
                            icon: "content-copy"
                        MDButtonText:
                            text: "Copy Remote URL"

                    MDButton:
                        style: "outlined"
                        on_release: root.refresh_status()
                        MDButtonIcon:
                            icon: "refresh"
                        MDButtonText:
                            text: "Refresh"

            # Cross-Network Code Generator Card
            MDBoxLayout:
                orientation: 'vertical'
                adaptive_height: True
                radius: [dp(16)]
                padding: dp(16)
                spacing: dp(10)
                theme_bg_color: "Custom"
                md_bg_color: [0.08, 0.16, 0.32, 0.08] if app.theme_cls.theme_style == "Light" else [0.12, 0.18, 0.28, 0.5]

                MDLabel:
                    text: "Client Code Snippets (Connect from any program)"
                    font_style: "Title"
                    role: "small"
                    adaptive_height: True

                # Language Selector Chips
                MDBoxLayout:
                    orientation: 'horizontal'
                    adaptive_height: True
                    spacing: dp(6)
                    pos_hint: {"center_x": 0.5}

                    MDButton:
                        id: btn_lang_curl
                        style: "filled" if root.selected_lang == "curl" else "outlined"
                        on_release: root.select_lang("curl")
                        MDButtonText:
                            text: "cURL"

                    MDButton:
                        id: btn_lang_py
                        style: "filled" if root.selected_lang == "python" else "outlined"
                        on_release: root.select_lang("python")
                        MDButtonText:
                            text: "Python"

                    MDButton:
                        id: btn_lang_node
                        style: "filled" if root.selected_lang == "nodejs" else "outlined"
                        on_release: root.select_lang("nodejs")
                        MDButtonText:
                            text: "Node.js"

                    MDButton:
                        id: btn_lang_go
                        style: "filled" if root.selected_lang == "go" else "outlined"
                        on_release: root.select_lang("go")
                        MDButtonText:
                            text: "Go"

                # Code Display Box
                MDTextField:
                    id: code_snippet_inp
                    text: root.snippet_code
                    mode: "filled"
                    multiline: True
                    readonly: True
                    adaptive_height: True
                    size_hint_y: None
                    height: dp(140)

                MDButton:
                    style: "tonal"
                    pos_hint: {"center_x": 0.5}
                    on_release: root.copy_snippet_code()
                    MDButtonIcon:
                        icon: "code-tags-check"
                    MDButtonText:
                        text: "Copy Code Snippet"

            # Tailscale Setup Guide Card
            MDBoxLayout:
                orientation: 'vertical'
                adaptive_height: True
                radius: [dp(16)]
                padding: dp(14)
                spacing: dp(6)
                theme_bg_color: "Custom"
                md_bg_color: [0.08, 0.16, 0.32, 0.06] if app.theme_cls.theme_style == "Light" else [0.1, 0.15, 0.22, 0.4]

                MDLabel:
                    text: "How to connect across 2 networks in 2 minutes:"
                    font_style: "Title"
                    role: "small"
                    adaptive_height: True

                MDLabel:
                    text: "1. Install the free Tailscale app on your phone and on your PC/server.\n2. Log in with the same account on both.\n3. Your phone receives a 100.x.y.z IP that is securely accessible from your PC/server anywhere in the world.\n4. Call the remote endpoint shown above to send SMS without exposing public ports!"
                    font_style: "Body"
                    role: "small"
                    theme_text_color: "Secondary"
                    adaptive_height: True
''')

class TailscaleBox(MDBoxLayout):
    is_ts_connected = BooleanProperty(False)
    ts_ip_text = StringProperty("Not connected")
    ts_endpoint_text = StringProperty("Endpoint: http://127.0.0.1:9292/sms/")
    selected_lang = StringProperty("curl")
    snippet_code = StringProperty("")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.port = 9292
        self.cached_snippets = {}

    def update_tailscale_info(self, port: int = 9292, api_key: str = "YOUR_API_KEY"):
        self.port = port
        status = TailscaleService.get_status()
        self.is_ts_connected = status["connected"]

        if self.is_ts_connected and status["ip"]:
            self.ts_ip_text = status["ip"]
            endpoint = f"http://{status['ip']}:{port}/sms/"
            self.ts_endpoint_text = f"Remote Endpoint: {endpoint}"
        else:
            local_ip = status.get("local_ip") or "127.0.0.1"
            self.ts_ip_text = f"Not detected (Local LAN: {local_ip})"
            endpoint = f"http://{local_ip}:{port}/sms/"
            self.ts_endpoint_text = f"Local Endpoint: {endpoint}"

        self.cached_snippets = TailscaleService.generate_code_snippets(endpoint, api_key=api_key)
        self.snippet_code = self.cached_snippets.get(self.selected_lang, "")

    def select_lang(self, lang: str):
        self.selected_lang = lang
        self.snippet_code = self.cached_snippets.get(lang, "")

    def copy_mesh_endpoint(self):
        from kivymd.app import MDApp
        app = MDApp.get_running_app()
        status = TailscaleService.get_status()
        if status["connected"] and status["ip"]:
            url = f"http://{status['ip']}:{self.port}/sms/"
        else:
            local_ip = status.get("local_ip") or "127.0.0.1"
            url = f"http://{local_ip}:{self.port}/sms/"
        Clipboard.copy(url)
        if app and hasattr(app, "show_toast_msg"):
            app.show_toast_msg(f"Copied endpoint: {url}")

    def copy_snippet_code(self):
        from kivymd.app import MDApp
        app = MDApp.get_running_app()
        if self.snippet_code:
            Clipboard.copy(self.snippet_code)
            if app and hasattr(app, "show_toast_msg"):
                app.show_toast_msg(f"Copied {self.selected_lang.upper()} snippet!")

    def refresh_status(self):
        from kivymd.app import MDApp
        app = MDApp.get_running_app()
        port = app.req_template.get("port", 9292) if app else 9292
        self.update_tailscale_info(port=port)
        if app and hasattr(app, "show_toast_msg"):
            app.show_toast_msg("Network & Tailscale status refreshed.")
