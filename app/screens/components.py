"""Small reusable widgets shared by the Messages and API screens."""
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDButton, MDButtonText, MDButtonIcon

from kivy.lang import Builder
from kivy.properties import StringProperty, ColorProperty, BooleanProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.widget import Widget

Builder.load_string('''
<StatusChip>:
    orientation: "horizontal"
    adaptive_size: True
    padding: dp(8), dp(4)
    spacing: dp(4)
    radius: [dp(12)]
    theme_bg_color: "Custom"
    md_bg_color: [root.chip_color[0], root.chip_color[1], root.chip_color[2], 0.18]
    pos_hint: {"center_y": 0.5}

    MDIcon:
        icon: root.icon
        theme_icon_color: "Custom"
        icon_color: root.chip_color
        font_size: dp(16)
        size_hint: None, None
        size: dp(16), dp(16)
        pos_hint: {"center_y": 0.5}

    MDLabel:
        text: root.text
        theme_text_color: "Custom"
        text_color: root.chip_color
        font_style: "Label"
        role: "medium"
        adaptive_size: True
        pos_hint: {"center_y": 0.5}

<EmptyState>:
    orientation: "vertical"
    adaptive_height: True
    padding: dp(24), dp(40), dp(24), dp(24)
    spacing: dp(8)

    MDIcon:
        icon: root.icon
        pos_hint: {"center_x": 0.5}
        theme_icon_color: "Secondary"
        font_size: sp(48)

    MDLabel:
        text: root.title
        halign: "center"
        font_style: "Title"
        role: "medium"
        adaptive_height: True

    MDLabel:
        text: root.subtitle
        halign: "center"
        font_style: "Body"
        role: "medium"
        theme_text_color: "Secondary"
        adaptive_height: True

<SkeletonRow>:
    size_hint_y: None
    height: dp(76)
    radius: [dp(12)]
    theme_bg_color: "Custom"
    md_bg_color: [0.5, 0.5, 0.55, 0.14]
''')


class StatusChip(MDBoxLayout):
    text = StringProperty("")
    icon = StringProperty("help-circle-outline")
    chip_color = ColorProperty([0.5, 0.5, 0.5, 1])


class EmptyState(MDBoxLayout):
    icon = StringProperty("inbox-outline")
    title = StringProperty("")
    subtitle = StringProperty("")


class SkeletonRow(MDBoxLayout):
    """Placeholder shown while the first page of a list loads."""


def card_color(theme_style: str):
    return [0.08, 0.16, 0.32, 0.08] if theme_style == "Light" else [0.12, 0.18, 0.28, 0.5]
