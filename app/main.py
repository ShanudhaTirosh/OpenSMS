import os
os.environ['KIVY_GL_BACKEND'] = 'sdl2'
from kivy.config import Config
Config.set("graphics", "multisamples", "0")
import sys
import json
import socket
from threading import Thread

from kivy.uix.widget import Widget
from kivy.core.clipboard import Clipboard
from kivy.lang import Builder
from kivy.core.window import Window
from kivy.utils import platform
from kivy.metrics import dp, sp
from kivy.clock import Clock
from kivy.properties import StringProperty, NumericProperty, ObjectProperty, BooleanProperty, ColorProperty

# debug
try:
    from kivy.graphics.opengl import glGetString, GL_VENDOR, GL_RENDERER, GL_VERSION
    print("GL_VENDOR:", glGetString(GL_VENDOR))
    print("GL_RENDERER:", glGetString(GL_RENDERER))
    print("GL_VERSION:", glGetString(GL_VERSION))
except Exception as e:
    print(f"OpenGL info query skipped: {e}")

from kivymd.uix.widget import MDWidget
from kivymd.app import MDApp
from kivymd.uix.navigationbar import MDNavigationBar, MDNavigationItem
from kivymd.uix.screen import MDScreen
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDButton, MDButtonIcon, MDButtonText
from kivymd.uix.textfield import MDTextField
from kivymd.uix.dialog import MDDialog, MDDialogHeadlineText, MDDialogSupportingText, MDDialogButtonContainer, MDDialogContentContainer

# import screens (else pyinstaller may ignore it)
from screens.mainScr import ButtonControl, AppHomeBox
from screens.settings import SettingsBox, ApiKeyTxtbox
from screens.tailscaleScr import TailscaleBox
from services.smsApi import send_sms, calculate_sms_segments, sanitize_phone_number

# import services
from services.postApi import get_api_keys, set_config_path, generate_new_api_key
from services.pathMgr import atomic_write_json, get_device_ip_addresses, get_network_interfaces_info
from services.tailscaleSvc import TailscaleService

# IMPORTANT: Set this property for keyboard behavior
Window.softinput_mode = "below_target"

# import platform specific modules
if platform == "android":
    from jnius import autoclass, cast
    from android.permissions import check_permission, request_permissions, Permission
    from screens.kivymd_patch import disable_gpu_ripple, disable_hover
    from services.android_env import on_android
    disable_gpu_ripple()
    if on_android():
        disable_hover()
else:
    from services.appSvc import app_service_thread
    from services.pathMgr import get_user_data_dir

# Local classes
class BaseMDNavigationItem(MDNavigationItem):
    icon = StringProperty()
    text = StringProperty()

class MainScreenBox(MDBoxLayout):
    top_pad = NumericProperty(0)
    bottom_pad = NumericProperty(0)
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if platform == "android":
            try:
                from android.display_cutout import get_height_of_bar
                self.top_pad = int(get_height_of_bar('status'))
                self.bottom_pad = int(get_height_of_bar('navigation'))
            except Exception as e:
                print(f"Display cutout unavailable (older android fallback): {e}")
                self.top_pad = dp(28)
                self.bottom_pad = dp(42)

## Global definitions
__version__ = "0.3.0" # App version


# Determine the base path for your application's resources
if getattr(sys, 'frozen', False):
    # Running as a PyInstaller bundle
    base_path = sys._MEIPASS
else:
    # Running in a normal Python environment
    base_path = os.path.dirname(os.path.abspath(__file__))
kv_file_path = os.path.join(base_path, 'main_layout.kv')

## Main App Class
class OpenSmsApp(MDApp):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        Window.bind(on_keyboard=self.events)
        self.txt_dialog = None
        self.test_dialog = None
        self.wake_lock = None
        self.api_started = False
        self.key_exists = False
        self.api_key = None
        self.detected_ips = ["127.0.0.1"]
        self.config_template = {
            "app": "opensms",
            "port": 9292,
            "boot": False,
            "wakelock": True,
            "theme": "Light"
        }
        self.req_template = {
            "port": 9292,
            "server": "stop",
        }

    def build(self):
        self.theme_cls.primary_palette = "Blue"
        self.theme_cls.accent_palette = "Orange"
        self.theme_cls.theme_style = self.config_template.get("theme", "Light")
        return Builder.load_file(kv_file_path)

    ## App logics
    def on_start(self):
        # for android
        if platform == "android":
            from android.storage import app_storage_path
            sdk_version = 28
            try:
                VERSION = autoclass('android.os.Build$VERSION')
                sdk_version = VERSION.SDK_INT
                print(f"Android SDK version: {sdk_version}")
            except Exception as e:
                print(f"Could not check android SDK version: {e}")

            # Guard permission requests for older android versions (API < 33 has no POST_NOTIFICATIONS)
            self.android_permissions = [Permission.WAKE_LOCK, Permission.SEND_SMS]
            if sdk_version >= 33:
                try:
                    self.android_permissions.append(Permission.POST_NOTIFICATIONS)
                except Exception as ex:
                    print(f"POST_NOTIFICATIONS permission not available: {ex}")

            request_permissions(self.android_permissions, self.permission_callback)
            self.internal_storage = app_storage_path()
            self.config_dir = os.path.join(self.internal_storage, 'config')
            os.makedirs(self.config_dir, exist_ok=True)
            self.request_path = os.path.join(self.config_dir, "request.json")
            self.resp_path = os.path.join(self.config_dir, "resp.json")
            if os.path.exists(self.resp_path):
                try:
                    os.remove(self.resp_path)
                except Exception:
                    pass
            self.write_request()
            # start the listener service on Android
            try:
                self.start_service()
            except Exception as e:
                print(f"Error while starting android service: {e}")
        # non android platforms
        else:
            self.internal_storage = get_user_data_dir(self.config_template["app"])
            self.config_dir = os.path.join(str(self.internal_storage), 'config')
            os.makedirs(self.config_dir, exist_ok=True)
            self.request_path = os.path.join(self.config_dir, "request.json")
            self.resp_path = os.path.join(self.config_dir, "resp.json")
            self.write_request()
            Thread(target=app_service_thread, daemon=True).start()

        # All generic setups
        set_config_path(self.config_dir)
        self.app_config = os.path.join(self.config_dir, "config.json")
        auto_start_sw = self.root.ids.settings_scr.ids.auto_start_sw
        port_no_inp = self.root.ids.settings_scr.ids.port_no_inp
        wakelock_sw = self.root.ids.settings_scr.ids.wakelock_sw
        dark_theme_sw = self.root.ids.settings_scr.ids.dark_theme_sw

        if os.path.exists(self.app_config):
            try:
                with open(self.app_config, "r", encoding="utf-8") as cf:
                    saved_config = json.load(cf)
                self.config_template["port"] = int(saved_config.get("port", 9292))
                self.config_template["boot"] = bool(saved_config.get("boot", False))
                self.config_template["wakelock"] = bool(saved_config.get("wakelock", True))
                self.config_template["theme"] = saved_config.get("theme", "Light")
            except Exception as e:
                print(f"Config load error: {e}")

            self.req_template["port"] = int(self.config_template["port"])
            if self.config_template["boot"]:
                self.req_template["server"] = "start"
                auto_start_sw.active = True
                Thread(target=self.write_request, daemon=True).start()
            else:
                auto_start_sw.active = False
        else:
            self.write_app_conf()

        port_no_inp.text = str(self.config_template["port"])
        wakelock_sw.active = self.config_template.get("wakelock", True)
        dark_theme_sw.active = (self.config_template.get("theme") == "Dark")
        self.theme_cls.theme_style = self.config_template.get("theme", "Light")

        api_keys = get_api_keys()
        if len(api_keys) >= 1:
            self.key_exists = True

        # Discover network IP addresses
        self.update_network_addresses()

        Thread(target=self.resp_check_loop, daemon=True).start()
        print("Init success...")

    def update_network_addresses(self):
        """Find local Wi-Fi, Ethernet, and VPN IP addresses, prioritizing Tailscale."""
        self.detected_ips = get_device_ip_addresses()
        port = self.req_template.get("port", 9292)
        ip_label_text = ", ".join(self.detected_ips)
        ts_status = TailscaleService.get_status()
        preferred_endpoint, net_type = TailscaleService.get_preferred_endpoint(port)

        try:
            home_scr = self.root.ids.home_scr
            home_scr.is_online = self.api_started
            home_scr.has_tailscale = ts_status["connected"]

            if hasattr(home_scr.ids, "ts_chip_lbl"):
                if ts_status["connected"]:
                    home_scr.ids.ts_chip_lbl.text = f"Tailscale Mesh: Connected ({ts_status['ip']})"
                else:
                    home_scr.ids.ts_chip_lbl.text = "Tailscale: Not detected (Tap Mesh to view guide)"

            if hasattr(home_scr.ids, "ip_addresses_lbl"):
                home_scr.ids.ip_addresses_lbl.text = f"{ip_label_text}"

            if hasattr(home_scr.ids, "api_endpoint_lbl"):
                home_scr.ids.api_endpoint_lbl.text = f"Endpoint ({net_type}): {preferred_endpoint}"

            if hasattr(self.root.ids, "tailscale_scr"):
                self.root.ids.tailscale_scr.update_tailscale_info(port=port)
        except Exception as e:
            print(f"Notice: address labels not ready: {e}")

    def get_service_class(self, activity):
        try:
            pkg = activity.getPackageName()
            return autoclass(f"{pkg}.ServiceOpensmssvc")
        except Exception:
            try:
                return autoclass('com.shanutechx.opensms.ServiceOpensmssvc')
            except Exception:
                return autoclass('in.daslearning.opensms.ServiceOpensmssvc')

    def start_service(self):
        PythonActivity = autoclass('org.kivy.android.PythonActivity')
        mActivity = PythonActivity.mActivity
        service = self.get_service_class(mActivity)
        argument = os.environ.get('PYTHON_SERVICE_ARGUMENT', '')
        print(f"PYTHON_SERVICE_ARGUMENT: {argument}")
        service.start(mActivity, 'icon', 'OpenSMS API', 'Service Running', argument)

    def stop_service(self):
        PythonActivity = autoclass('org.kivy.android.PythonActivity')
        mActivity = PythonActivity.mActivity
        service = self.get_service_class(mActivity)
        service.stop(mActivity)


    def resp_check_loop(self):
        import time
        time.sleep(0.5)
        while True:
            resp = None
            if os.path.exists(self.resp_path):
                try:
                    with open(self.resp_path, "r", encoding="utf-8") as rf:
                        resp = json.load(rf)
                    if resp:
                        server_stat = resp.get("server", "")
                        port = self.req_template.get("port", 9292)
                        preferred_endpoint, net_type = TailscaleService.get_preferred_endpoint(port)

                        if server_stat == "started" and not self.api_started:
                            self.api_started = True
                            if self.config_template.get("wakelock", True):
                                self.acquire_wakelock()
                            # Thread-safe UI update
                            def update_started_ui(dt):
                                home = self.root.ids.home_scr
                                home.is_online = True
                                home.ids.api_srv_lbl.text = "GATEWAY ONLINE"
                                home.ids.api_port_sublbl.text = f"Listening on Port {port} • Ready"
                                home.ids.api_srv_btn.btn_icon = "stop"
                                home.ids.api_srv_btn.btn_txt = "Stop Server"
                                home.ids.api_srv_btn.btn_colour = "orange"
                                if hasattr(home.ids, "status_icon"):
                                    home.ids.status_icon.icon = "check-circle"
                                if hasattr(home.ids, "api_endpoint_lbl"):
                                    home.ids.api_endpoint_lbl.text = f"Endpoint ({net_type}): {preferred_endpoint}"
                                self.show_toast_msg("API Server Started")
                            Clock.schedule_once(update_started_ui)

                        elif server_stat == "stopped" and self.api_started:
                            self.api_started = False
                            self.release_wakelock()
                            # Thread-safe UI update
                            def update_stopped_ui(dt):
                                home = self.root.ids.home_scr
                                home.is_online = False
                                home.ids.api_srv_lbl.text = "GATEWAY STANDBY"
                                home.ids.api_port_sublbl.text = f"Port {port} • Tap Start Server below"
                                home.ids.api_srv_btn.btn_icon = "play"
                                home.ids.api_srv_btn.btn_txt = "Start Server"
                                home.ids.api_srv_btn.btn_colour = "green"
                                if hasattr(home.ids, "status_icon"):
                                    home.ids.status_icon.icon = "cellphone-wireless"
                                self.show_toast_msg("API Server Stopped")
                            Clock.schedule_once(update_stopped_ui)

                        elif server_stat == "error":
                            error_detail = resp.get("error", "Port conflict or bind error")
                            if self.api_started:
                                self.api_started = False
                                self.release_wakelock()
                            def update_error_ui(dt):
                                home = self.root.ids.home_scr
                                home.is_online = False
                                home.ids.api_srv_lbl.text = "SERVER ERROR"
                                home.ids.api_port_sublbl.text = f"Error: {error_detail}"
                                home.ids.api_srv_btn.btn_icon = "play"
                                home.ids.api_srv_btn.btn_txt = "Start Server"
                                home.ids.api_srv_btn.btn_colour = "green"
                                self.show_toast_msg(f"Server Error: {error_detail}", is_error=True)
                            Clock.schedule_once(update_error_ui)

                except Exception as e:
                    # Ignore transient read collisions while file is being written
                    pass
            time.sleep(1.5)

    def write_app_conf(self):
        atomic_write_json(self.app_config, self.config_template)

    def write_request(self):
        atomic_write_json(self.request_path, self.req_template)

    def api_server_mgr(self, instance=None):
        permissions_ok = self.check_request_android_permission()
        if not permissions_ok:
            return
        key_ok = self.check_if_key_exists()
        if key_ok:
            if not self.api_started:
                self.req_template["server"] = "start"
                self.write_request()
            else:
                self.req_template["server"] = "stop"
                self.write_request()
        else:
            self.new_api_key_pop()

    def check_request_android_permission(self):
        if platform == "android":
            permission_flag = True
            for permission in self.android_permissions:
                tmp_flag = check_permission(permission)
                if not tmp_flag:
                    permission_flag = False
                    break
            if not permission_flag:
                request_permissions(self.android_permissions, self.permission_callback)
            return permission_flag
        else:
            return True

    def permission_callback(self, permissions, results):
        if False in results:
            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            current_activity = PythonActivity.mActivity
            usr_deny_flag = False
            for permission in permissions:
                try:
                    should_show = current_activity.shouldShowRequestPermissionRationale(permission)
                    if not should_show:
                        usr_deny_flag = True
                        break
                except Exception:
                    pass
            if usr_deny_flag:
                print("Permission permanently denied by user")
                Clock.schedule_once(lambda dt: self.show_settings_popup())

    def show_settings_popup(self):
        buttons = MDDialogButtonContainer(
            Widget(),
            MDButton(
                MDButtonText(text="Cancel"),
                style="text",
                on_release=self.txt_dialog_closer
            ),
            MDButton(
                MDButtonText(text="Open Settings", theme_text_color="Custom", text_color="orange"),
                style="text",
                on_release=self.open_android_settings
            ),
            spacing="8dp",
        )
        self.show_text_dialog(
            "Permissions Missing",
            "Please grant SMS and Notification permissions in Android Settings for OpenSMS to work properly.",
            None,
            buttons
        )

    def open_android_settings(self, instance=None):
        self.txt_dialog_closer()
        try:
            Intent = autoclass('android.content.Intent')
            Settings = autoclass('android.provider.Settings')
            Uri = autoclass('android.net.Uri')
            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            activity = PythonActivity.mActivity
            intent = Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS)
            uri = Uri.fromParts("package", activity.getPackageName(), None)
            intent.setData(uri)
            activity.startActivity(intent)
        except Exception as e:
            print(f"Error opening settings: {e}")

    def check_if_key_exists(self):
        api_keys = get_api_keys()
        self.key_exists = (len(api_keys) >= 1)
        return self.key_exists

    def new_api_key_pop(self):
        buttons = MDDialogButtonContainer(
            Widget(),
            MDButton(
                MDButtonText(text="Cancel"),
                style="text",
                on_release=self.txt_dialog_closer
            ),
            MDButton(
                MDButtonText(text="Generate", theme_text_color="Custom", text_color="green"),
                style="text",
                on_release=self.create_new_api_key
            ),
            spacing="8dp",
        )
        self.show_text_dialog(
            "Generate API Key",
            "Generate a new API key? This will immediately invalidate existing keys.",
            None,
            buttons
        )

    def create_new_api_key(self, instance=None):
        self.txt_dialog_closer()
        self.api_key = generate_new_api_key()
        if self.api_key:
            Clipboard.copy(self.api_key)
            custom = MDDialogContentContainer(
                ApiKeyTxtbox(text=self.api_key)
            )
            buttons = MDDialogButtonContainer(
                Widget(),
                MDButton(
                    MDButtonText(text="Dismiss"),
                    style="text",
                    on_release=self.close_key_dialog
                ),
                MDButton(
                    MDButtonText(text="Copy Key", theme_text_color="Custom", text_color="green"),
                    style="text",
                    on_release=self.copy_api_key
                ),
                spacing="8dp",
            )
            self.show_text_dialog(
                "Your New API Key",
                "The key is copied to clipboard. Store it securely! It will not be displayed again.",
                custom,
                buttons
            )
        else:
            Clock.schedule_once(lambda dt: self.show_toast_msg("Failed to generate API key, try again!", is_error=True))

    def copy_api_key(self, instance=None):
        if self.api_key:
            Clipboard.copy(self.api_key)
        self.close_key_dialog()
        Clock.schedule_once(lambda dt: self.show_toast_msg("API Key copied to clipboard."))

    def close_key_dialog(self, instance=None):
        self.txt_dialog_closer()
        # SEC-01: Wipe API key from memory after copy/dismiss
        self.api_key = None

    ## Copy helpers for home screen
    def copy_endpoint_url(self, instance=None):
        port = self.req_template.get("port", 9292)
        primary_ip = self.detected_ips[0] if self.detected_ips else "127.0.0.1"
        url = f"http://{primary_ip}:{port}/sms/"
        Clipboard.copy(url)
        self.show_toast_msg(f"Copied endpoint: {url}")

    def copy_curl_example(self, instance=None):
        port = self.req_template.get("port", 9292)
        primary_ip = self.detected_ips[0] if self.detected_ips else "127.0.0.1"
        curl_cmd = (
            f"curl -i -X POST 'http://{primary_ip}:{port}/sms/' \\\n"
            f"  -H 'Content-Type: application/json' \\\n"
            f"  -H 'Authorization: Bearer YOUR_API_KEY' \\\n"
            f"  -d '{{\"number\": \"+1234567890\", \"text\": \"Hello from OpenSMS!\"}}'"
        )
        Clipboard.copy(curl_cmd)
        self.show_toast_msg("cURL command copied to clipboard!")

    ## Settings section
    def save_settings(self, instance=None, control_txt="none"):
        port_no_inp = self.root.ids.settings_scr.ids.port_no_inp
        if control_txt == "switch":
            self.config_template["boot"] = not self.config_template.get("boot", False)

        raw_port = port_no_inp.text.strip()
        if raw_port:
            try:
                port_no = int(raw_port)
                if not (1025 <= port_no <= 65535):
                    self.show_toast_msg("Port must be between 1025 and 65535", is_error=True)
                    return
                self.config_template["port"] = port_no
                self.req_template["port"] = port_no
            except ValueError:
                self.show_toast_msg("Invalid port number", is_error=True)
                return

        port = self.config_template["port"]
        boot = self.config_template["boot"]
        print(f"Service configuration saved: boot={boot}, port={port}")
        Thread(target=self.write_app_conf, daemon=True).start()
        Thread(target=self.write_request, daemon=True).start()
        self.update_network_addresses()
        Clock.schedule_once(lambda dt: self.show_toast_msg("Settings saved successfully."))

    def toggle_theme(self, switch_instance):
        new_style = "Dark" if switch_instance.active else "Light"
        self.theme_cls.theme_style = new_style
        self.config_template["theme"] = new_style
        Thread(target=self.write_app_conf, daemon=True).start()

    def toggle_wakelock_setting(self, switch_instance):
        enabled = switch_instance.active
        self.config_template["wakelock"] = enabled
        if enabled and self.api_started:
            self.acquire_wakelock()
        elif not enabled:
            self.release_wakelock()
        Thread(target=self.write_app_conf, daemon=True).start()

    def refresh_settings_view(self):
        scr = self.root.ids.settings_scr.ids
        scr.auto_start_sw.active = self.config_template.get("boot", False)
        scr.port_no_inp.text = str(self.config_template.get("port", 9292))
        scr.wakelock_sw.active = self.config_template.get("wakelock", True)
        scr.dark_theme_sw.active = (self.config_template.get("theme") == "Dark")

    def confirm_reset_settings(self, instance=None):
        buttons = MDDialogButtonContainer(
            Widget(),
            MDButton(
                MDButtonText(text="Cancel"),
                style="text",
                on_release=self.txt_dialog_closer
            ),
            MDButton(
                MDButtonText(text="Reset", theme_text_color="Custom", text_color="red"),
                style="text",
                on_release=self.reset_settings
            ),
            spacing="8dp",
        )
        self.show_text_dialog(
            "Reset Settings",
            "Reset all settings to default values (Port 9292, Auto-start disabled)?",
            None,
            buttons
        )

    def reset_settings(self, instance=None):
        self.txt_dialog_closer()
        self.config_template = {
            "app": "opensms",
            "port": 9292,
            "boot": False,
            "wakelock": True,
            "theme": "Light"
        }
        self.req_template["port"] = 9292
        self.theme_cls.theme_style = "Light"
        self.refresh_settings_view()
        self.update_network_addresses()
        Thread(target=self.write_app_conf, daemon=True).start()
        Thread(target=self.write_request, daemon=True).start()
        Clock.schedule_once(lambda dt: self.show_toast_msg("Settings reset to defaults."))

    ## Wakelock handling
    def acquire_wakelock(self):
        if self.wake_lock:
            return
        if platform == "android":
            try:
                PythonActivity = autoclass("org.kivy.android.PythonActivity")
                Context = autoclass("android.content.Context")
                activity = PythonActivity.mActivity
                PowerManager = autoclass("android.os.PowerManager")
                power_manager = cast(PowerManager, activity.getSystemService(Context.POWER_SERVICE))
                # Use PARTIAL_WAKE_LOCK (keeps CPU on in background without screen)
                self.wake_lock = power_manager.newWakeLock(
                    PowerManager.PARTIAL_WAKE_LOCK, "OpenSmsApp::WakeLockTag"
                )
                self.wake_lock.acquire()
                print("Partial WakeLock acquired")
            except Exception as e:
                print(f"Wake lock acquire error: {e}")

    def release_wakelock(self):
        if self.wake_lock and self.wake_lock.isHeld():
            try:
                self.wake_lock.release()
                self.wake_lock = None
                print("WakeLock released")
            except Exception as e:
                print(f"Wake lock release error: {e}")

    ## UI helpers & dialogs
    def show_toast_msg(self, message, is_error=False, duration=3):
        try:
            from kivymd.uix.snackbar import MDSnackbar, MDSnackbarText
            bg_color = (0.15, 0.55, 0.25, 1) if not is_error else (0.8, 0.2, 0.2, 1)
            MDSnackbar(
                MDSnackbarText(text=message),
                y=dp(24),
                orientation="horizontal",
                pos_hint={"center_x": 0.5},
                background_color=bg_color,
            ).open()
        except Exception as e:
            print(f"Toast [{message}]: {e}")

    def show_text_dialog(
            self,
            title,
            text="",
            custom_content: MDDialogContentContainer | None = None,
            buttons: MDDialogButtonContainer | None = None
        ):
        # BUG-06 fix: Only pass non-None widgets to MDDialog
        widgets = [
            MDDialogHeadlineText(text=title),
            MDDialogSupportingText(text=text)
        ]
        if custom_content:
            widgets.append(custom_content)
        if buttons:
            widgets.append(buttons)

        self.txt_dialog = MDDialog(*widgets)
        self.txt_dialog.open()

    def txt_dialog_closer(self, instance=None):
        if self.txt_dialog:
            self.txt_dialog.dismiss()
            self.txt_dialog = None

    ## Test SMS Dialog
    def show_test_sms_dialog(self, instance=None):
        from kivymd.uix.label import MDLabel
        phone_input = MDTextField(
            mode="outlined",
            hint_text="Phone Number (e.g. +1234567890)",
            text="",
            size_hint_y=None,
            height=dp(56)
        )
        msg_input = MDTextField(
            mode="outlined",
            hint_text="Message text",
            text="Hello from OpenSMS test!",
            size_hint_y=None,
            height=dp(56)
        )

        calc_init = calculate_sms_segments(msg_input.text)
        metrics_lbl = MDLabel(
            text=f"{calc_init['length']} chars • {calc_init['segments']} segment(s) ({calc_init['encoding']})",
            font_style="Label",
            role="small",
            theme_text_color="Secondary",
            adaptive_height=True
        )

        def on_msg_change(inst, val):
            c = calculate_sms_segments(val)
            metrics_lbl.text = f"{c['length']} chars • {c['segments']} segment(s) ({c['encoding']})"

        msg_input.bind(text=on_msg_change)

        content_box = MDBoxLayout(
            phone_input,
            msg_input,
            metrics_lbl,
            orientation="vertical",
            spacing=dp(10),
            adaptive_height=True
        )
        content_container = MDDialogContentContainer(content_box)

        def do_send(inst):
            phone = sanitize_phone_number(phone_input.text)
            msg = msg_input.text.strip()
            if not phone or not msg:
                self.show_toast_msg("Valid phone number and message cannot be empty", is_error=True)
                return
            self.txt_dialog_closer()
            self.show_toast_msg(f"Sending test SMS to {phone}...")
            def worker():
                stat = send_sms(phone, msg)
                if stat:
                    Clock.schedule_once(lambda dt: self.show_toast_msg(f"Test SMS sent to {phone}!"))
                else:
                    Clock.schedule_once(lambda dt: self.show_toast_msg("Test SMS failed to send", is_error=True))
            Thread(target=worker, daemon=True).start()

        buttons = MDDialogButtonContainer(
            Widget(),
            MDButton(
                MDButtonText(text="Cancel"),
                style="text",
                on_release=self.txt_dialog_closer
            ),
            MDButton(
                MDButtonText(text="Send SMS", theme_text_color="Custom", text_color="green"),
                style="text",
                on_release=do_send
            ),
            spacing="8dp",
        )
        self.show_text_dialog(
            "Send Test SMS",
            "Verify your cellular carrier, SIM card, and SMS permissions directly.",
            content_container,
            buttons
        )

    ## VPN & Remote Access Guide Dialog
    def show_vpn_guide_dialog(self, instance=None):
        self.goto_tailscale_screen()

    def show_about_dialog(self, instance=None):
        about_text = (
            f"OpenSMS v{__version__}\n\n"
            "An open-source solution to host an SMS API gateway on your Android device.\n\n"
            "• Privacy focused, no ads, no trackers\n"
            "• Compatible with Android 7.0 (API 24) to Android 15+\n"
            "• Tailscale WireGuard Mesh integration for multi-network cross-connect\n"
            "• Supports local Wi-Fi, VPN mesh, and multi-network routing"
        )
        buttons = MDDialogButtonContainer(
            Widget(),
            MDButton(
                MDButtonText(text="Close"),
                style="text",
                on_release=self.txt_dialog_closer
            ),
            spacing="8dp",
        )
        self.show_text_dialog(
            "About OpenSMS",
            about_text,
            None,
            buttons
        )

    ## Drawer action hooks
    def open_test_sms_from_drawer(self):
        if hasattr(self.root.ids, "nav_drawer"):
            self.root.ids.nav_drawer.set_state("close")
        Clock.schedule_once(lambda dt: self.show_test_sms_dialog(), 0.2)

    def open_vpn_guide_from_drawer(self):
        self.goto_tailscale_screen()

    def open_about_from_drawer(self):
        if hasattr(self.root.ids, "nav_drawer"):
            self.root.ids.nav_drawer.set_state("close")
        Clock.schedule_once(lambda dt: self.show_about_dialog(), 0.2)

    def goto_logs_screen(self, instance=None):
        if hasattr(self.root.ids, "nav_drawer"):
            self.root.ids.nav_drawer.set_state("close")
        self.go_to_screen("Logs")

    def goto_tailscale_screen(self, instance=None):
        if hasattr(self.root.ids, "nav_drawer"):
            self.root.ids.nav_drawer.set_state("close")
        self.go_to_screen("Mesh")

    def go_to_screen(self, screen: str):
        self.root.ids.screen_manager.current = screen

    def on_main_screen_entry(self, instance=None):
        self.root.ids.top_back_btn.opacity = 0
        self.root.ids.top_back_btn.disabled = True
        self.update_network_addresses()

    def on_tailscale_screen_entry(self, instance=None):
        self.root.ids.top_back_btn.opacity = 1
        self.root.ids.top_back_btn.disabled = False
        port = self.req_template.get("port", 9292)
        if hasattr(self.root.ids, "tailscale_scr"):
            self.root.ids.tailscale_scr.update_tailscale_info(port=port)

    def on_settings_entry(self, instance=None):
        self.root.ids.top_back_btn.opacity = 1
        self.root.ids.top_back_btn.disabled = False

    def back_button_action(self, instance=None):
        if self.root.ids.screen_manager.current in ["Settings", "Logs", "Mesh"]:
            self.go_to_screen("SMS")

    def events(self, instance, keyboard, keycode, text, modifiers):
        """Handle mobile device back button."""
        if keyboard in (1001, 27):
            if self.txt_dialog:
                self.txt_dialog_closer()
                return True
            if self.root.ids.screen_manager.current in ["Settings", "Logs", "Mesh"]:
                self.back_button_action()
                return True
        return False

    def on_stop(self):
        print("Exiting app...")
        if platform == "android":
            self.stop_service()
            self.release_wakelock()

    def on_switch_tabs(
            self,
            bar: MDNavigationBar,
            item: MDNavigationItem,
            item_icon: str,
            item_text: str,
        ):
        self.root.ids.screen_manager.current = item_text

if __name__ == '__main__':
    OpenSmsApp().run()

