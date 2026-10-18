from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDButton, MDButtonIcon, MDButtonText
from kivymd.uix.scrollview import MDScrollView

from kivy.lang import Builder
from kivy.uix.widget import Widget
from kivy.properties import StringProperty, NumericProperty, ObjectProperty, ColorProperty, BooleanProperty
from kivy.metrics import dp, sp
from kivy.utils import platform

Builder.load_string('''
<ButtonControl>
    pos_hint: {"center_x": .5}
    theme_bg_color: "Custom"
    md_bg_color: self.btn_colour
    MDButtonIcon:
        icon: root.btn_icon
        color: "white"
    MDButtonText:
        text: root.btn_txt
        color: "white"

<AppHomeBox>:
    orientation: 'vertical'
    spacing: dp(8)

    MDScrollView:
        do_scroll_x: False
        size_hint_y: 1

        MDBoxLayout:
            orientation: 'vertical'
            adaptive_height: True
            spacing: dp(14)
            padding: dp(8), dp(4), dp(8), dp(16)

            # Gateway Hero Status Card
            MDBoxLayout:
                orientation: 'vertical'
                adaptive_height: True
                radius: [dp(20)]
                padding: dp(18)
                spacing: dp(12)
                theme_bg_color: "Custom"
                md_bg_color: [0.06, 0.18, 0.36, 0.14] if app.theme_cls.theme_style == "Light" else [0.12, 0.18, 0.30, 0.8]

                # Status Header Row
                MDBoxLayout:
                    orientation: 'horizontal'
                    adaptive_height: True
                    spacing: dp(10)

                    MDButtonIcon:
                        id: status_icon
                        icon: "cellphone-wireless"
                        theme_icon_color: "Custom"
                        icon_color: [0.1, 0.75, 0.35, 1] if root.is_online else [0.85, 0.55, 0.1, 1]
                        pos_hint: {"center_y": 0.5}

                    MDBoxLayout:
                        orientation: 'vertical'
                        adaptive_height: True
                        spacing: dp(2)

                        MDLabel:
                            id: api_srv_lbl
                            text: "GATEWAY STANDBY"
                            font_style: "Title"
                            role: "medium"
                            adaptive_height: True

                        MDLabel:
                            id: api_port_sublbl
                            text: "Port 9292 • Tap Start Server below"
                            font_style: "Label"
                            role: "medium"
                            theme_text_color: "Secondary"
                            adaptive_height: True

                MDDivider:
                    size_hint_x: 1

                # Network Addresses Section
                MDBoxLayout:
                    orientation: 'vertical'
                    adaptive_height: True
                    spacing: dp(6)

                    # Tailscale Mesh Indicator Badge
                    MDBoxLayout:
                        id: ts_badge_box
                        orientation: 'horizontal'
                        adaptive_height: True
                        spacing: dp(6)

                        MDButtonIcon:
                            id: ts_chip_icon
                            icon: "shield-check"
                            theme_icon_color: "Custom"
                            icon_color: [0.1, 0.75, 0.35, 1] if root.has_tailscale else [0.7, 0.7, 0.7, 1]
                            pos_hint: {"center_y": 0.5}

                        MDLabel:
                            id: ts_chip_lbl
                            text: "Tailscale Mesh: Connected" if root.has_tailscale else "Tailscale: Not detected (Tap Mesh to setup)"
                            font_style: "Label"
                            role: "medium"
                            theme_text_color: "Primary"
                            adaptive_height: True
                            pos_hint: {"center_y": 0.5}

                    MDLabel:
                        text: "Active Network Addresses (Wi-Fi / VPN / LAN):"
                        font_style: "Label"
                        role: "small"
                        theme_text_color: "Secondary"
                        adaptive_height: True

                    MDLabel:
                        id: ip_addresses_lbl
                        text: "Discovering network addresses..."
                        font_style: "Body"
                        role: "medium"
                        adaptive_height: True

                    MDLabel:
                        id: api_endpoint_lbl
                        text: "Endpoint: http://127.0.0.1:9292/sms/"
                        font_style: "Label"
                        role: "medium"
                        theme_text_color: "Primary"
                        adaptive_height: True

                # Quick Copy Action Row
                MDBoxLayout:
                    orientation: 'horizontal'
                    adaptive_height: True
                    spacing: dp(8)
                    pos_hint: {"center_x": 0.5}

                    MDButton:
                        style: "outlined"
                        on_release: app.copy_endpoint_url()
                        MDButtonIcon:
                            icon: "content-copy"
                        MDButtonText:
                            text: "Copy URL"

                    MDButton:
                        style: "outlined"
                        on_release: app.copy_curl_example()
                        MDButtonIcon:
                            icon: "code-tags"
                        MDButtonText:
                            text: "Copy cURL"

            # Primary Action Button (Start / Stop)
            ButtonControl:
                id: api_srv_btn
                style: "filled"
                size_hint_x: 0.95
                pos_hint: {"center_x": .5}
                on_release: app.api_server_mgr(self)

            # Quick Operations & Tools Card
            MDBoxLayout:
                orientation: 'vertical'
                adaptive_height: True
                radius: [dp(16)]
                padding: dp(14)
                spacing: dp(10)
                theme_bg_color: "Custom"
                md_bg_color: [0.08, 0.16, 0.32, 0.08] if app.theme_cls.theme_style == "Light" else [0.12, 0.18, 0.28, 0.5]

                MDLabel:
                    text: "Quick Operations"
                    font_style: "Title"
                    role: "small"
                    adaptive_height: True

                MDBoxLayout:
                    orientation: 'horizontal'
                    adaptive_height: True
                    spacing: dp(8)
                    pos_hint: {"center_x": 0.5}

                    MDButton:
                        style: "tonal"
                        on_release: app.show_test_sms_dialog()
                        MDButtonIcon:
                            icon: "send"
                        MDButtonText:
                            text: "Test SMS"

                    MDButton:
                        style: "tonal"
                        on_release: app.goto_tailscale_screen()
                        MDButtonIcon:
                            icon: "vpn"
                        MDButtonText:
                            text: "Remote Mesh"

            Widget:
                size_hint_y: None
                height: dp(10)
''')

class AppHomeBox(MDBoxLayout):
    is_online = BooleanProperty(False)
    has_tailscale = BooleanProperty(False)

class ButtonControl(MDButton):
    btn_icon = StringProperty("play")
    btn_txt = StringProperty("Start Server")
    btn_colour = "green"


