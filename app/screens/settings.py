from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.scrollview import MDScrollView
from kivymd.uix.button import MDButton, MDButtonIcon, MDButtonText
from kivymd.uix.textfield import MDTextField

from kivy.lang import Builder
from kivy.uix.widget import Widget
from kivy.properties import StringProperty, NumericProperty, ObjectProperty, ColorProperty, BooleanProperty
from kivy.metrics import dp, sp
from kivy.utils import platform

Builder.load_string('''

<ApiKeyTxtbox>:
    mode: "outlined"
    readonly: True

<SettingsBox>:
    orientation: "vertical"
    spacing: dp(8)

    # Top Action Buttons
    MDBoxLayout:
        orientation: "horizontal"
        adaptive_height: True
        adaptive_width: True
        spacing: dp(12)
        pos_hint: {"center_x": .5}
        padding: dp(8), dp(4)

        MDButton:
            theme_bg_color: "Custom"
            md_bg_color: [0.1, 0.65, 0.35, 1]
            on_release: app.save_settings(self)
            MDButtonIcon:
                icon: "content-save"
                color: "white"
            MDButtonText:
                text: "Save Settings"
                color: "white"

        MDButton:
            theme_bg_color: "Custom"
            md_bg_color: [0.35, 0.35, 0.35, 1]
            on_release: app.confirm_reset_settings()
            MDButtonIcon:
                icon: "restore"
                color: "white"
            MDButtonText:
                text: "Reset"
                color: "white"

    MDScrollView:
        do_scroll_x: False

        MDBoxLayout:
            id: main_scroll_bx
            orientation: "vertical"
            adaptive_height: True
            spacing: dp(10)
            padding: dp(8), dp(4), dp(8), dp(16)

            # System & App Updates Card
            MDBoxLayout:
                orientation: "vertical"
                adaptive_height: True
                radius: [dp(14)]
                padding: dp(14)
                spacing: dp(8)
                theme_bg_color: "Custom"
                md_bg_color: [0.08, 0.28, 0.52, 0.12] if app.theme_style == "Light" else [0.09, 0.2, 0.35, 0.6]

                MDLabel:
                    text: "Application & Updates"
                    font_style: "Title"
                    role: "small"
                    adaptive_height: True

                MDListItem:
                    MDListItemLeadingIcon:
                        icon: "update"
                    MDListItemHeadlineText:
                        text: "Auto-Check for Updates"
                    MDListItemSupportingText:
                        text: "Check GitHub Releases on app startup"
                    MDSwitch:
                        id: auto_update_sw
                        pos_hint: {"center_y": 0.5}
                        icon_active: "check"
                        icon_inactive: "close"
                        icon_active_color: "green"
                        track_color_active: "green"
                        on_active: app.toggle_auto_update(self, self.active)

                MDBoxLayout:
                    orientation: "horizontal"
                    adaptive_height: True
                    spacing: dp(8)

                    MDButton:
                        style: "tonal"
                        on_release: app.check_for_updates_manually()
                        MDButtonIcon:
                            icon: "cloud-search-outline"
                        MDButtonText:
                            text: "Check for Updates"

                    MDLabel:
                        id: current_version_lbl
                        text: "Current: v0.4.0"
                        font_style: "Label"
                        role: "medium"
                        theme_text_color: "Secondary"
                        adaptive_height: True
                        pos_hint: {"center_y": 0.5}

            # Telephony & Dual-SIM Card
            MDBoxLayout:
                orientation: "vertical"
                adaptive_height: True
                radius: [dp(14)]
                padding: dp(14)
                spacing: dp(8)
                theme_bg_color: "Custom"
                md_bg_color: [0.08, 0.28, 0.52, 0.08] if app.theme_style == "Light" else [0.09, 0.18, 0.28, 0.5]

                MDLabel:
                    text: "Telephony & Cellular"
                    font_style: "Title"
                    role: "small"
                    adaptive_height: True

                MDListItem:
                    MDListItemLeadingIcon:
                        icon: "sim"
                    MDListItemHeadlineText:
                        text: "Preferred SIM Slot"
                    MDListItemSupportingText:
                        id: sim_slot_supporting_txt
                        text: "Auto-detect (System default)"
                    MDButton:
                        id: sim_cycle_btn
                        style: "tonal"
                        pos_hint: {"center_y": 0.5}
                        on_release: app.cycle_sim_slot()
                        MDButtonText:
                            id: sim_cycle_btn_txt
                            text: "Auto"

            # Gateway Service Config Card
            MDBoxLayout:
                orientation: "vertical"
                adaptive_height: True
                radius: [dp(14)]
                padding: dp(14)
                spacing: dp(8)
                theme_bg_color: "Custom"
                md_bg_color: [0.08, 0.28, 0.52, 0.08] if app.theme_style == "Light" else [0.09, 0.18, 0.28, 0.5]

                MDLabel:
                    text: "Gateway & Power"
                    font_style: "Title"
                    role: "small"
                    adaptive_height: True

                # Auto Start
                MDListItem:
                    MDListItemLeadingIcon:
                        icon: "rocket-launch"
                    MDListItemHeadlineText:
                        text: "Auto Start API Server"
                    MDListItemSupportingText:
                        text: "Launch gateway automatically on app startup"
                    MDSwitch:
                        id: auto_start_sw
                        pos_hint: {"center_y": 0.5}
                        icon_active: "check"
                        icon_inactive: "close"
                        icon_active_color: "green"
                        track_color_active: "green"
                        on_active: app.toggle_auto_start(self, self.active)

                # Port Number
                MDListItem:
                    MDListItemLeadingIcon:
                        icon: "server-network"
                    MDListItemHeadlineText:
                        text: "Server Port"
                    MDListItemSupportingText:
                        text: "Port number (1025 - 65535)"
                    MDTextField:
                        id: port_no_inp
                        mode: "filled"
                        input_filter: 'int'
                        max_text_length: 5
                        size_hint_x: 0.35
                        pos_hint: {"center_y": 0.5}

                # Wake Lock
                MDListItem:
                    MDListItemLeadingIcon:
                        icon: "battery-charging"
                    MDListItemHeadlineText:
                        text: "Background WakeLock"
                    MDListItemSupportingText:
                        text: "Prevent CPU sleep when server is active"
                    MDSwitch:
                        id: wakelock_sw
                        pos_hint: {"center_y": 0.5}
                        icon_active: "check"
                        icon_inactive: "close"
                        icon_active_color: "green"
                        track_color_active: "green"
                        on_active: app.toggle_wakelock_setting(self, self.active)

                # Dark Mode
                MDListItem:
                    MDListItemLeadingIcon:
                        icon: "theme-light-dark"
                    MDListItemHeadlineText:
                        text: "Dark Theme"
                    MDListItemSupportingText:
                        text: "Switch between Light and Dark mode"
                    MDSwitch:
                        id: dark_theme_sw
                        pos_hint: {"center_y": 0.5}
                        icon_active: "check"
                        icon_inactive: "close"
                        on_active: app.toggle_theme(self, self.active)

                # API Key Management
                MDListItem:
                    MDListItemLeadingIcon:
                        icon: "key"
                    MDListItemHeadlineText:
                        text: "Generate New API Key"
                    MDListItemSupportingText:
                        text: "Generate or cycle master authentication key"
                    MDFabButton:
                        icon: "autorenew"
                        style: "small"
                        theme_bg_color: "Custom"
                        md_bg_color: "orange"
                        pos_hint: {'center_y': 0.5}
                        on_release: app.new_api_key_pop()

''')

class SettingsBox(MDBoxLayout):
    is_programmatic = BooleanProperty(False)

class ApiKeyTxtbox(MDTextField):
    pass
