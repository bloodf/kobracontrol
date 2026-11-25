"""Check everything (Settings > Requirements): every connection and permission Kobra Control depends on, in one
list. Free of the `orca` module; service.cmd_checkup runs it on the service's worker thread.

Read-only: the printer is reached with the same login and read-only status queries the tab's hello uses
(service.cmd_connect); nothing pauses, stops, moves, heats or feeds. Spoolman gets its /health, Anycubic Cloud its
printer list. Each check reuses the code the plugin already runs for that job.

Each result is {"id", "state": "pass" | "fail" | "off", "reason", "detail", "action"}: "off" means not configured,
`reason` names the failure for the page's plain-English fix, `detail` is what was found or the raw error, and
`action` is what the page can offer ("allow_printer", "allow_spoolman": OrcaSlicer's permission dialog)."""

import cloud
import connection
import locate
import spoolman as sm

PASS, FAIL, OFF = "pass", "fail", "off"
ORDER = ("printer", "login", "certificate", "printer_agents", "spoolman", "cloud")


def result(id_, state, reason="", detail="", action=""):
    return {"id": id_, "state": state, "reason": reason, "detail": detail, "action": action}


def denied(error):
    """OrcaSlicer's audit refused it: a PermissionError, also one wrapped by a client that raised its own error."""
    while error is not None:
        if isinstance(error, PermissionError) or getattr(error, "code", None) == "denied":
            return True
        error = error.__cause__ or error.__context__
    return False


def _target(svc):
    with svc.lock:
        return svc.target


def printer_checks(svc):
    """The printer on the LAN (located, its HTTP /info answers) and its login (certificate + MQTT session). A user's
    check: one login attempt now (retry, as the tab's Retry), not the last error of a connection waiting out its
    backoff."""
    target = _target(svc)
    if target is None or cloud.printer_id(target.host):   # none chosen, or driven through Anycubic Cloud
        reason = "cloud" if target is not None else "no_printer"
        return [result("printer", OFF, reason), result("login", OFF, reason)]
    try:
        info = svc.cmd_connect(retry=True)
    except locate.NotFound as e:
        return [result("printer", FAIL, "not_found", str(e)), result("login", FAIL, "needs_printer")]
    except Exception as e:
        latest = _target(svc)   # read once: locating may have filled the address in meanwhile
        host = latest.host if latest is not None else ""
        conn = svc.connections.get(host) if host else None
        if getattr(conn, "denied", False) or denied(e):
            return [result("printer", FAIL, "denied", str(e), "allow_printer"), result("login", FAIL, "needs_printer")]
        if conn is not None and conn.no_certificate:   # the certificate failed before the printer was contacted
            return [result("printer", OFF, "needs_certificate"), result("login", FAIL, "no_certificate", str(e))]
        if conn is None or conn.http_failed:
            return [result("printer", FAIL, "unreachable", str(e)), result("login", FAIL, "needs_printer")]
        return [result("printer", PASS, detail=host), result("login", FAIL, "held" if conn.held else "login", str(e))]
    about = " · ".join(x for x in (info.get("model"), info.get("firmware")) if x)
    return [result("printer", PASS, detail=info.get("address", "")), result("login", PASS, detail=about)]


def certificate_check(svc):
    """The client certificate the printer login uses loads (the saved one, else the bundled one)."""
    try:
        svc.tls()
    except connection.NoCertificate as e:
        return [result("certificate", FAIL, "no_certificate", str(e))]
    found = next((i for i in svc.host_requirements if i["id"] == "certificate"), None)
    return [result("certificate", PASS, detail=found["details"] if found else "")]


def printer_agents_check(svc):
    """OrcaSlicer's printer agents (Print, Send, the Device tab): only "seen in use" can be told, never "off"."""
    return [result("printer_agents", PASS) if svc.agent_seen else result("printer_agents", FAIL, "not_seen")]


def spoolman_check(svc):
    target = _target(svc)
    url = target.spoolman_url if target is not None else ""
    if not url:
        return [result("spoolman", OFF, "not_set")]
    try:
        svc._spoolman(target)
    except Exception as e:   # SpoolmanError keeps OrcaSlicer's refusal as its context
        if denied(e):
            return [result("spoolman", FAIL, "denied", str(e), "allow_spoolman")]
        return [result("spoolman", FAIL, "unreachable", str(e))]
    return [result("spoolman", PASS, detail=url)]


def cloud_check(svc):
    account = svc.cloud
    if account is None:
        return [result("cloud", OFF, "off")]
    if not account.signed_in:
        return [result("cloud", FAIL, "signed_out")]
    try:
        printers = svc.cmd_cloud_printers()
    except Exception as e:
        return [result("cloud", FAIL, "denied" if denied(e) else "unreachable", str(e))]
    return [result("cloud", PASS, detail=str(len(printers)))]


CHECKS = (printer_checks, certificate_check, printer_agents_check, spoolman_check, cloud_check)


def run(svc, checks=CHECKS, log=print):
    """Every check in turn; one that raises is a failure with its error, never the end of the list."""
    out = []
    for check in checks:
        try:
            out += check(svc)
        except Exception as e:
            log("kobracontrol: check %s failed (%r)" % (check.__name__, e))
            if check is printer_checks:   # both of its rows, so the list keeps its shape
                out += [result("printer", FAIL, "error", str(e)), result("login", FAIL, "needs_printer")]
            else:
                out.append(result(check.__name__.replace("_check", ""), FAIL, "error", str(e)))
    return sorted(out, key=lambda r: ORDER.index(r["id"]) if r["id"] in ORDER else len(ORDER))
