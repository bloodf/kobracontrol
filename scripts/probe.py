"""Read-only smoke test against a real Kobra X: python3 scripts/probe.py <printer-ip> [--slicer PATH].

Finds the Anycubic Slicer client certificate, recovers the LAN credentials, connects MQTT and sends only
info/query and multiColorBox/getInfo (nothing that moves, heats or changes the printer). Secrets are never
printed. Exit 0 on success, 1 with a one-line reason at the first step that failed.
"""

import argparse
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "kobracontrol"))

import certs  # noqa: E402
import kobra  # noqa: E402


class StepFailed(Exception):
    pass


def step(name, fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except (kobra.KobraError, certs.CertError, OSError) as e:
        raise StepFailed("%s: %s" % (name, e)) from None


def summary(view, creds):
    boxes = [b for b in view["multi_color_box"] if isinstance(b, dict)]
    slots = sum(len(b.get("slots") or []) for b in boxes)
    return "\n".join([
        "model:       %s (%s)" % (view["printer_name"] or "?", creds.model),
        "firmware:    %s" % (view["firmware"] or "?"),
        "state:       %s (raw %r)" % (view["state"], view["kobra_state"]),
        "nozzle:      %s / %s C" % (view["nozzle_temp"], view["nozzle_target"]),
        "bed:         %s / %s C" % (view["bed_temp"], view["bed_target"]),
        "ACE boxes:   %d (%d slots)" % (len(boxes), slots),
        "upload URL:  %s" % ("yes" if view["upload_url"] else "no"),
        "camera URL:  %s" % ("yes" if view["camera_url"] or view["camera_urls"] else "no"),
    ])


def run(ip, slicer=None, http_port=18910, mqtt_port=9883, out=print):
    found = step("certificate", certs.find, [slicer] if slicer else certs.default_locations())
    out("certificate: found in %s" % os.path.basename(found.source))
    tmp = tempfile.mkdtemp(prefix="kobracontrol-probe-")
    try:
        ctx = step("certificate", certs.context, *certs.save(tmp, found.cert_pem, found.key_pem))
        creds = step("credentials", kobra.fetch_credentials, ip, port=http_port)
        out("credentials: ok (%s)" % creds.model)
        state = kobra.State(model=creds.model)
        printer = kobra.Printer(creds, ssl_context=ctx, mqtt_port=mqtt_port, http_port=http_port, on_report=state.apply)
        step("mqtt", printer.connect)
        try:
            state.connected = True
            step("info/query", lambda: kobra.check_reply(printer.query_info(), "info/query"))
            step("multiColorBox/getInfo", lambda: kobra.check_reply(printer.query_multi_color_box(), "multiColorBox/getInfo"))
            out(summary(state.view(), creds))
        finally:
            printer.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("ip")
    parser.add_argument("--slicer", help="Anycubic Slicer Next install folder or library file")
    args = parser.parse_args(argv)
    try:
        run(args.ip, args.slicer)
    except StepFailed as e:
        print("FAILED %s" % e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
