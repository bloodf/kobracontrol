"""Spooler's stock in the Kobra Control tab: the list Spooler publishes, and linking one of its spools to a
slot. Every printer command still goes through kobracontrol's own service for the printer the page shows;
Spooler only supplies the list. Free of the `orca` module."""

import peers

STOCK_CHANGED = "Spooler's stock list changed since this one was shown; nothing was written. Pick the spool again."


def _int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _assign_args(slot, spool_id, key):
    if not _int(slot) or slot < 0:
        raise ValueError("no slot chosen")
    if not _int(spool_id) or spool_id <= 0:
        raise ValueError("no spool chosen")
    if not isinstance(key, str) or not key:
        raise ValueError(STOCK_CHANGED)
    return slot, spool_id, key


class StockMixin:
    """For service.Service: needs lock, bindings, spools, _snapshot() and _ctx() (both return a tuple whose last
    item is the target: .spoolman_url, .spoolman_report_usage; None without a printer), cmd_spools() (fills
    self.spools with spoolman.spool_view dicts from a fresh read) and cmd_bind_spool(slot, spool_id).
    `peers` is a peers.SpoolerLink, set by the plugin (None outside OrcaSlicer: no Spooler to find)."""

    peers = None

    def want_stock(self, refresh=False):
        if self.peers is not None:
            self.peers.want_stock(refresh)

    @staticmethod
    def _usage_owner(target):
        """Who records this printer's filament use in Spoolman, for the stock view's note: "kobracontrol", "off"
        (the setting), "spooler" (Spooler books it in the same Spoolman, so Kobra Control does not)."""
        if target is None:
            return "unknown"
        if target.spoolman_report_usage:
            return "kobracontrol"
        return "spooler" if getattr(target, "own_report_usage", False) else "off"

    @staticmethod
    def _origin_check(target, spooler_origin):
        """True: the Spoolman set here is Spooler's; False: a different one; None: can't tell; "fallback": none is
        set here, so Spooler's is used (the same one by construction, which is not a comparison)."""
        own = getattr(target, "own_spoolman_url", getattr(target, "spoolman_url", "")) if target is not None else ""
        if target is not None and not own and spooler_origin and target.spoolman_url:
            return "fallback"
        mine = peers.normalize_origin(own) if target else ""
        if not mine or not spooler_origin:
            return None
        return mine == spooler_origin

    def cmd_stock(self, refresh=False):
        """Spooler's state and stock list, with what this printer needs to use it."""
        if self.peers is None:
            spooler = {"state": "absent", "text": peers.STATE_TEXT["absent"], "detail": "", "version": "",
                       "session": "", "origin": ""}
            return {"spooler": spooler, "stock": {**peers.parse_stock(None, None), "state": "unavailable",
                                                  "text": spooler["text"]},
                    "same_spoolman": None, "usage": "unknown", "bindings": {}}
        self.want_stock(bool(refresh))
        target = self._snapshot()[-1]
        spooler, stock = self.peers.stock()
        with self.lock:
            bindings = {str(k): v for k, v in self.bindings.items()}
            by_spool = {v: k for k, v in sorted(self.bindings.items(), reverse=True)}   # lowest slot wins a tie
        stock = {**stock, "rows": [{**r, "bound_slot": by_spool.get(r["id"])} for r in stock["rows"]]}
        return {"spooler": {k: v for k, v in spooler.items() if k != "session"}, "stock": stock,
                "same_spoolman": self._origin_check(target, spooler["origin"]) if spooler["state"] == "active" else None,
                "usage": self._usage_owner(target), "bindings": bindings}

    def _current_row(self, key, spool_id):
        if self.peers is None:
            raise ValueError(peers.STATE_TEXT["absent"])
        spooler, stock = self.peers.stock()
        if spooler["state"] != "active":
            raise ValueError(spooler["text"])
        if stock["key"] != key:
            raise ValueError(STOCK_CHANGED)
        row = next((r for r in stock["rows"] if r["id"] == spool_id), None)
        if row is None:
            raise ValueError("Spool #%d is no longer in Spooler's stock list; nothing was written." % spool_id)
        return spooler, row

    def cmd_stock_assign(self, slot, spool_id, key):
        """Link a spool picked from Spooler's list to a slot of the printer this request was made for.
        Checked first: Spooler still runs with the list the page showed, both plugins use the same Spoolman,
        and kobracontrol's own Spoolman read finds that spool with the same filament. Then the normal bind."""
        slot, spool_id, key = _assign_args(slot, spool_id, key)
        target = self._ctx()[-1]
        spooler, row = self._current_row(key, spool_id)
        if self._origin_check(target, spooler["origin"]) is False:
            raise ValueError("Kobra Control's Spoolman (%s) isn't the one Spooler uses (%s); nothing was written. "
                             "Set the same Spoolman address in both." % (peers.normalize_origin(target.spoolman_url),
                                                                         spooler["origin"]))
        self.cmd_spools()   # kobracontrol's own, fresh read of the spool it will write
        with self.lock:
            mine = next((s for s in self.spools if s["id"] == spool_id), None)
        if mine is None:
            raise ValueError("Spool #%d isn't in the Spoolman Kobra Control reaches; nothing was written. "
                             "Do both plugins use the same Spoolman?" % spool_id)
        if row["filament_id"] is not None and mine.get("filament_id") != row["filament_id"]:
            raise ValueError("Spool #%d holds another filament in the Spoolman Kobra Control reaches than in "
                             "Spooler's list; nothing was written. Do both plugins use the same Spoolman?" % spool_id)
        self._current_row(key, spool_id)   # Spooler didn't restart or change source during the read
        return self.cmd_bind_spool(slot, spool_id)
