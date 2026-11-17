import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src", "kobracontrol")]

import spoolman as sm  # noqa: E402


def spool(sid, material="PLA", colour="FF0000", location="", vendor="Generic", **kw):
    return {"id": sid, "location": location, "filament": {"id": sid * 10, "material": material, "color_hex": colour,
                                                          "vendor": {"name": vendor}, "name": "N%d" % sid}, **kw}


class FakeSpoolmanServer:
    def __init__(self, spools=(), fail=None, redirect=None, body=None):
        self.spools, self.calls, self.fail, self.redirect, self.body = list(spools), [], fail, redirect, body
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _do(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n)) if n else None
                outer.calls.append((self.command, self.path, body))
                if outer.redirect:
                    self.send_response(302)
                    self.send_header("Location", outer.redirect)
                    self.end_headers()
                    return
                if outer.fail:
                    self.send_response(outer.fail)
                    self.end_headers()
                    return
                out = outer.spools if self.path.startswith("/api/v1/spool?") else {"status": "healthy"}
                data = outer.body if outer.body is not None else json.dumps(out).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            do_GET = do_PATCH = do_PUT = _do

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.srv = FakeSpoolmanServer([spool(1)])
        self.addCleanup(self.srv.close)

    def test_connect_spools_location_and_use(self):
        c = sm.Spoolman(self.srv.url)
        self.assertEqual(c.connect(), {"via": "direct"})
        self.assertEqual([s["id"] for s in c.spools()], [1])
        c.set_location(1, "Kobra S2")
        c.use_weight(1, 3.14159)
        self.assertEqual(self.srv.calls[0][:2], ("GET", "/api/v1/health"))
        self.assertEqual(self.srv.calls[2][::2], ("PATCH", {"location": "Kobra S2"}))
        self.assertEqual(self.srv.calls[3], ("PUT", "/api/v1/spool/1/use", {"use_weight": 3.14}))

    def test_url_without_scheme_and_unconfigured(self):
        self.assertEqual(sm.Spoolman("127.0.0.1:1234/").url, "http://127.0.0.1:1234")
        with self.assertRaises(sm.SpoolmanError):
            sm.Spoolman("").connect()

    def test_http_error_and_unreachable_are_spoolman_errors(self):
        bad = FakeSpoolmanServer(fail=500)
        self.addCleanup(bad.close)
        with self.assertRaisesRegex(sm.SpoolmanError, "HTTP 500"):
            sm.Spoolman(bad.url).connect()
        dead = FakeSpoolmanServer()
        url = dead.url
        dead.close()
        with self.assertRaisesRegex(sm.SpoolmanError, "can't reach"):
            sm.Spoolman(url, timeout=1).connect()

    def test_ids_are_integers(self):
        with self.assertRaises(ValueError):
            sm.Spoolman(self.srv.url).use_weight("1; drop", 1)


class UrlSafetyTests(unittest.TestCase):
    def test_only_http_and_https_with_a_host(self):
        for bad in ("file:///etc/passwd#", "file:///etc/passwd", "ftp://box/x", "http://", "https:///x", "gopher://box",
                    "http://box:99999", "javascript:alert(1)", "data:text/plain,x"):
            with self.assertRaises(sm.SpoolmanError, msg=bad):
                sm.Spoolman(bad)
            self.assertIsNone(sm.clean_url(bad, strict=False), bad)
        self.assertEqual(sm.clean_url("HTTPS://Box:7912/spool/"), "https://box:7912/spool")
        self.assertEqual(sm.clean_url("box:7912"), "http://box:7912")
        self.assertEqual(sm.clean_url(""), "")
        self.assertEqual(sm.Spoolman("").url, "")

    def test_opener_has_no_file_or_ftp_handler(self):
        names = {type(h).__name__ for h in sm._opener().handlers}
        self.assertFalse(names & {"FileHandler", "FTPHandler", "DataHandler"})

    def test_a_redirect_to_another_host_is_refused(self):
        target = FakeSpoolmanServer([spool(1)])
        src = FakeSpoolmanServer(redirect=target.url + "/api/v1/health")
        for s in (target, src):
            self.addCleanup(s.close)
        with self.assertRaisesRegex(sm.SpoolmanError, "HTTP 302"):
            sm.Spoolman(src.url).connect()
        self.assertEqual(target.calls, [])

    def test_a_redirect_to_a_file_url_is_refused(self):
        src = FakeSpoolmanServer(redirect="file:///etc/passwd")
        self.addCleanup(src.close)
        with self.assertRaises(sm.SpoolmanError):
            sm.Spoolman(src.url).connect()

    def test_an_oversized_body_is_refused(self):
        src = FakeSpoolmanServer(body=b"[" + b"0," * (sm.MAX_BODY // 2 + 10) + b"0]")
        self.addCleanup(src.close)
        with self.assertRaisesRegex(sm.SpoolmanError, "too large"):
            sm.Spoolman(src.url).spools()


class MatchTests(unittest.TestCase):
    def test_best_spool_by_material_family_colour_and_exclusion(self):
        spools = [sm.spool_view(spool(1, "PLA", "FF0000")), sm.spool_view(spool(2, "PETG", "FF0000")),
                  sm.spool_view(spool(3, "PLA", "FE0101"))]
        slot = {"type": "PLA", "color": [255, 0, 0]}
        self.assertEqual(sm.best_spool(slot, spools)["id"], 1)
        self.assertEqual(sm.best_spool(slot, spools, exclude=(1,))["id"], 3)
        self.assertIsNone(sm.best_spool({"type": "ABS", "color": [255, 0, 0]}, spools))
        self.assertIsNone(sm.best_spool({"type": "PLA", "colour": "#00FF00"}, spools))
        self.assertIsNone(sm.best_spool({"type": "", "color": [255, 0, 0]}, spools))

    def test_spool_view_flattens(self):
        v = sm.spool_view(spool(5, "PLA", "ff0000", "Kobra S1", remaining_weight=300.0, initial_weight=1000,
                                last_used="2026-01-01T00:00:00"))
        self.assertEqual((v["id"], v["colour"], v["vendor"], v["remaining"], v["initial"], v["location"]),
                         (5, "#FF0000", "Generic", 300.0, 1000, "Kobra S1"))
        multi = sm.spool_view({"id": 6, "filament": {"multi_color_hexes": "00FF00,0000FF"}})
        self.assertEqual((multi["colour"], multi["colours"]), ("#00FF00", ["#00FF00", "#0000FF"]))
        self.assertEqual(sm.spool_view({"id": 7})["vendor"], "Generic")

    def test_linked_preset_spool_first_then_filament(self):
        """orca_filament_preset: Spoolman keeps extra values JSON-encoded; a raw text is taken as written."""
        enc = lambda v: {"orca_filament_preset": json.dumps(v)}   # noqa: E731
        filament = {"extra": enc("Filament PLA")}
        self.assertEqual(sm.linked_preset({"extra": enc(" My PLA @Anycubic Kobra X "), "filament": filament}),
                         "My PLA @Anycubic Kobra X")
        self.assertEqual(sm.linked_preset({"extra": enc(""), "filament": filament}), "Filament PLA")
        self.assertEqual(sm.linked_preset({"filament": filament}), "Filament PLA")
        self.assertEqual(sm.linked_preset({"extra": {"orca_filament_preset": "Raw name"}}), "Raw name")
        self.assertEqual(sm.linked_preset({"extra": {"orca_filament_preset": "5"}, "filament": filament}), "Filament PLA")
        self.assertEqual(sm.linked_preset({"extra": {"orca_filament_preset": '"  "'}}), "")
        self.assertEqual(sm.linked_preset({"extra": "junk", "filament": {"extra": None}}), "")
        self.assertEqual(sm.spool_view({"id": 8, "filament": filament})["orca_preset"], "Filament PLA")

    def test_colour_helpers(self):
        self.assertEqual(sm.norm_colour("ff0000ff"), "#FF0000")
        self.assertIsNone(sm.norm_colour("red"))
        self.assertEqual(sm.colour_distance("#000000", "#000000"), 0)
        self.assertEqual(sm.colour_distance(None, "#000000"), 765.0)
        self.assertEqual(sm.material_family("PLA-CF"), "PLA")
        self.assertEqual(sm.slot_colour({"color": [1, 2, 3]}), "#010203")
        self.assertEqual(sm.slot_colour({"colour": "abcdef"}), "#ABCDEF")
        self.assertEqual(sm.slot_fields(sm.spool_view(spool(1, "PETG", "00ff00"))),
                         {"type": "PETG", "colour": "#00FF00"})

    def test_slot_changed(self):
        a = {"type": "PLA", "color": [1, 2, 3], "status": 5}
        self.assertFalse(sm.slot_changed(a, dict(a)))
        self.assertTrue(sm.slot_changed(a, {**a, "color": [1, 2, 4]}))
        self.assertTrue(sm.slot_changed(a, {**a, "status": 0}))
        self.assertTrue(sm.slot_changed(None, a))


class BindingTests(unittest.TestCase):
    def test_location_roundtrip(self):
        self.assertEqual(sm.location_for("Kobra X", 2), "Kobra X S3")
        self.assertEqual(sm.location_score("Kobra X S3", "Kobra X", 2), 2)
        self.assertEqual(sm.location_score("kobra   x s3", "KOBRA X", 2), 2)
        self.assertEqual(sm.location_score("Other S3", "Kobra X", 2), 0)
        self.assertEqual(sm.location_score("Kobra X S3", "Kobra X", 1), 0)
        self.assertEqual(sm.location_score("", "Kobra X", 0), 0)
        self.assertEqual(len(sm.location_for("x" * 100, 0)), 64)

    def test_bindings_from_locations(self):
        spools = [sm.spool_view(spool(1, location="Kobra X S1", last_used="2026-01-01")),
                  sm.spool_view(spool(2, location="Kobra X S1", last_used="2026-02-01")),   # used last wins
                  sm.spool_view(spool(3, location="Kobra X S2", archived=True)),            # archived never binds
                  sm.spool_view(spool(4, location="Kobra X S5")),
                  sm.spool_view(spool(5, location="Shelf A")),
                  sm.spool_view(spool(6, location="Other S2"))]
        self.assertEqual(sm.bindings_from_locations(spools, "Kobra X"), {0: 2, 4: 4})

    def test_bindings_ignore_absurd_slot_numbers(self):
        spools = [sm.spool_view(spool(1, location="K S0")), sm.spool_view(spool(2, location="K S999")),
                  sm.spool_view(spool(3, location="K S16"))]
        self.assertEqual(sm.bindings_from_locations(spools, "K"), {15: 3})


if __name__ == "__main__":
    unittest.main()
