"""Shared settings for the architecture diagrams (diagrams-as-code).

Icons: AWS Architecture Icons, bundled by the `diagrams` library (MIT).
AWS permits their use in architecture diagrams.
"""

from pathlib import Path

import diagrams

ICON_IN = 1.4  # the library's fixed node width; icons scale to it
LINE_IN = 0.2  # height of one 12 pt label line, in inches

def _tighten(attrs: dict, label: str) -> None:
    """Size icon nodes to icon + label so arrows land on the icon or its label.

    diagrams 0.25.1 pads every node by 0.4 in per label line, which leaves blank space
    between icon and label; arrows ending there look like they point at nothing.
    """
    if "image" in attrs and "height" in attrs:
        lines = label.count("\n") + 1 if label else 0
        attrs["height"] = f"{ICON_IN + 0.1 + LINE_IN * lines:.2f}"


def _patch(cls) -> None:
    """Nodes are created by Diagram.node, or by Cluster.node inside a cluster."""
    original = cls.node

    def node(self, nodeid: str, label: str, **attrs) -> None:
        _tighten(attrs, label)
        original(self, nodeid, label, **attrs)

    cls.node = node


_patch(diagrams.Diagram)
_patch(diagrams.Cluster)

OUT_DIR = Path(__file__).parent

GRAPH_ATTR = {
    "fontsize": "20",
    "fontname": "Helvetica",
    "pad": "0.4",
    "nodesep": "0.6",
    "ranksep": "1.1",
    "dpi": "110",
    # Curved edges keep labels attached to their arrows (ortho detaches them).
    "splines": "spline",
}
# Icons sit at the top of each node box so arrows land on the icon, not on blank space
# (the library makes node boxes taller than their icons to fit the label underneath).
NODE_ATTR = {"fontsize": "12", "fontname": "Helvetica", "imagepos": "tc"}
EDGE_ATTR = {"fontsize": "11", "fontname": "Helvetica", "color": "#4a4a4a", "penwidth": "1.3"}


def diagram_kwargs(name: str, title: str, direction: str = "LR") -> dict:
    """Common keyword arguments for diagrams.Diagram; writes <name>.png here."""
    return {
        "name": title,
        "filename": str(OUT_DIR / name),
        "outformat": "png",
        "show": False,
        "direction": direction,
        "graph_attr": GRAPH_ATTR,
        "node_attr": NODE_ATTR,
        "edge_attr": EDGE_ATTR,
    }
