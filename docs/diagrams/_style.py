"""Shared settings for the architecture diagrams (diagrams-as-code).

Icons: AWS Architecture Icons, bundled by the `diagrams` library (MIT).
AWS permits their use in architecture diagrams.
"""

from pathlib import Path

OUT_DIR = Path(__file__).parent

GRAPH_ATTR = {
    "fontsize": "20",
    "fontname": "Helvetica",
    "pad": "0.4",
    "nodesep": "0.6",
    "ranksep": "0.9",
    "dpi": "110",
    # Curved edges keep labels attached to their arrows (ortho detaches them).
    "splines": "spline",
}
NODE_ATTR = {"fontsize": "12", "fontname": "Helvetica"}
EDGE_ATTR = {"fontsize": "11", "fontname": "Helvetica", "color": "#4a4a4a"}


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
