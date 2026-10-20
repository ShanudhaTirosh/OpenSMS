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

            # Update Available Banner (Visible when GitHub release detected)
            MDButton:
                id: update_banner_btn
                opacity: 1 if root.has_update else 0
                disabled: not root.has_update
                size_hint_y: None
                height: dp(48) if root.has_update else 0
                size_hint_x: 1
                style: "tonal"
                theme_bg_color: "Custom"
                md_bg_color: [0.15, 0.45, 0.95, 0.18] if app.theme_style == "Light" else [0.2, 0.5, 0.95, 0.35]
                on_release: app.open_update_dialog_from_banner()

                MDButtonIcon:
                    icon: "cloud-download"
                    theme_icon_color: "Custom"
                    icon_color: [0.2, 0.55, 0.98, 1]
                    pos_hint: {"center_y": 0.5}

                MDButtonText:
                    text: root.update_banner_text
                    font_style: "Label"
                    role: "medium"
                    theme_text_color: "Custom"
                    text_color: [0.15, 0.45, 0.95, 1] if app.theme_style == "Light" else [0.5, 0.8, 1, 1]
                    pos_hint: {"center_y": 0.5}

            # Gateway Hero Status Card
            MDBoxLayout:
                orientation: 'vertical'
                adaptive_height: True
                radius: [dp(20)]
                padding: dp(18)
                spacing: dp(12)
                theme_bg_color: "Custom"
                md_bg_color: [0.06, 0.18, 0.36, 0.14] if app.theme_style == "Light" else [0.12, 0.18, 0.30, 0.8]

                # Status Header Row
                MDBoxLayout:
                    orientation: 'horizontal'
                    adaptive_height: True
                    spacing: dp(10)

                    MDButtonIcon:
                        id: status_icon
                        icon: "check-circle" if root.is_online else "cellphone-wireless"
                        theme_icon_color: "Custom"
                        icon_color: [0.1, 0.75, 0.35, 1] if root.is_online else [0.85, 0.55, 0.1, 1]
                        pos_hint: {"center_y": 0.5}

                    MDBoxLayout:
                        orientation: 'vertical'
                        adaptive_height: True
                        spacing: dp(2)

                        MDLabel:
                            id: api_srv_lbl
                            text: "GATEWAY ONLINE" if root.is_online else "GATEWAY STANDBY"
                            font_style: "Title"
                            role: "medium"
                            adaptive_height: True

                        MDLabel:
                            id: api_port_sublbl
                            text: "Listening on Port 9292 • Ready" if root.is_online else "Port 9292 • Tap Start Server below"
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

                    # Tailscale Mesh Indicator Badge (Tap to view Mesh setup)
                    MDButton:
                        id: ts_badge_btn
                        style: "tonal"
                        theme_bg_color: "Custom"
                        md_bg_color: [0.1, 0.7, 0.3, 0.15] if root.has_tailscale else ([0.8, 0.2, 0.2, 0.1] if app.theme_style == "Light" else [0.35, 0.15, 0.15, 0.6])
                        on_release: app.goto_tailscale_screen()
                        adaptive_height: True
                        size_hint_x: 1

                        MDButtonIcon:
                            id: ts_chip_icon
                            icon: "shield-check" if root.has_tailscale else "shield-off"
                            theme_icon_color: "Custom"
                            icon_color: [0.1, 0.75, 0.35, 1] if root.has_tailscale else [0.85, 0.3, 0.3, 1]
                            pos_hint: {"center_y": 0.5}

                        MDButtonText:
                            id: ts_chip_lbl
                            text: "Tailscale Mesh: Connected" if root.has_tailscale else "Tailscale: Not detected (Tap to setup)"
                            font_style: "Label"
                            role: "medium"
                            theme_text_color: "Custom"
                            text_color: [0.1, 0.6, 0.25, 1] if root.has_tailscale else ([0.75, 0.2, 0.2, 1] if app.theme_style == "Light" else [0.95, 0.5, 0.5, 1])
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

            # Live Metrics Dashlet Row
            MDBoxLayout:
                orientation: 'horizontal'
                adaptive_height: True
                spacing: dp(8)

                # Sent Today Dashlet
                MDBoxLayout:
                    orientation: 'vertical'
                    adaptive_height: True
                    radius: [dp(14)]
                    padding: dp(12)
                    spacing: dp(4)
                    theme_bg_color: "Custom"
                    md_bg_color: [0.1, 0.65, 0.35, 0.12] if app.theme_style == "Light" else [0.1, 0.55, 0.3, 0.35]

                    MDLabel:
                        text: "Sent Today"
                        font_style: "Label"
                        role: "small"
                        theme_text_color: "Secondary"
                        adaptive_height: True

                    MDLabel:
                        id: metric_sent_today_lbl
                        text: root.metric_sent_today
                        font_style: "Title"
                        role: "large"
                        theme_text_color: "Custom"
                        text_color: [0.1, 0.65, 0.3, 1] if app.theme_style == "Light" else [0.25, 0.85, 0.45, 1]
                        adaptive_height: True

                # Success Rate Dashlet
                MDBoxLayout:
                    orientation: 'vertical'
                    adaptive_height: True
                    radius: [dp(14)]
                    padding: dp(12)
                    spacing: dp(4)
                    theme_bg_color: "Custom"
                    md_bg_color: [0.15, 0.45, 0.85, 0.12] if app.theme_style == "Light" else [0.15, 0.35, 0.7, 0.35]

                    MDLabel:
                        text: "Success Rate"
                        font_style: "Label"
                        role: "small"
                        theme_text_color: "Secondary"
                        adaptive_height: True

                    MDLabel:
                        id: metric_success_rate_lbl
                        text: root.metric_success_rate
                        font_style: "Title"
                        role: "large"
                        theme_text_color: "Custom"
                        text_color: [0.15, 0.45, 0.85, 1] if app.theme_style == "Light" else [0.45, 0.75, 1, 1]
                        adaptive_height: True

                # Queue Depth Dashlet
                MDBoxLayout:
                    orientation: 'vertical'
                    adaptive_height: True
                    radius: [dp(14)]
                    padding: dp(12)
                    spacing: dp(4)
                    theme_bg_color: "Custom"
                    md_bg_color: [0.85, 0.55, 0.1, 0.12] if app.theme_style == "Light" else [0.75, 0.45, 0.1, 0.35]

                    MDLabel:
                        text: "Queue Depth"
                        font_style: "Label"
                        role: "small"
                        theme_text_color: "Secondary"
                        adaptive_height: True

                    MDLabel:
                        id: metric_queue_lbl
                        text: root.metric_queue
                        font_style: "Title"
                        role: "large"
                        theme_text_color: "Custom"
                        text_color: [0.85, 0.55, 0.1, 1] if app.theme_style == "Light" else [1, 0.75, 0.3, 1]
                        adaptive_height: True

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
                md_bg_color: [0.08, 0.16, 0.32, 0.08] if app.theme_style == "Light" else [0.12, 0.18, 0.28, 0.5]

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
                            icon: "shield-account-outline"
                        MDButtonText:
                            text: "Remote Mesh"

                    MDButton:
                        style: "tonal"
                        on_release: app.check_for_updates_manually()
                        MDButtonIcon:
                            icon: "cloud-search-outline"
                        MDButtonText:
                            text: "Updates"

            Widget:
                size_hint_y: None
                height: dp(10)
''')

class AppHomeBox(MDBoxLayout):
    is_online = BooleanProperty(False)
    has_tailscale = BooleanProperty(False)
    has_update = BooleanProperty(False)
    update_banner_text = StringProperty("⚡ Update Available • Tap to Install")
    metric_sent_today = StringProperty("0")
    metric_success_rate = StringProperty("100%")
    metric_queue = StringProperty("0")

class ButtonControl(MDButton):
    btn_icon = StringProperty("play")
    btn_txt = StringProperty("Start Server")
    btn_colour = StringProperty("green")
