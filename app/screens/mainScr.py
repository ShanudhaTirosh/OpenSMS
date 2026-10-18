from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDButton, MDButtonIcon, MDButtonText
from kivymd.uix.scrollview import MDScrollView

from kivy.lang import Builder
from kivy.uix.widget import Widget
from kivy.properties import StringProperty, NumericProperty, ObjectProperty, ColorProperty
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

            # Server Status & Address Card
            MDBoxLayout:
                orientation: 'vertical'
                adaptive_height: True
                radius: [dp(16)]
                padding: dp(16)
                spacing: dp(10)
                theme_bg_color: "Custom"
                md_bg_color: [0.08, 0.16, 0.32, 0.12] if app.theme_cls.theme_style == "Light" else [0.15, 0.22, 0.35, 0.7]

                MDBoxLayout:
                    orientation: 'horizontal'
                    adaptive_height: True
                    spacing: dp(8)

                    MDButtonIcon:
                        id: status_icon
                        icon: "cellphone-wireless"
                        pos_hint: {"center_y": 0.5}

                    MDLabel:
                        id: api_srv_lbl
                        text: "API Server is not running"
                        font_style: "Title"
                        role: "medium"
                        adaptive_height: True
                        pos_hint: {"center_y": 0.5}

                MDDivider:
                    size_hint_x: 1

                MDBoxLayout:
                    orientation: 'vertical'
                    adaptive_height: True
                    spacing: dp(4)

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

                # Quick Copy Buttons
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
                size_hint_x: 0.9
                pos_hint: {"center_x": .5}
                on_release: app.api_server_mgr(self)

            # Quick Tools Card
            MDBoxLayout:
                orientation: 'vertical'
                adaptive_height: True
                radius: [dp(16)]
                padding: dp(14)
                spacing: dp(8)
                theme_bg_color: "Custom"
                md_bg_color: [0.08, 0.16, 0.32, 0.08] if app.theme_cls.theme_style == "Light" else [0.12, 0.18, 0.28, 0.5]

                MDLabel:
                    text: "Quick Tools & Guides"
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
                        on_release: app.show_vpn_guide_dialog()
                        MDButtonIcon:
                            icon: "vpn"
                        MDButtonText:
                            text: "VPN / Remote Guide"

            Widget:
                size_hint_y: None
                height: dp(10)
''')

class AppHomeBox(MDBoxLayout):
    pass

class ButtonControl(MDButton):
    btn_icon = StringProperty("play")
    btn_txt = StringProperty("Start Server")
    btn_colour = "green"

