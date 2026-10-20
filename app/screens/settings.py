from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.scrollview import MDScrollView
from kivymd.uix.gridlayout import MDGridLayout
from kivymd.uix.button import MDButton, MDButtonIcon, MDButtonText
from kivymd.uix.textfield import MDTextField, MDTextFieldTrailingIcon

from kivy.lang import Builder
from kivy.uix.widget import Widget
from kivy.properties import StringProperty, NumericProperty, ObjectProperty, ColorProperty
from kivy.metrics import dp, sp
from kivy.utils import platform

Builder.load_string('''

<ApiKeyTxtbox>:
    mode: "outlined"
    readonly: True

<SettingsBox>:
    orientation: "vertical"
    spacing: dp(8)

    MDBoxLayout:
        orientation: "horizontal"
        adaptive_height: True
        adaptive_width: True
        spacing: dp(12)
        pos_hint: {"center_x": .5}
        padding: dp(8), dp(4)

        MDButton:
            theme_bg_color: "Custom"
            md_bg_color: "green"
            on_release: app.save_settings(self)
            MDButtonIcon:
                icon: "content-save"
                color: "white"
            MDButtonText:
                text: "Save Settings"
                color: "white"

        MDButton:
            theme_bg_color: "Custom"
            md_bg_color: [0.3, 0.3, 0.3, 1]
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
            padding: dp(8), dp(4)

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
                    text: "Requires restart (1025 - 65535)"
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
                    text: "Switch between Light and Dark theme"
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
                    text: "Invalidates the previous key immediately"
                MDFabButton:
                    icon: "autorenew"
                    style: "small"
                    theme_bg_color: "Custom"
                    md_bg_color: "orange"
                    pos_hint: {'center_y': 0.5}
                    on_release: app.new_api_key_pop()

''')

class SettingsBox(MDBoxLayout):
    pass

class ApiKeyTxtbox(MDTextField):
    pass

