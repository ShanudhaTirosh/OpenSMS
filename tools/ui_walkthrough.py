"""
Headless UI walkthrough (not part of the default pytest run).

Launches the REAL app under a virtual display with throw-away data, seeds sample messages/keys, drives the
Messages and API screens (filter, detail, create key with validation, one-time key, revoke confirm, empty
search, dark theme) and saves screenshots.

    pip install kivy==2.3.1 https://github.com/kivymd/KivyMD/archive/master.zip fastapi "uvicorn<0.35" requests
    cd app && xvfb-run -a -s "-screen 0 1080x1920x24" python ../tools/ui_walkthrough.py

Run from the app/ directory. Screenshots go to OUT below. Needs a GL-capable (software) display; on Linux install
xvfb and libgl1-mesa-dri.
"""
import os, sys, time, json
os.environ.update(KIVY_NO_ARGS="1", HOME="/tmp/hh", XDG_DATA_HOME="/tmp/hh", OPENSMS_ALLOW_SIMULATION="1")
sys.path.insert(0, ".")
from kivy.config import Config
Config.set("graphics", "width", "412"); Config.set("graphics", "height", "860")
import main as M
from kivy.clock import Clock
OUT = os.environ.get("OPENSMS_SHOT_DIR", "/tmp/opensms-shots")
os.makedirs(OUT, exist_ok=True)
log = []
errors = []

class Shots(M.OpenSmsApp):
    def on_start(self):
        super().on_start()
        try:
            self.steps = [self.s_seed, self.s_overview, self.s_msgs, self.s_msgs_failed, self.s_detail, self.s_api, self.s_newkey, self.s_keyshown, self.s_revoke, self.s_empty_search, self.s_compose, self.s_compose_invalid, self.s_compose_review, self.s_compose_send, self.s_system, self.s_system_clear, self.s_dark_msgs, self.s_done]
            Clock.schedule_once(self.run_step, 1.5)
        except Exception as e:
            errors.append(("on_start_error", repr(e))); self.stop()
    def run_step(self, dt):
        if not self.steps: return
        fn = self.steps.pop(0)
        try: delay = fn() or 0.9
        except Exception:
            import traceback; errors.append((fn.__name__, traceback.format_exc()[-600:])); delay = 0.5
        Clock.schedule_once(self.run_step, delay)
    def shot(self, name):
        from kivy.core.window import Window
        Window.screenshot(name=f"{OUT}/{name}.png")
    # ---- steps
    def s_seed(self):
        from services.dbMgr import DatabaseManager
        db = DatabaseManager.get_instance(self.config_dir)
        now = time.time()
        rows = [("+94771234567","Your verification code is 482913","delivered",now-300,None,2),
                ("+94712345678","Meeting moved to 3pm, see you in the lobby. Reply STOP to cancel.","sent",now-3600,None,1),
                ("+94770001122","Order #1043 has shipped","submitted",now-60,None,1),
                ("+94775550101","Hello from the gateway","failed",now-86400*1.2,"Radio is off (airplane mode?)",1),
                ("+94779998877","Queued message","queued",now-5,None,1),
                ("+94774443322","Lost during restart","unknown",now-86400*3,"No radio result received; the message may or may not have been sent",1)]
        for i,(to,text,st,ts,err,parts) in enumerate(rows):
            mid = db.create_message(to, text, status="queued", provider="android")
            db.record_parts(mid, parts)
            if st in ("sent","delivered"):
                for p in range(parts): db.update_part(mid, p, sent_ok=True)
            if st == "delivered":
                for p in range(parts): db.update_part(mid, p, delivery="delivered")
            db.update_message_status(mid, st, carrier_error=err)
            with db._conn() as c: c.execute("UPDATE messages SET created_at=?, updated_at=? WHERE id=?", (ts, ts, mid))
        for i in range(21):
            mid = db.create_message(f"+9477100{i:04d}", f"bulk {i}", status="sent", provider="android")
            with db._conn() as c: c.execute("UPDATE messages SET created_at=?, updated_at=? WHERE id=?", (now-86400*5-i*60, now-86400*5-i*60, mid))
        from services import postApi
        postApi.set_config_path(self.config_dir)
        postApi.generate_new_api_key("Home server", ["sms:write","sms:read"])
        postApi.generate_new_api_key("Ops dashboard", ["admin"])
        postApi.generate_new_api_key("Old CI key", ["sms:write"])
        for r in db.list_api_keys():
            if r["name"] == "Old CI key": db.revoke_api_key(r["id"])
        log.append(("seeded", db.count_messages()))
    def s_overview(self): self.go_to_screen("SMS"); return 1.0
    def s_msgs(self): self.go_to_screen("Messages"); Clock.schedule_once(lambda dt: self.shot("4_messages"), 1.4); return 2.0
    def s_msgs_failed(self):
        box = self.root.ids.messages_scr; box.set_filter("failed"); Clock.schedule_once(lambda dt: self.shot("5_messages_failed_filter"), 1.0); return 1.6
    def s_detail(self):
        box = self.root.ids.messages_scr; box.set_filter("all")
        def open_it(dt):
            sent = box._db().get_messages(status="failed")[0]; box.open_detail(sent)
            Clock.schedule_once(lambda dt: self.shot("6_message_detail"), 0.8)
        Clock.schedule_once(open_it, 1.0); return 2.2
    def s_api(self):
        self.txt_dialog_closer(); self.go_to_screen("API"); Clock.schedule_once(lambda dt: self.shot("7_api_keys"), 1.2); return 1.8
    def s_newkey(self):
        self.root.ids.api_scr.show_create_dialog(); Clock.schedule_once(lambda dt: self.shot("8_new_key_dialog"), 0.9); return 1.4
    def s_keyshown(self):
        # real create flow through the dialog's own Create handler: empty name first (inline validation), then valid
        d = self.txt_dialog
        def find(w, cls, acc):
            if w.__class__.__name__ == cls: acc.append(w)
            for c in w.children: find(c, cls, acc)
            return acc
        btns = [b for b in find(d, "MDButton", []) if any(getattr(c, "text", "") == "Create" for c in find(b, "MDButtonText", []))]
        btns[0].dispatch("on_release")
        errs = [l.text for l in find(d, "MDLabel", []) if "name" in l.text.lower()]
        log.append(("inline_validation", errs))
        self.shot("9_new_key_validation")
        field = find(d, "MDTextField", [])[0]; field.text = "Billing service"
        btns[0].dispatch("on_release")
        Clock.schedule_once(lambda dt: self.shot("10_key_shown_once"), 1.0); return 1.6
    def s_revoke(self):
        self.txt_dialog_closer()
        box = self.root.ids.api_scr
        box._confirm_revoke(box._db().list_api_keys()[0]["id"], "Billing service")
        Clock.schedule_once(lambda dt: self.shot("11_revoke_confirm"), 0.8); return 1.4
    def s_empty_search(self):
        self.txt_dialog_closer(); self.go_to_screen("Messages")
        box = self.root.ids.messages_scr; box.ids.search_inp.text = "zzz-no-match"
        Clock.schedule_once(lambda dt: self.shot("12_messages_empty_search"), 1.8); return 2.4
    # ---- compose flow (service loop is not running in this harness, so the outbox file is checked instead)
    def _find(self, w, cls, acc):
        if w.__class__.__name__ == cls: acc.append(w)
        for c in w.children: self._find(c, cls, acc)
        return acc
    def _btn(self, label):
        return [b for b in self._find(self.txt_dialog, "MDButton", []) if any(getattr(c, "text", "") == label for c in self._find(b, "MDButtonText", []))][0]
    def s_compose(self):
        self.root.ids.messages_scr.ids.search_inp.text = ""
        self.root.ids.messages_scr.show_compose_dialog()
        Clock.schedule_once(lambda dt: self.shot("14_compose"), 0.8); return 1.4
    def s_compose_invalid(self):
        d = self.txt_dialog
        fields = list(reversed(self._find(d, "MDTextField", [])))   # Kivy lists children last-added first
        fields[0].text = "abc"; fields[1].text = "Hello from the compose dialog"
        self._btn("Review").dispatch("on_release")
        errs = [l.text for l in self._find(d, "MDLabel", []) if "phone" in l.text.lower() or "digit" in l.text.lower()]
        log.append(("compose_validation", errs))
        Clock.schedule_once(lambda dt: self.shot("15_compose_invalid"), 0.6); return 1.2
    def s_compose_review(self):
        fields = list(reversed(self._find(self.txt_dialog, "MDTextField", [])))
        fields[0].text = "+94771234567"
        self._btn("Review").dispatch("on_release")
        Clock.schedule_once(lambda dt: self.shot("16_compose_confirm"), 1.6); return 2.4
    def s_compose_send(self):
        import os, json as _j
        btn = self._btn("Send")
        btn.dispatch("on_release"); btn.dispatch("on_release")            # a double tap must queue only one message
        folder = os.path.join(self.config_dir, "outbox")
        files = sorted(os.listdir(folder)) if os.path.isdir(folder) else []
        payloads = [_j.load(open(os.path.join(folder, f))) for f in files]
        log.append(("outbox_files", [(p["number"], p["text"]) for p in payloads]))
        if len(files) != 1: errors.append(("compose_send", f"expected exactly one outbox file, got {len(files)}"))
        return 0.6
    # ---- System screen (diagnostics + maintenance)
    def s_system(self):
        self.go_to_screen("System")
        Clock.schedule_once(lambda dt: self.shot("17_system"), 1.8)
        def check(dt):
            box = self.root.ids.system_scr
            titles = [sec["title"] for sec in box.sections]
            log.append(("system_sections", titles))
            if titles != ["Gateway", "SMS", "Network", "Storage", "App"]:
                errors.append(("system", f"unexpected sections {titles}"))
            import services.diagnostics as _D
            txt = _D.to_text(box.sections)
            if "osms_" in txt:
                errors.append(("system", "report leaks a key"))
        Clock.schedule_once(check, 2.0)
        return 2.6
    def s_system_clear(self):
        from services.dbMgr import DatabaseManager
        db = DatabaseManager.get_instance(self.config_dir)
        before = db.count_messages()
        self.root.ids.system_scr._confirm_clear(None)
        Clock.schedule_once(lambda dt: self.shot("18_clear_confirm"), 0.9)
        def press(dt):
            btn = self._btn("Delete"); btn.dispatch("on_release")
        Clock.schedule_once(press, 1.2)
        def verify(dt):
            after = db.count_messages()
            log.append(("clear_history", (before, after)))
            if after >= before: errors.append(("clear", f"history not cleared: {before} -> {after}"))
        Clock.schedule_once(verify, 2.2)
        return 3.0
    def s_dark_msgs(self):
        self.root.ids.messages_scr.ids.search_inp.text = ""
        self.theme_cls.theme_style = "Dark"; self.theme_style = "Dark"
        Clock.schedule_once(lambda dt: self.shot("13_messages_dark"), 1.8); return 2.4
    def s_done(self):
        json.dump({"log": log, "errors": errors}, open(os.path.join(OUT, "walkthrough_log.json"), "w"), indent=1, default=str); self.stop()

Shots().run()
validation = [v for k, v in log if k == "inline_validation"]
cv = [v for k, v in log if k == "compose_validation"]
if not cv or not cv[0]:
    errors.append(("compose_validation", "invalid phone number message was not shown"))
if not validation or not validation[0]:
    errors.append(("inline_validation", "empty-name validation message was not shown"))
for name, tb in errors:
    print(f"WALKTHROUGH ERROR in {name}:\n{tb}", file=sys.stderr)
sys.exit(1 if errors else 0)
