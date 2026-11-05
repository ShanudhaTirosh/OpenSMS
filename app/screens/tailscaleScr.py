from threading import Thread

from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.gridlayout import MDGridLayout
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

            # Built-in Tailscale (experimental): the app joins the tailnet itself, no Tailscale app needed
            MDBoxLayout:
                orientation: 'vertical'
                adaptive_height: True
                radius: [dp(16)]
                padding: dp(16)
                spacing: dp(8)
                theme_bg_color: "Custom"
                md_bg_color: [0.10, 0.45, 0.30, 0.14] if app.theme_style == "Light" else [0.10, 0.30, 0.22, 0.7]

                MDLabel:
                    text: root.emb_title
                    font_style: "Title"
                    role: "medium"
                    adaptive_height: True

                MDLabel:
                    text: root.emb_detail
                    font_style: "Body"
                    role: "small"
                    theme_text_color: "Secondary"
                    adaptive_height: True

                MDTextField:
                    id: emb_key
                    mode: "outlined"
                    input_type: "text"
                    password: True
                    size_hint_y: None
                    height: dp(56) if root.emb_can_connect else 0
                    opacity: 1 if root.emb_can_connect else 0
                    disabled: not root.emb_can_connect

                    MDTextFieldHintText:
                        text: "Auth key or API token (tskey-...)"

                MDTextField:
                    id: emb_host
                    mode: "outlined"
                    input_type: "text"
                    size_hint_y: None
                    height: dp(56) if root.emb_can_connect else 0
                    opacity: 1 if root.emb_can_connect else 0
                    disabled: not root.emb_can_connect

                    MDTextFieldHintText:
                        text: "Device name (optional, e.g. opensms-phone)"

                MDTextField:
                    id: emb_ctrl
                    mode: "outlined"
                    input_type: "url"
                    size_hint_y: None
                    height: dp(56) if root.emb_can_connect else 0
                    opacity: 1 if root.emb_can_connect else 0
                    disabled: not root.emb_can_connect

                    MDTextFieldHintText:
                        text: "Control server URL (optional, e.g. Headscale)"

                MDBoxLayout:
                    orientation: 'horizontal'
                    adaptive_height: True
                    spacing: dp(6)

                    MDButton:
                        style: "filled"
                        size_hint_x: 0.4
                        disabled: not root.emb_can_connect
                        on_release: root.emb_connect()
                        MDButtonText:
                            text: "Connect"

                    MDButton:
                        style: "outlined"
                        size_hint_x: 0.35
                        disabled: not root.emb_can_disconnect
                        on_release: app.ts_embedded_disconnect()
                        MDButtonText:
                            text: "Disconnect"

                    MDButton:
                        style: "text"
                        size_hint_x: 0.25
                        disabled: not root.emb_can_forget
                        on_release: app.ts_embedded_forget()
                        MDButtonText:
                            text: "Forget"

                MDLabel:
                    text: root.emb_peers_text
                    font_style: "Body"
                    role: "small"
                    adaptive_height: True
                    opacity: 1 if root.emb_peers_text else 0

                MDLabel:
                    text: "Experimental. The key is used once and never stored; an API token only creates a single-use key (valid 10 minutes). The device appears in your Tailscale admin console and can be removed there."
                    font_style: "Label"
                    role: "medium"
                    theme_text_color: "Secondary"
                    adaptive_height: True

            # Listening mode card (which network the API listens on)
            MDBoxLayout:
                orientation: 'vertical'
                adaptive_height: True
                radius: [dp(16)]
                padding: dp(16)
                spacing: dp(10)
                theme_bg_color: "Custom"
                md_bg_color: [0.08, 0.28, 0.52, 0.16] if app.theme_style == "Light" else [0.09, 0.22, 0.38, 0.8]

                MDLabel:
                    text: "API listening mode"
                    font_style: "Title"
                    role: "medium"
                    adaptive_height: True

                MDLabel:
                    text: root.bind_help_text
                    font_style: "Body"
                    role: "small"
                    theme_text_color: "Secondary"
                    adaptive_height: True

                MDBoxLayout:
                    orientation: 'vertical'
                    adaptive_height: True
                    spacing: dp(8)

                    MDBoxLayout:
                        orientation: 'horizontal'
                        adaptive_height: True
                        spacing: dp(8)

                        MDButton:
                            style: "filled" if root.bind_mode == "all" else "outlined"
                            size_hint_x: 0.5
                            on_release: app.set_bind_mode("all")
                            MDButtonText:
                                text: "All networks"

                        MDButton:
                            style: "filled" if root.bind_mode == "tailscale" else "outlined"
                            size_hint_x: 0.5
                            on_release: app.set_bind_mode("tailscale")
                            MDButtonText:
                                text: "Tailscale only"

                    MDButton:
                        style: "filled" if root.bind_mode == "localhost" else "outlined"
                        size_hint_x: 1
                        on_release: app.set_bind_mode("localhost")
                        MDButtonText:
                            text: "This phone only (Localhost)"

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
                        text: root.state_title
                        font_style: "Title"
                        role: "medium"
                        adaptive_height: True
                        pos_hint: {"center_y": 0.5}

                MDDivider:
                    size_hint_x: 1

                MDLabel:
                    text: root.state_detail
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
                        text: "Tailscale address:" if root.is_ts_connected else "Network status:"
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

                # Action Buttons (wrap on narrow phones instead of running off-screen)
                MDGridLayout:
                    cols: 2
                    adaptive_height: True
                    spacing: dp(8)

                    MDButton:
                        style: "filled"
                        on_release: root.copy_mesh_endpoint()
                        MDButtonIcon:
                            icon: "content-copy"
                        MDButtonText:
                            text: "Copy URL"

                    MDButton:
                        style: "tonal"
                        on_release: app.open_or_install_tailscale()
                        MDButtonIcon:
                            icon: "download"
                        MDButtonText:
                            text: "Tailscale app"

                    MDButton:
                        style: "outlined"
                        on_release: root.refresh_status()
                        MDButtonIcon:
                            icon: "refresh"
                        MDButtonText:
                            text: "Refresh"

            # Cross-Network Code Generator Card
            # Diagnostics card
            MDBoxLayout:
                orientation: 'vertical'
                adaptive_height: True
                radius: [dp(16)]
                padding: dp(16)
                spacing: dp(6)
                theme_bg_color: "Custom"
                md_bg_color: [0.08, 0.16, 0.32, 0.08] if app.theme_style == "Light" else [0.12, 0.18, 0.28, 0.5]

                MDLabel:
                    text: "Diagnostics"
                    font_style: "Title"
                    role: "small"
                    adaptive_height: True

                MDLabel:
                    text: root.diagnostics_text
                    font_style: "Body"
                    role: "small"
                    theme_text_color: "Secondary"
                    adaptive_height: True

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
                MDGridLayout:
                    cols: 3
                    adaptive_height: True
                    spacing: dp(6)

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
                        id: btn_lang_php
                        style: "filled" if root.selected_lang == "php" else "outlined"
                        on_release: root.select_lang("php")
                        MDButtonText:
                            text: "PHP"

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
    state_title = StringProperty("Tailscale: checking...")
    state_detail = StringProperty("")
    diagnostics_text = StringProperty("")
    emb_title = StringProperty("Built-in Tailscale")
    emb_detail = StringProperty("")
    emb_peers_text = StringProperty("")
    emb_endpoint = StringProperty("")
    emb_ip = StringProperty("")
    emb_available = BooleanProperty(False)
    emb_connected = BooleanProperty(False)
    emb_can_connect = BooleanProperty(False)
    emb_can_disconnect = BooleanProperty(False)
    emb_can_forget = BooleanProperty(False)
    bind_mode = StringProperty("all")
    bind_help_text = StringProperty("")
    selected_lang = StringProperty("curl")
    snippet_code = StringProperty("")
    guide_text = StringProperty(
        "OpenSMS does not connect to Tailscale by itself and never asks for a Tailscale key.\n\n"
        "1. Install the Tailscale app, sign in and connect.\n"
        "2. OpenSMS shows the Tailscale address (100.x.y.z) it observes on this phone.\n"
        "3. Call the gateway from your other devices at http://<that address>:<port>/sms/.\n"
        "4. Choose 'Tailscale only' to keep the API off Wi-Fi/LAN.\n\n"
        "Android allows one VPN at a time: another VPN will switch Tailscale off. "
        "The state shown here is what this phone currently reports, not a guarantee that a remote device can reach it."
    )

    _STATE_TEXT = {
        "connected": ("Tailscale: connected",
                      "This phone has a Tailscale address. Other devices on your tailnet can reach the gateway "
                      "at the address below while the server is running."),
        "other_vpn": ("Another VPN is active",
                      "A VPN is running but it has no Tailscale address. Open the Tailscale app and connect "
                      "(Android allows one VPN at a time)."),
        "disconnected": ("Tailscale: not connected",
                         "No Tailscale address found on this phone. Open the Tailscale app, sign in and connect."),
        "unknown": ("Tailscale: status unavailable",
                    "The network state could not be read on this device."),
    }
    _BIND_HELP = {
        "all": "The API listens on every network (Wi-Fi, mobile data, Tailscale). Simple, but the API token "
               "is sent unencrypted on Wi-Fi/LAN.",
        "tailscale": "The API listens only on the Tailscale address. It will not start unless Tailscale is "
                     "connected, and it never falls back to other networks.",
        "localhost": "The API is reachable from this phone only.",
    }
    _LEVEL_MARK = {"ok": "[OK]", "info": "[i]", "warn": "[!]", "error": "[X]"}

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.port = 9292
        self.cached_snippets = {}
        Clock.schedule_interval(self._emb_poll, 2.0)

    # ---- built-in Tailscale card
    def _emb_poll(self, dt):
        """The engine runs in the background service: refresh the card while this screen is showing."""
        from kivymd.app import MDApp
        app = MDApp.get_running_app()
        try:
            if app and app.root.ids.screen_manager.current == "Mesh":
                before = self.emb_connected
                self.emb_refresh()
                if before != self.emb_connected:       # the status card below must follow the built-in node
                    self.update_tailscale_info(port=self.port)
        except Exception:
            pass

    def emb_refresh(self):
        from kivymd.app import MDApp
        from services.tsUiText import describe_embedded
        app = MDApp.get_running_app()
        status = app.ts_embedded_status() if app and hasattr(app, "ts_embedded_status") else {}
        info = describe_embedded(status, self.port)
        self.emb_title, self.emb_detail, self.emb_peers_text = info["title"], info["detail"], info["peers_text"]
        self.emb_endpoint = info["endpoint"]
        self.emb_ip = info["ip"]
        self.emb_available, self.emb_connected = info["available"], info["connected"]
        self.emb_can_connect, self.emb_can_disconnect, self.emb_can_forget = info["can_connect"], info["can_disconnect"], info["can_forget"]

    def emb_connect(self):
        from kivymd.app import MDApp
        app = MDApp.get_running_app()
        ok = app.ts_embedded_connect(self.ids.emb_key.text, self.ids.emb_host.text, self.ids.emb_ctrl.text)
        if ok:
            self.ids.emb_key.text = ""          # the key lives nowhere in the UI once it has been handed over
        self.emb_refresh()
        return ok

    def update_tailscale_info(self, port: int = 9292):
        """Refresh from what the device actually reports. The API key is never part of the snippets."""
        from kivymd.app import MDApp
        app = MDApp.get_running_app()
        self.port = port
        mode = "all"
        if app and hasattr(app, "config_template"):
            mode = app.config_template.get("bind_mode", "all")
        self.bind_mode = mode
        self.bind_help_text = self._BIND_HELP.get(mode, "")

        status = TailscaleService.get_status(port=port, bind_mode=mode)
        self.is_ts_connected = status["connected"]
        title, detail = self._STATE_TEXT.get(status["state"], self._STATE_TEXT["unknown"])
        self.state_title, self.state_detail = title, detail

        endpoint, net_type = TailscaleService.get_preferred_endpoint(port, mode)
        if status["connected"] and status["ip"]:
            self.ts_ip_text = status["ip"]
        else:
            self.ts_ip_text = f"Not detected (local address: {status.get('local_ip') or '127.0.0.1'})"
        self.ts_endpoint_text = f"{net_type} endpoint: {endpoint}"
        self.diagnostics_text = "\n".join(
            f"{self._LEVEL_MARK.get(d['level'], '[i]')} {d['text']}" for d in status["diagnostics"])

        self.emb_refresh()
        if self.emb_connected and self.emb_endpoint:
            endpoint, net_type = self.emb_endpoint, "Built-in Tailscale"
            self.ts_endpoint_text = f"{net_type} endpoint: {endpoint}"
            self.is_ts_connected = True
            self.ts_ip_text = self.emb_ip or "connected"
            self.state_title = "Tailscale: connected (built-in)"
            self.state_detail = ("This phone is on your tailnet through the built-in Tailscale. Other tailnet devices "
                                 "can reach the gateway at the address below while the server is running.")
        self.cached_snippets = TailscaleService.generate_code_snippets(endpoint)
        self.snippet_code = self.cached_snippets.get(self.selected_lang, "")

    def select_lang(self, lang: str):
        self.selected_lang = lang
        self.snippet_code = self.cached_snippets.get(lang, "")

    def copy_mesh_endpoint(self):
        from kivymd.app import MDApp
        app = MDApp.get_running_app()
        mode = app.config_template.get("bind_mode", "all") if app else "all"
        url, _ = TailscaleService.get_preferred_endpoint(self.port, mode)
        if self.emb_connected and self.emb_endpoint:
            url = self.emb_endpoint
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
        """Re-read the network state off the UI thread (includes a short TCP self-probe)."""
        from kivymd.app import MDApp
        app = MDApp.get_running_app()
        port = app.req_template.get("port", 9292) if app else 9292
        mode = app.config_template.get("bind_mode", "all") if app else "all"

        def worker():
            status = TailscaleService.get_status(port=port, bind_mode=mode, probe=True)
            Clock.schedule_once(lambda dt: self._apply_probe(status, port), 0)
        Thread(target=worker, daemon=True).start()

    def _apply_probe(self, status, port):
        self.update_tailscale_info(port=port)
        self.diagnostics_text = "\n".join(
            f"{self._LEVEL_MARK.get(d['level'], '[i]')} {d['text']}" for d in status["diagnostics"])
