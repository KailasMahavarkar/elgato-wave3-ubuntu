"""Deck view: large quick-action tiles for use mid-stream."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from . import deck  # noqa: E402
from . import layout  # noqa: E402

# Every group wraps at the same column count, otherwise groups with different
# item counts flow to different widths and the deck's right edge goes ragged.
MAX_COLUMNS = 4
REFRESH_MS = 250
SHORTCUT_KEYS = "1234567890"


class Tile(Gtk.Button):
    """One quick action, rendered as a large tile."""

    def __init__(self, action, index):
        super().__init__()
        self.action = action
        self.add_css_class("deck-tile")
        if action.kind == deck.DANGER:
            self.add_css_class("danger")
        self.set_tooltip_text(action.tooltip or action.label)
        self.set_hexpand(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_valign(Gtk.Align.CENTER)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.shortcut = Gtk.Label(
            label=SHORTCUT_KEYS[index] if index < len(SHORTCUT_KEYS) else ""
        )
        self.shortcut.add_css_class("tile-shortcut")
        self.shortcut.set_xalign(0)
        self.shortcut.set_hexpand(True)
        top.append(self.shortcut)
        box.append(top)

        self.icon = Gtk.Image.new_from_icon_name(action.icon)
        self.icon.set_pixel_size(26)
        self.icon.add_css_class("tile-icon")
        box.append(self.icon)

        self.label = Gtk.Label(label=action.label)
        self.label.add_css_class("tile-label")
        self.label.set_ellipsize(3)
        box.append(self.label)

        self.state = Gtk.Label(label="")
        self.state.add_css_class("tile-state")
        box.append(self.state)

        self.set_child(box)
        self.connect("clicked", self._clicked)
        self.refresh()

    def _clicked(self, _b):
        if not self.action.enabled():
            return
        self.action.toggle()
        self.refresh()

    def refresh(self):
        available = self.action.enabled()
        active = self.action.active() if available else False

        self.set_sensitive(available)
        # Third line always spells the state, so colour is never the only cue.
        self.state.set_text(
            self.action.on_word if active else self.action.off_word
        )
        if active:
            self.add_css_class("engaged")
        else:
            self.remove_css_class("engaged")


class DeckPage(Gtk.Box):
    def __init__(self, actions):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.tiles = []
        self._refresh_source = None

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)

        clamp = Adw.Clamp(maximum_size=layout.CONTENT_WIDTH,
                          tightening_threshold=layout.TIGHTENING)
        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        column.set_margin_top(20)
        column.set_margin_bottom(20)
        column.set_margin_start(18)
        column.set_margin_end(18)

        index = 0
        for group in (deck.MIC, deck.EFFECTS, deck.STREAM):
            members = [a for a in actions if a.group == group]
            if not members:
                continue

            heading = Gtk.Label(label=group.upper())
            heading.add_css_class("section-heading")
            heading.set_xalign(0)
            column.append(heading)

            # FlowBox rather than a fixed grid so the deck reflows to width.
            grid = Gtk.FlowBox()
            grid.set_selection_mode(Gtk.SelectionMode.NONE)
            grid.set_homogeneous(True)
            grid.set_min_children_per_line(2)
            grid.set_max_children_per_line(MAX_COLUMNS)
            grid.set_column_spacing(10)
            grid.set_row_spacing(10)
            for action in members:
                tile = Tile(action, index)
                index += 1
                self.tiles.append(tile)
                child = Gtk.FlowBoxChild()
                child.set_child(tile)
                child.set_focusable(False)
                grid.append(child)
            column.append(grid)

        clamp.set_child(column)
        scroller.set_child(clamp)
        self.append(scroller)

        self._keys = None
        self.connect("map", self._on_map)
        self.connect("unmap", self._on_unmap)

    def _key_pressed(self, _c, keyval, _code, state):
        # Ignore modified presses so Alt+1 style window shortcuts still work.
        if state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK):
            return False
        name = Gdk.keyval_name(keyval) or ""
        if len(name) != 1 or name not in SHORTCUT_KEYS:
            return False
        position = SHORTCUT_KEYS.index(name)
        if position >= len(self.tiles):
            return False
        tile = self.tiles[position]
        if not tile.get_sensitive():
            # Let the key fall through rather than swallowing it.
            return False
        tile.action.toggle()
        self.refresh()
        return True

    def _on_map(self, *_a):
        self.refresh()
        if self._refresh_source is None:
            self._refresh_source = GLib.timeout_add(REFRESH_MS, self._tick)

        # The controller lives on the window, not on this box: after a view
        # switch focus is still on the switcher button, so a controller
        # attached here would not see the press until a tile was clicked.
        root = self.get_root()
        if root is not None and self._keys is None:
            self._keys = Gtk.EventControllerKey()
            self._keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
            self._keys.connect("key-pressed", self._key_pressed)
            root.add_controller(self._keys)

    def _on_unmap(self, *_a):
        if self._refresh_source is not None:
            GLib.source_remove(self._refresh_source)
            self._refresh_source = None
        # Shortcuts must not stay live while another view is showing.
        root = self.get_root()
        if root is not None and self._keys is not None:
            root.remove_controller(self._keys)
        self._keys = None

    def _tick(self):
        self.refresh()
        return True

    def refresh(self):
        for tile in self.tiles:
            tile.refresh()
