from threading import Thread

from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDButton, MDButtonIcon, MDButtonText
from kivymd.uix.scrollview import MDScrollView
from kivymd.uix.textfield import MDTextField

from kivy.lang import Builder
from kivy.uix.widget import Widget
from kivy.core.clipboard import Clipboard
from kivy.properties import StringProperty, BooleanProperty
from kivy.metrics import dp, sp
from kivy.clock import Clock

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

            # In-App Tailscale Direct Key Setup Card
            MDBoxLayout:
                orientation: 'vertical'
                adaptive_height: True
                radius: [dp(16)]
                padding: dp(16)
                spacing: dp(10)
                theme_bg_color: "Custom"
                md_bg_color: [0.08, 0.28, 0.52, 0.16] if app.theme_style == "Light" else [0.09, 0.22, 0.38, 0.8]

                MDBoxLayout:
                    orientation: 'horizontal'
                    adaptive_height: True
                    spacing: dp(8)

                    MDButtonIcon:
                        icon: "key-wireless"
                        theme_icon_color: "Custom"
                        icon_color: [0.15, 0.65, 0.95, 1]
                        pos_hint: {"center_y": 0.5}

                    MDLabel:
                        text: "In-App Tailscale Connection"
                        font_style: "Title"
                        role: "medium"
                        adaptive_height: True
                        pos_hint: {"center_y": 0.5}

                MDLabel:
                    text: "Enter your Tailscale API Key (tskey-api-...), Auth Key (tskey-auth-...), or Tailscale 100.x.y.z IP. OpenSMS connects directly and extracts your mesh endpoint."
                    font_style: "Body"
                    role: "small"
                    theme_text_color: "Secondary"
                    adaptive_height: True

                MDTextField:
                    id: ts_key_inp
                    text: root.ts_key_input_text
                    mode: "outlined"
                    hint_text: "Tailscale Key or IP (tskey-api-... / 100.x.y.z)"
                    size_hint_y: None
                    height: dp(56)

                # Key Action Buttons
                MDBoxLayout:
                    orientation: 'horizontal'
                    adaptive_height: True
                    spacing: dp(8)
                    pos_hint: {"center_x": 0.5}

                    MDButton:
                        style: "filled"
                        on_release: root.connect_key()
                        MDButtonIcon:
                            icon: "lan-connect"
                        MDButtonText:
                            text: "Connect & Get IP"

                    MDButton:
                        style: "outlined"
                        on_release: root.disconnect_key()
                        MDButtonIcon:
                            icon: "lan-disconnect"
                        MDButtonText:
                            text: "Disconnect"

                    MDButton:
                        style: "tonal"
                        on_release: app.show_key_help_dialog()
                        MDButtonIcon:
                            icon: "help-circle-outline"
                        MDButtonText:
                            text: "Help"

                # In-App Key Status Details
                MDLabel:
                    id: ts_key_status_lbl
                    text: root.ts_key_status_text
                    font_style: "Label"
                    role: "small"
                    theme_text_color: "Custom"
                    text_color: [0.1, 0.7, 0.35, 1] if root.is_ts_connected else [0.75, 0.45, 0.1, 1]
                    adaptive_height: True

            # Tailscale Hero Status Card
            MDBoxLayout:
                orientation: 'vertical'
                adaptive_height: True
                radius: [dp(16)]
                padding: dp(16)
                spacing: dp(10)
                theme_bg_color: "Custom"
                md_bg_color: [0.05, 0.25, 0.45, 0.12] if app.theme_style == "Light" else [0.08, 0.18, 0.32, 0.65]

                MDBoxLayout:
                    orientation: 'horizontal'
                    adaptive_height: True
                    spacing: dp(8)

                    MDButtonIcon:
                        id: ts_status_icon
                        icon: "shield-check" if root.is_ts_connected else "shield-off"
                        theme_icon_color: "Custom"
                        icon_color: [0.1, 0.75, 0.35, 1] if root.is_ts_connected else [0.85, 0.3, 0.3, 1]
                        pos_hint: {"center_y": 0.5}

                    MDLabel:
                        id: ts_status_lbl
                        text: "Tailscale Mesh: Connected" if root.is_ts_connected else "Tailscale: Not Connected"
                        font_style: "Title"
                        role: "medium"
                        adaptive_height: True
                        pos_hint: {"center_y": 0.5}

                MDDivider:
                    size_hint_x: 1

                MDLabel:
                    text: "Worldwide cross-network SMS dispatch active via Tailscale WireGuard mesh." if root.is_ts_connected else "Tailscale mesh is not active. Connect using your Key/IP above or install Tailscale to enable secure remote access anywhere."
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
                        text: "Tailscale Mesh IP:" if root.is_ts_connected else "Network Status:"
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
                            text: "Copy Remote URL" if root.is_ts_connected else "Copy Local URL"

                    MDButton:
                        style: "tonal"
                        on_release: app.open_or_install_tailscale()
                        MDButtonIcon:
                            icon: "download"
                        MDButtonText:
                            text: "Get App"

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
                md_bg_color: [0.08, 0.16, 0.32, 0.08] if app.theme_style == "Light" else [0.12, 0.18, 0.28, 0.5]

                MDLabel:
                    text: "Client Code Snippets (Ready to paste in your app)"
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
                md_bg_color: [0.08, 0.16, 0.32, 0.06] if app.theme_style == "Light" else [0.1, 0.15, 0.22, 0.4]

                MDLabel:
                    text: "How Tailscale Remote Access works:"
                    font_style: "Title"
                    role: "small"
                    adaptive_height: True

                MDLabel:
                    text: root.guide_text
                    font_style: "Body"
                    role: "small"
                    theme_text_color: "Secondary"
                    adaptive_height: True
''')

class TailscaleBox(MDBoxLayout):
    is_ts_connected = BooleanProperty(False)
    ts_ip_text = StringProperty("Not connected")
    ts_endpoint_text = StringProperty("Endpoint: http://127.0.0.1:9292/sms/")
    ts_key_input_text = StringProperty("")
    ts_key_status_text = StringProperty("No In-App Key configured. Tap 'Help' for instructions.")
    selected_lang = StringProperty("curl")
    snippet_code = StringProperty("")
    guide_text = StringProperty(
        "• Option 1 (In-App Key): Generate a Tailscale API Access Token or Auth Key from login.tailscale.com/admin/settings/keys, paste it above and tap Connect. OpenSMS automatically syncs your Tailnet node IP!\n\n"
        "• Option 2 (Direct 100.x IP): If your device is on a Tailscale network, paste its 100.x.y.z IP address above.\n\n"
        "• Option 3 (Native App): Install the Tailscale Android app and sign in. OpenSMS detects the live VPN interface automatically without configuration!"
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.port = 9292
        self.cached_snippets = {}

    def update_tailscale_info(self, port: int = 9292, api_key: str = "YOUR_API_KEY"):
        self.port = port
        status = TailscaleService.get_status()
        self.is_ts_connected = status["connected"]

        # Restore input key if present in service
        cfg_key = status.get("configured_key", "")
        if cfg_key and not self.ts_key_input_text:
            self.ts_key_input_text = cfg_key

        if self.is_ts_connected and status["ip"]:
            self.ts_ip_text = status["ip"]
            endpoint = f"http://{status['ip']}:{port}/sms/"
            self.ts_endpoint_text = f"Remote Mesh Endpoint: {endpoint}"
            mode_str = status.get("mode", "connected").replace("_", " ").title()
            node = status.get("node_name", "gateway")
            self.ts_key_status_text = f"Connected ({mode_str}): Node '{node}' • {status['ip']}"
        else:
            local_ip = status.get("local_ip") or "127.0.0.1"
            self.ts_ip_text = f"Not detected (Local Wi-Fi / LAN: {local_ip})"
            endpoint = f"http://{local_ip}:{port}/sms/"
            self.ts_endpoint_text = f"Local LAN Endpoint: {endpoint}"
            self.ts_key_status_text = "Tailscale not connected. Enter Key or IP above to connect."

        self.cached_snippets = TailscaleService.generate_code_snippets(endpoint, api_key=api_key)
        self.snippet_code = self.cached_snippets.get(self.selected_lang, "")

    def connect_key(self):
        from kivymd.app import MDApp
        app = MDApp.get_running_app()
        raw_key = self.ids.ts_key_inp.text.strip()
        if not raw_key:
            if app and hasattr(app, "show_toast_msg"):
                app.show_toast_msg("Please enter an API Token, Auth Key, or Tailscale IP.", is_error=True)
            return

        if app and hasattr(app, "show_toast_msg"):
            app.show_toast_msg("Connecting to Tailscale...")

        def worker():
            res = TailscaleService.connect_tailscale_key(raw_key)

            def on_finish(dt):
                if res.get("success"):
                    if app and hasattr(app, "save_tailscale_config"):
                        app.save_tailscale_config(
                            key=raw_key,
                            ip=res.get("ip"),
                            node_name=res.get("node_name", "opensms-node"),
                            mode=res.get("mode", "configured")
                        )
                    port = app.req_template.get("port", 9292) if app else 9292
                    self.update_tailscale_info(port=port)
                    if app and hasattr(app, "update_network_addresses"):
                        app.update_network_addresses()
                    if app and hasattr(app, "show_toast_msg"):
                        app.show_toast_msg(res.get("message", "Tailscale connected!"))
                else:
                    err = res.get("error", "Failed to connect to Tailscale.")
                    self.ts_key_status_text = f"Connection failed: {err}"
                    if app and hasattr(app, "show_toast_msg"):
                        app.show_toast_msg(err, is_error=True)

            Clock.schedule_once(on_finish)

        Thread(target=worker, daemon=True).start()

    def disconnect_key(self):
        from kivymd.app import MDApp
        app = MDApp.get_running_app()
        TailscaleService.disconnect_key()
        self.ids.ts_key_inp.text = ""
        self.ts_key_input_text = ""
        if app and hasattr(app, "clear_tailscale_config"):
            app.clear_tailscale_config()
        port = app.req_template.get("port", 9292) if app else 9292
        self.update_tailscale_info(port=port)
        if app and hasattr(app, "update_network_addresses"):
            app.update_network_addresses()
        if app and hasattr(app, "show_toast_msg"):
            app.show_toast_msg("Tailscale key disconnected.")

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
