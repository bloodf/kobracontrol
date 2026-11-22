"""What Kobra Control knows about each Anycubic FDM printer, keyed by the model code the printer reports (`modeId`
in the decrypted /ctrl answer, the second-to-last part of every MQTT topic). Data only. Free of `orca`.

Model codes: anycubic_ha_local const.py and Rinkhals tools.sh (both list 20021-20030). Bed sizes: Anycubic Slicer
Next's own machine profiles (printable_area / printable_height). Temperature maxima: Anycubic's published
specifications (store pages, wiki); the Kobra X keeps Kobralink's 320/120 (its profile sets none). The Kobra 2 limits
are the cloud's `temp_limit` for a Kobra 2 Pro (Bob-41's capture, docs/models.md).

  verified       a real printer of this model was driven by Kobra Control. Every other model is "experimental: needs
                 testers" in the page and the README: same LAN protocol by every public source, never tried here.
  feeder         "head+ace": the Kobra X head feeder box (-1) plus ACE units; "ace": ACE units only (ace.py works
                 out the layout from the reports; this is what to expect, for docs and tests).
  camera         "live": /live/<token> on the printer; "flv": :18088/flv (camera_url_for follows the printer's URL).
  lan            the stock firmware has the /info + /ctrl + MQTT LAN mode. False: cloud only (Kobra 2 series).
  single_client  the printer's MQTT broker takes one LAN client at a time (Kobra 3 / S1 family, Printer Tools and
                 anycubic_ha_local notes): a refused login means another app holds it, so retrying never helps.

A model code not listed here connects read-only: status and files, no heating, moving, feeding or printing."""

import re

FAMILY_LIMITS = {"nozzle_max": 300, "bed_max": 100}   # the page's limits before any printer answers

PROFILES = {
    "20030": dict(name="Anycubic Kobra X", nozzle_max=320, bed_max=120, bed=(260, 260, 260), feeder="head+ace",
                  camera="live", lan=True, single_client=False, verified=True),
    "20024": dict(name="Anycubic Kobra 3", nozzle_max=300, bed_max=110, bed=(255, 255, 260), feeder="ace",
                  camera="flv", lan=True, single_client=True, verified=False),
    "20027": dict(name="Anycubic Kobra 3 V2", nozzle_max=300, bed_max=110, bed=(255, 255, 260), feeder="ace",
                  camera="flv", lan=True, single_client=True, verified=False),
    "20026": dict(name="Anycubic Kobra 3 Max", nozzle_max=300, bed_max=90, bed=(426, 420, 501), feeder="ace",
                  camera="flv", lan=True, single_client=True, verified=False),
    "20025": dict(name="Anycubic Kobra S1", nozzle_max=320, bed_max=120, bed=(250, 250, 250), feeder="ace",
                  camera="flv", lan=True, single_client=True, verified=False),
    "20029": dict(name="Anycubic Kobra S1 Max", nozzle_max=350, bed_max=120, bed=(350, 350, 350), feeder="ace",
                  camera="flv", lan=True, single_client=True, verified=False),
    "20028": dict(name="Anycubic Kobra 4", nozzle_max=300, bed_max=100, bed=(260, 260, 260), feeder="ace",
                  camera="flv", lan=True, single_client=True, verified=False),
    "20021": dict(name="Anycubic Kobra 2 Pro", nozzle_max=260, bed_max=110, bed=(220, 220, 250), feeder="",
                  camera="", lan=False, single_client=False, verified=False),
    "20022": dict(name="Anycubic Kobra 2 Plus", nozzle_max=260, bed_max=110, bed=(320, 320, 400), feeder="",
                  camera="", lan=False, single_client=False, verified=False),
    "20023": dict(name="Anycubic Kobra 2 Max", nozzle_max=260, bed_max=110, bed=(426, 426, 500), feeder="",
                  camera="", lan=False, single_client=False, verified=False),
}

_SUFFIX = re.compile(r"\s*(\(.*\)|\d+(\.\d+)?\s*nozzle|combo)\s*$", re.I)


def get(mode_id):
    """The profile of a model code, None when unknown."""
    return PROFILES.get(str(mode_id or ""))


def key(name):
    """'Anycubic Kobra 3 V2 0.4 nozzle' -> 'kobra 3 v2': the comparable part of a model or preset name."""
    text = " ".join(str(name or "").replace("_", " ").replace("-", " ").split()).lower()
    text = re.sub(r"^anycubic\s*", "", text)
    while True:
        shorter = _SUFFIX.sub("", text)
        if shorter == text:
            return re.sub(r"kobra\s*(?=[a-z0-9])", "kobra ", text)
        text = shorter


def by_name(name):
    """(model code, profile) whose name matches a model or preset name, longest name first; (None, None)."""
    k = key(name)
    for mode_id, p in sorted(PROFILES.items(), key=lambda item: -len(item[1]["name"])):
        if k == key(p["name"]):
            return mode_id, p
    return None, None


def is_anycubic_lan(*values):
    """True when one of the values (printer_model, preset name, inherits) names a model this plugin reaches over the
    LAN, with or without "Anycubic", a nozzle size or "(user)" after it: 'Kobra S1 Max 0.4 nozzle', 'My Kobra 3'.
    A preset name may carry more words, so the profile name is searched as a whole word, longest first."""
    for v in values:
        k = key(v)
        for p in sorted(PROFILES.values(), key=lambda p: -len(p["name"])):
            if p["lan"] and re.search(r"(^|\W)%s($|\W)" % re.escape(key(p["name"])), k):
                return True
    return False


def same_model(file_model, mode_id, model=""):
    """A file sliced for `file_model` fits the printer (its model code, else its reported model name). Files that name
    no model, and printers Kobra Control has no profile for, are not second-guessed."""
    if not file_model:
        return True
    p = get(mode_id)
    name = p["name"] if p else model
    return not name or key(file_model) == key(name)


def limits(mode_id):
    """{"nozzle_max", "bed_max"} for a model; an unknown model gets nothing to heat to (it is read-only)."""
    p = get(mode_id)
    return {"nozzle_max": p["nozzle_max"], "bed_max": p["bed_max"]} if p else {"nozzle_max": 0, "bed_max": 0}


def describe(mode_id, model=""):
    """status.data `profile`: {"known", "verified", "name", "mode_id", "single_client"} for the page's notices."""
    p = get(mode_id)
    return {"known": bool(p and p["lan"]), "verified": bool(p and p["verified"]), "mode_id": str(mode_id or ""),
            "name": p["name"] if p else (model or ""), "single_client": bool(p and p["single_client"])}
