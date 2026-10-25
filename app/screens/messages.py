"""Messages screen: searchable, filterable, paginated history with a detail view."""
from threading import Thread

from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDButton, MDButtonText, MDButtonIcon
from kivymd.uix.dialog import MDDialogButtonContainer
from kivymd.uix.label import MDLabel
from kivymd.uix.dialog import MDDialogContentContainer
from kivymd.uix.textfield import MDTextField, MDTextFieldHintText

from kivy.clock import Clock
from kivy.core.clipboard import Clipboard
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import StringProperty, BooleanProperty, ListProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.widget import Widget

from services.dbMgr import DatabaseManager
from services.outbox import write_outbox, validate_outgoing
from services.smsApi import calculate_sms_segments
from services import uiFormat as U
from screens.components import StatusChip, EmptyState, SkeletonRow, card_color  # noqa: F401 (registers KV rules)

Builder.load_string('''
<MessageRow>:
    orientation: "horizontal"
    size_hint_y: None
    height: dp(84)
    padding: dp(12), dp(8)
    spacing: dp(10)
    radius: [dp(12)]
    theme_bg_color: "Custom"
    md_bg_color: root.bg_color

    MDBoxLayout:
        orientation: "vertical"
        spacing: dp(2)

        MDLabel:
            text: root.recipient
            font_style: "Title"
            role: "small"
            adaptive_height: True
            shorten: True
            shorten_from: "right"

        MDLabel:
            text: root.preview
            font_style: "Body"
            role: "small"
            theme_text_color: "Secondary"
            adaptive_height: True
            max_lines: 1
            shorten: True
            shorten_from: "right"

        MDLabel:
            text: root.time_text
            font_style: "Label"
            role: "small"
            theme_text_color: "Secondary"
            adaptive_height: True

    StatusChip:
        id: chip
        text: root.status_label
        icon: root.status_icon
        chip_color: root.status_color

<MessagesBox>:
    orientation: "vertical"
    spacing: dp(8)

    MDBoxLayout:
        orientation: "horizontal"
        adaptive_height: True
        spacing: dp(6)
        padding: dp(4), dp(4), dp(4), 0

        MDTextField:
            id: search_inp
            mode: "outlined"
            size_hint_y: None
            height: dp(56)
            on_text: root.on_search_text(self.text)

            MDTextFieldLeadingIcon:
                icon: "magnify"

            MDTextFieldHintText:
                text: "Search number or text"

        MDIconButton:
            icon: "refresh"
            pos_hint: {"center_y": 0.5}
            on_release: root.reload()

        MDIconButton:
            icon: "message-plus-outline"
            style: "tonal"
            pos_hint: {"center_y": 0.5}
            on_release: root.show_compose_dialog()

    MDScrollView:
        do_scroll_y: False
        size_hint_y: None
        height: dp(48)

        MDBoxLayout:
            id: chip_box
            orientation: "horizontal"
            adaptive_width: True
            spacing: dp(6)
            padding: dp(4), dp(4)

    MDLabel:
        text: root.range_text
        font_style: "Label"
        role: "medium"
        theme_text_color: "Secondary"
        adaptive_height: True
        padding: dp(8), 0

    MDScrollView:
        do_scroll_x: False

        MDBoxLayout:
            id: list_box
            orientation: "vertical"
            adaptive_height: True
            spacing: dp(8)
            padding: dp(4), dp(4), dp(4), dp(16)
''')


class MessageRow(ButtonBehavior, MDBoxLayout):
    recipient = StringProperty("")
    preview = StringProperty("")
    time_text = StringProperty("")
    status_label = StringProperty("")
    status_icon = StringProperty("help-circle-outline")
    status_color = ListProperty([0.5, 0.5, 0.5, 1])
    bg_color = ListProperty([0.1, 0.1, 0.1, 0.1])

    def __init__(self, msg: dict, on_open, theme_style: str = "Light", **kw):
        super().__init__(**kw)
        info = U.status_info(msg.get("status"))
        self.msg = msg
        self._on_open = on_open
        self.recipient = msg.get("recipient", "")
        self.preview = U.shorten(msg.get("text", ""), 80)
        self.time_text = U.format_time(msg.get("created_at"))
        self.status_label, self.status_icon, self.status_color = info["label"], info["icon"], list(info["color"])
        self.bg_color = card_color(theme_style)

    def on_release(self):
        self._on_open(self.msg)


class MessagesBox(MDBoxLayout):
    status_filter = StringProperty("all")
    range_text = StringProperty("")
    loading = BooleanProperty(False)

    REFRESH_SECONDS = 5

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.search_text = ""
        self.offset = 0
        self.rows = []
        self.has_more = False
        self._debounce = None
        self._auto = None
        self._generation = 0
        self._chips = {}
        Clock.schedule_once(lambda dt: self._build_chips(), 0)

    # ---------------------------------------------------------------- helpers
    def _app(self):
        return MDApp.get_running_app()

    def _db(self):
        return DatabaseManager.get_instance(self._app().config_dir)

    def _theme(self):
        return getattr(self._app(), "theme_style", "Light")

    def _build_chips(self):
        box = self.ids.chip_box
        if self._chips:
            return
        for f in U.FILTERS:
            label = "All" if f == "all" else U.status_info(f)["label"]
            btn = MDButton(MDButtonText(text=label), style="filled" if f == self.status_filter else "outlined")
            btn.bind(on_release=lambda _b, flt=f: self.set_filter(flt))
            self._chips[f] = btn
            box.add_widget(btn)

    # ---------------------------------------------------------------- actions
    def set_filter(self, flt: str):
        self.status_filter = flt
        for key, btn in self._chips.items():
            btn.style = "filled" if key == flt else "outlined"
        self.reload()

    def on_search_text(self, text: str):
        if text == self.search_text:
            return
        self.search_text = text
        if self._debounce:
            self._debounce.cancel()
        self._debounce = Clock.schedule_once(lambda dt: self.reload(), 0.4)

    def reload(self, quiet: bool = False):
        self.offset = 0
        self._load(reset=True, quiet=quiet)

    def load_more(self):
        self._load(reset=False)

    def start_auto_refresh(self):
        self.stop_auto_refresh()
        self.reload()
        self._auto = Clock.schedule_interval(self._tick, self.REFRESH_SECONDS)

    def stop_auto_refresh(self):
        if self._auto:
            self._auto.cancel()
            self._auto = None

    def _tick(self, dt):
        # Only refresh when the user is looking at the first page, so "load more" is never disturbed.
        if len(self.rows) <= U.PAGE_SIZE:
            self.reload(quiet=True)

    # ---------------------------------------------------------------- loading
    def _load(self, reset: bool, quiet: bool = False):
        self._generation += 1
        gen = self._generation
        offset = 0 if reset else len(self.rows)
        if reset and not quiet:
            self._show_skeleton()
        self.loading = True
        status, search = self.status_filter, self.search_text

        def worker():
            try:
                data = U.fetch_messages(self._db(), status=status, search=search, offset=offset)
                err = None
            except Exception as e:  # shown as an error state with a retry action
                data, err = None, str(e)
            Clock.schedule_once(lambda dt: self._apply(gen, reset, data, err), 0)

        Thread(target=worker, daemon=True).start()

    def _apply(self, gen, reset, data, err):
        if gen != self._generation:   # a newer request superseded this one
            return
        self.loading = False
        box = self.ids.list_box
        box.clear_widgets()
        if err:
            self.range_text = ""
            es = EmptyState(icon="alert-circle-outline", title="Could not load messages", subtitle=err)
            retry = MDButton(MDButtonText(text="Retry"), style="tonal", pos_hint={"center_x": 0.5})
            retry.bind(on_release=lambda *_: self.reload())
            box.add_widget(es)
            box.add_widget(retry)
            return
        self.rows = (self.rows if not reset else []) + data["rows"]
        self.has_more = data["has_more"]
        self.range_text = data["range_text"]
        if not self.rows:
            searching = bool(self.search_text or self.status_filter != "all")
            box.add_widget(EmptyState(
                icon="magnify" if searching else "message-text-outline",
                title="No matching messages" if searching else "No messages yet",
                subtitle="Try a different search or filter." if searching
                         else "Messages sent through the API will appear here."))
            return
        theme = self._theme()
        for msg in self.rows:
            box.add_widget(MessageRow(msg, self.open_detail, theme_style=theme))
        if self.has_more:
            more = MDButton(MDButtonText(text="Load more"), style="tonal", pos_hint={"center_x": 0.5})
            more.bind(on_release=lambda *_: self.load_more())
            box.add_widget(more)

    def _show_skeleton(self):
        box = self.ids.list_box
        box.clear_widgets()
        for _ in range(4):
            box.add_widget(SkeletonRow())

    # ---------------------------------------------------------------- compose
    def show_compose_dialog(self, number: str = "", text: str = ""):
        """Step 1: write the message (inline validation, live segment count). Step 2: confirm, then queue."""
        app = self._app()
        if hasattr(app, "require_gateway_service") and not app.require_gateway_service():
            return
        number_field = MDTextField(MDTextFieldHintText(text="Phone number (e.g. +94771234567)"), mode="outlined",
                                   text=number, size_hint_y=None, height=dp(56))
        text_field = MDTextField(MDTextFieldHintText(text="Message"), mode="outlined", text=text,
                                 multiline=True, size_hint_y=None, height=dp(112))
        counter = MDLabel(text="", theme_text_color="Secondary", font_style="Label", role="medium", adaptive_height=True)
        error = MDLabel(text="", theme_text_color="Custom", text_color=(0.85, 0.25, 0.25, 1),
                        font_style="Label", role="medium", adaptive_height=True)

        def refresh_counter(*_):
            c = calculate_sms_segments(text_field.text)
            counter.text = f"{c['length']} characters \u2022 {c['segments']} segment(s) \u2022 {c['encoding']}"
            error.text = ""
        text_field.bind(text=refresh_counter)
        number_field.bind(text=lambda *_: setattr(error, "text", ""))
        refresh_counter()

        def review(*_):
            clean_number, clean_text, err = validate_outgoing(number_field.text, text_field.text)
            if err:
                error.text = err           # the dialog and what was typed stay
                return
            app.txt_dialog_closer()
            self._show_confirm(clean_number, clean_text)

        content = MDDialogContentContainer(orientation="vertical", spacing=dp(10))
        for w in (number_field, text_field, counter, error):
            content.add_widget(w)
        buttons = MDDialogButtonContainer(
            Widget(),
            MDButton(MDButtonText(text="Cancel"), style="text", on_release=app.txt_dialog_closer),
            MDButton(MDButtonText(text="Review", theme_text_color="Custom", text_color="green"), style="text", on_release=review),
            spacing="8dp",
        )
        app.show_text_dialog("New message", "Sent through the gateway queue, so it appears here with its real status.", content, buttons)

    def _show_confirm(self, number: str, text: str):
        app = self._app()
        sim_slot = app.config_template.get("sim_slot", -1) if hasattr(app, "config_template") else -1
        info = calculate_sms_segments(text)
        sent = {"done": False}
        send_btn = MDButton(MDButtonText(text="Send", theme_text_color="Custom", text_color="green"), style="text")

        def do_send(*_):
            if sent["done"]:               # prevent duplicate submissions
                return
            sent["done"] = True
            send_btn.disabled = True
            try:
                write_outbox(app.config_dir, number, text, sim_slot)
            except (ValueError, OSError) as e:
                sent["done"] = False
                send_btn.disabled = False
                app.show_toast_msg(f"Could not queue the message: {e}", is_error=True)
                return
            app.txt_dialog_closer()
            app.show_toast_msg("Message queued")
            Clock.schedule_once(lambda dt: self.reload(), 1.2)

        send_btn.bind(on_release=do_send)
        buttons = MDDialogButtonContainer(
            Widget(),
            MDButton(MDButtonText(text="Edit"), style="text",
                     on_release=lambda *_: (app.txt_dialog_closer(), self.show_compose_dialog(number, text))),
            send_btn,
            spacing="8dp",
        )
        sim_txt = "default SIM" if sim_slot in (None, -1) else f"SIM slot {sim_slot + 1}"
        app.show_text_dialog(
            "Send this message?",
            f"To: {number}\nVia: {sim_txt}\n{info['segments']} segment(s), {info['encoding']}\n\n{U.shorten(text, 300)}\n\n"
            "SMS may be billed by your carrier.",
            None, buttons)

    # ---------------------------------------------------------------- detail
    def open_detail(self, msg: dict):
        app = self._app()
        try:
            parts = self._db().get_parts(msg["id"])
            fresh = self._db().get_message(msg["id"]) or msg
        except Exception:
            parts, fresh = [], msg
        info = U.status_info(fresh.get("status"))
        text = "\n".join(f"{k}: {v}" for k, v in U.describe_message(fresh, parts))
        buttons = MDDialogButtonContainer(
            Widget(),
            MDButton(MDButtonText(text="Copy ID"), style="text",
                     on_release=lambda *_: (Clipboard.copy(fresh["id"]), app.show_toast_msg("Message ID copied"))),
            MDButton(MDButtonText(text="Close"), style="text", on_release=app.txt_dialog_closer),
            spacing="8dp",
        )
        app.show_text_dialog(f"{info['label']} message", text, None, buttons)
