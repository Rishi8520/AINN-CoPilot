"""
Hexagonal 7-cell macro deployment.

Center cell (gNB0) surrounded by 6 cells at 60-degree spacing.
Inter-site distance (ISD) is configurable and defaults to a realistic
urban-macro value of 500 m (3GPP TR 38.901 urban macro reference ISD
range is 200-1732 m; 500 m is a common dense-urban assumption).
"""

import math
from typing import List, Dict


def build_hex_topology(isd_m: float = 500.0, center_x: float = 1000.0, center_y: float = 1000.0) -> List[Dict]:
    """
    Returns 7 gNB definitions: 1 center + 6 surrounding at distance ISD,
    spaced 60 degrees apart starting at 90 degrees (pointing "north").
    """
    gnbs = [
        {"id": 0, "x": center_x, "y": center_y, "role": "center"}
    ]

    for i in range(6):
        angle_deg = 90 + i * 60
        angle_rad = math.radians(angle_deg)
        x = center_x + isd_m * math.cos(angle_rad)
        y = center_y + isd_m * math.sin(angle_rad)
        gnbs.append({"id": i + 1, "x": round(x, 2), "y": round(y, 2), "role": "edge"})

    return gnbs


def distance(x1: float, y1: float, x2: float, y2: float) -> float:
    return math.hypot(x2 - x1, y2 - y1)


def neighbors_of(gnb_id: int, topology: List[Dict], k: int = 3) -> List[int]:
    """Return the k nearest neighboring gNB ids to gnb_id (used for handover target selection)."""
    me = next(g for g in topology if g["id"] == gnb_id)
    others = [g for g in topology if g["id"] != gnb_id]
    others.sort(key=lambda g: distance(me["x"], me["y"], g["x"], g["y"]))
    return [g["id"] for g in others[:k]]
