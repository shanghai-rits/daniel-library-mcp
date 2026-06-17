import csv
import io
import json
from PIL import Image, ImageDraw
import os
import re
import difflib
from collections import deque

# Config: absolute path based on project root
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_FILE = os.path.join(BASE_DIR, 'locations.csv')
CORRIDORS_FILE = os.path.join(BASE_DIR, 'corridors.json')

# A query "looks like a call number" when it is a Library of Congress style
# class (1-3 letters) optionally followed by a number, e.g. QA76, PN, B105.3.
CALL_NUMBER_RE = re.compile(r'^[A-Z]{1,3}\d')

# Corridor "spine" per floor: a graph of hallway waypoints (full-res pixel
# coords) connected by segments. There is no walkability map, so directions snap
# each location to its nearest waypoint and route along the spine -- this keeps
# the drawn path inside corridors instead of cutting diagonally through walls.
#
# The spine is authored visually in corridors.html and exported to corridors.json;
# load_corridors() reads that file at import. The dict below is only a fallback
# used when corridors.json is missing or unreadable.
_FALLBACK_CORRIDORS = {
    "5F": {
        "map_file": "5f_base.jpg",
        "waypoints": {
            "ent": (4065, 805),     # top corridor, above the Entrance & Exit door
            "top_w": (1500, 805),   # west end of the top corridor
            "top_e": (5400, 805),   # east end of the top corridor
            "ww_top": (300, 1540),  # west wing, top of the left-edge corridor
            "ww_mid": (300, 2500),  # west wing, middle (W508-W517 column)
            "ww_bot": (300, 3700),  # west wing, bottom (W518/W522 row)
            "nrow": (3360, 1497),   # N51x classroom row
        },
        "edges": [
            ("ent", "top_w"), ("ent", "top_e"), ("ent", "nrow"),
            ("top_w", "ww_top"),
            ("ww_top", "ww_mid"), ("ww_mid", "ww_bot"),
        ],
    },
    "6F": {
        "map_file": "6f_base.jpg",
        "waypoints": {
            "stair": (770, 900),       # near the 6F staircase
            "main": (4000, 900),       # central main-collection corridor
            "gsr": (3100, 1483),       # group study room row (N601-N605)
            "scholars": (6400, 700),   # east wing toward Scholars Space
        },
        "edges": [
            ("stair", "main"), ("main", "gsr"), ("main", "scholars"),
        ],
    },
}


def load_corridors():
    """Load the corridor spine from corridors.json, falling back to the inline
    dict if the file is missing or malformed.

    JSON shape: {"5F": {"map_file": ..., "waypoints": {id: [x, y]}, "edges": [[a, b]]}}.
    Waypoint values may be [x, y] lists or {x, y} dicts; both normalize to tuples.
    """
    if not os.path.exists(CORRIDORS_FILE):
        return _FALLBACK_CORRIDORS
    try:
        with open(CORRIDORS_FILE, encoding='utf-8') as f:
            raw = json.load(f)
    except (ValueError, OSError):
        return _FALLBACK_CORRIDORS

    out = {}
    for floor, info in raw.items():
        wps = {}
        for wid, v in info.get('waypoints', {}).items():
            wps[wid] = (v['x'], v['y']) if isinstance(v, dict) else (v[0], v[1])
        out[floor] = {
            'map_file': info['map_file'],
            'waypoints': wps,
            'edges': [(a, b) for a, b in info.get('edges', [])],
        }
    return out or _FALLBACK_CORRIDORS


CORRIDORS = load_corridors()


def _acronym(name):
    """Build an acronym from the significant words of a room name.

    "Interdisciplinary Digital Research Lab (N507)" -> "IDRL".
    Parenthetical room codes and short filler words are ignored so the
    acronym reflects how patrons actually abbreviate the room.
    """
    stripped = re.sub(r'\(.*?\)', ' ', name)
    skip = {'OF', 'THE', 'AND', 'FOR', 'A', 'AN'}
    letters = [w[0] for w in stripped.split() if w and w.upper() not in skip]
    return ''.join(letters).upper()


def _call_key(call):
    """Split a call number into (letters, number) for ordered comparison.

    String comparison alone misorders call numbers ("A100" < "A9"), so we
    compare the alphabetic class first, then the numeric portion.
    """
    m = re.match(r'^([A-Z]+)\s*(\d*(?:\.\d+)?)', call.upper())
    if not m:
        return (call.upper(), 0.0)
    letters, num = m.group(1), m.group(2)
    return (letters, float(num) if num else 0.0)


def find_location(query):
    query = query.strip().upper()
    if not os.path.exists(DATA_FILE):
        return None

    with open(DATA_FILE, mode='r', encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))

    # Transit rows (stairs/elevator) are routing infrastructure, not lookup
    # targets -- exclude them so a query never resolves to a stairwell.
    rows = [r for r in rows if r['type'].lower() != 'transit']

    best_match = None
    highest_score = 0

    for row in rows:
        name = row['name'].upper()
        call_id = row['call_start'].upper()

        # --- Strategy 1: Exact substring match (highest priority) ---
        if query in name or query in call_id:
            return row

        # --- Strategy 2: Acronym match (e.g. "IDRL" -> full lab name) ---
        if len(query) >= 2 and query == _acronym(name):
            return row

        # --- Strategy 3: Fuzzy matching (handles typos) ---
        # Match against individual words in the name, e.g. split "Researcher Room (N607)"
        words = name.replace('(', ' ').replace(')', ' ').split()
        words.append(call_id)

        for word in words:
            score = difflib.SequenceMatcher(None, query, word).ratio()
            if score > highest_score:
                highest_score = score
                best_match = row

    # Threshold of 0.7 to avoid false matches
    if highest_score > 0.7:
        return best_match

    # --- Strategy 4: Call number range ---
    # Only attempt this when the query actually looks like a call number.
    # Otherwise an unrelated query (e.g. "printer") would land inside some
    # shelf's alphabetic range and wrongly resolve to that shelf.
    if CALL_NUMBER_RE.match(query):
        qkey = _call_key(query)
        for row in rows:
            if row['type'].lower() == 'shelf':
                if _call_key(row['call_start']) <= qkey <= _call_key(row['call_end']):
                    return row

    return None


def search_and_draw(query):
    """
    Main entry point: pin the location on the full floor map and return the
    annotated image as JPEG bytes along with a human-readable description.
    """
    location = find_location(query)
    if not location:
        raise ValueError(f"Location not found for '{query}'.")

    try:
        x, y = int(location['x']), int(location['y'])
        base_map_path = os.path.join(BASE_DIR, location['map_file'])

        if not os.path.exists(base_map_path):
            raise FileNotFoundError(f"Base map {base_map_path} not found. Please check the filename.")

        img = Image.open(base_map_path)
        if img.mode != "RGB":
            img = img.convert("RGB")
        draw = ImageDraw.Draw(img)

        # Draw a prominent marker on the full map
        radius = 60
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill="red", outline="white", width=15)
        draw.ellipse((x - 15, y - 15, x + 15, y + 15), fill="white")

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        image_bytes = buf.getvalue()

        msg = f"'{location['name']}' has been marked on the {location['floor']} floor map."
        return msg, image_bytes

    except Exception as e:
        raise Exception(f"Failed to generate map: {str(e)}")


# --- Path finding / directions -------------------------------------------------

def _nearest_waypoint(floor, x, y):
    """Return (waypoint_id, (wx, wy)) on `floor` nearest to (x, y).

    Used to snap an arbitrary location onto the corridor spine.
    """
    wps = CORRIDORS[floor]["waypoints"]
    best_id, best_xy = min(
        wps.items(),
        key=lambda kv: (kv[1][0] - x) ** 2 + (kv[1][1] - y) ** 2,
    )
    return best_id, best_xy


def _project_to_segment(p, a, b):
    """Project point `p` onto segment a-b. Return (point_on_segment, dist2, t).

    `t` is the clamped parameter in [0, 1] (0 = at a, 1 = at b). Lets a route
    branch off a corridor at the closest point on an edge, not only at a node.
    """
    px, py = p
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    seg2 = dx * dx + dy * dy
    if seg2 == 0:
        t = 0.0
    else:
        t = ((px - ax) * dx + (py - ay) * dy) / seg2
        t = max(0.0, min(1.0, t))
    qx, qy = ax + t * dx, ay + t * dy
    return (qx, qy), (px - qx) ** 2 + (py - qy) ** 2, t


def _nearest_on_spine(floor, x, y):
    """Snap (x, y) to the nearest point on any corridor edge.

    Returns (edge, point, t): the (a, b) edge it landed on, the projected
    point, and the parameter t along it. Falls back to the nearest waypoint
    (as a degenerate edge) when the floor has no edges.
    """
    wps = CORRIDORS[floor]["waypoints"]
    edges = CORRIDORS[floor]["edges"]
    best = None
    for a, b in edges:
        if a not in wps or b not in wps:
            continue
        point, dist2, t = _project_to_segment((x, y), wps[a], wps[b])
        if best is None or dist2 < best[0]:
            best = (dist2, (a, b), point, t)
    if best is None:
        wid, wxy = _nearest_waypoint(floor, x, y)
        return (wid, wid), wxy, 0.0
    return best[1], best[2], best[3]


def _spine_route(floor, start_wp, end_wp):
    """Return the list of waypoint ids from `start_wp` to `end_wp` (inclusive).

    BFS over the floor's edge adjacency. The spine is a small near-tree, so the
    breadth-first path is the natural hallway route. Falls back to a direct
    [start, end] hop if the graph is disconnected for that pair.
    """
    if start_wp == end_wp:
        return [start_wp]

    adj = {}
    for a, b in CORRIDORS[floor]["edges"]:
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)

    queue = deque([start_wp])
    prev = {start_wp: None}
    while queue:
        node = queue.popleft()
        if node == end_wp:
            break
        for nxt in adj.get(node, []):
            if nxt not in prev:
                prev[nxt] = node
                queue.append(nxt)

    if end_wp not in prev:
        return [start_wp, end_wp]

    path, node = [], end_wp
    while node is not None:
        path.append(node)
        node = prev[node]
    return path[::-1]


def _path_points(floor, start_xy, end_xy):
    """Build the full route polyline on a single floor.

    Each endpoint branches off the spine at the closest point on its nearest
    *edge* (not the nearest node), so a route leaves the corridor right next to
    the room instead of detouring to the nearest waypoint. The two branch points
    are inserted as temporary nodes that split their host edges, and BFS over the
    augmented graph yields the hallway route between them. Consecutive duplicate
    points are collapsed.
    """
    wps = dict(CORRIDORS[floor]["waypoints"])
    edges = list(CORRIDORS[floor]["edges"])

    (sa, sb), s_proj, _ = _nearest_on_spine(floor, *start_xy)
    (ea, eb), e_proj, _ = _nearest_on_spine(floor, *end_xy)

    # Insert each branch point as a temporary node splitting its host edge.
    def split_edge(edge, point, node_id):
        a, b = edge
        wps[node_id] = point
        if a == b:                       # degenerate (no-edge fallback)
            edges.append((node_id, a))
            return
        if (a, b) in edges:
            edges.remove((a, b))
        elif (b, a) in edges:
            edges.remove((b, a))
        edges.extend([(a, node_id), (node_id, b)])

    split_edge((sa, sb), s_proj, "__start__")
    end_anchor = "__end__"
    if (ea, eb) == (sa, sb):
        # Both branch onto the same edge -- route directly between the two
        # projections without splitting twice.
        wps[end_anchor] = e_proj
        edges.append(("__start__", end_anchor))
    else:
        split_edge((ea, eb), e_proj, end_anchor)

    route = _spine_route_on(wps, edges, "__start__", end_anchor)
    pts = [start_xy] + [wps[w] for w in route] + [end_xy]

    out = [pts[0]]
    for p in pts[1:]:
        if p != out[-1]:
            out.append(p)
    return out


def _spine_route_on(wps, edges, start_wp, end_wp):
    """BFS over an explicit (waypoints, edges) graph; returns the id path.

    Like _spine_route but operates on a caller-supplied graph so temporary
    branch nodes can be routed through. Falls back to a direct hop if
    disconnected.
    """
    if start_wp == end_wp:
        return [start_wp]
    adj = {}
    for a, b in edges:
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    queue = deque([start_wp])
    prev = {start_wp: None}
    while queue:
        node = queue.popleft()
        if node == end_wp:
            break
        for nxt in adj.get(node, []):
            if nxt not in prev:
                prev[nxt] = node
                queue.append(nxt)
    if end_wp not in prev:
        return [start_wp, end_wp]
    path, node = [], end_wp
    while node is not None:
        path.append(node)
        node = prev[node]
    return path[::-1]


def _draw_route(map_file, points, start_color="green", end_color="red"):
    """Open `map_file`, draw the route polyline + endpoint markers, return JPEG.

    The polyline is drawn twice -- a wide white casing then a narrower blue core
    -- so it stays legible over a busy, light-colored floor plan. Endpoint
    markers reuse the ellipse geometry from search_and_draw().
    """
    base_map_path = os.path.join(BASE_DIR, map_file)
    if not os.path.exists(base_map_path):
        raise FileNotFoundError(f"Base map {base_map_path} not found. Please check the filename.")

    img = Image.open(base_map_path)
    if img.mode != "RGB":
        img = img.convert("RGB")
    draw = ImageDraw.Draw(img)

    if len(points) >= 2:
        draw.line(points, fill="white", width=34, joint="curve")
        draw.line(points, fill="#1E6FFF", width=18, joint="curve")

    radius = 60
    sx, sy = points[0]
    ex, ey = points[-1]
    draw.ellipse((sx - radius, sy - radius, sx + radius, sy + radius),
                 fill=start_color, outline="white", width=15)
    draw.ellipse((ex - radius, ey - radius, ex + radius, ey + radius),
                 fill=end_color, outline="white", width=15)
    draw.ellipse((ex - 15, ey - 15, ex + 15, ey + 15), fill="white")

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _transit_options(floor):
    """Return the list of inter-floor transit rows (stairs/elevator) on `floor`.

    Transit points are tagged type=Transit in locations.csv and paired across
    floors by their call id (e.g. STAIRS_CENTRAL, ELEVATOR).
    """
    if not os.path.exists(DATA_FILE):
        return []
    with open(DATA_FILE, mode='r', encoding='utf-8-sig') as f:
        return [r for r in csv.DictReader(f)
                if r['type'].lower() == 'transit' and r['floor'] == floor]


def _nearest_transit(from_floor, to_floor, x, y):
    """Pick the transit structure (stairs/elevator) nearest (x, y) on
    `from_floor`, returning (from_row, to_row) for the same structure on the
    destination floor. Returns (None, None) if none is available on both floors.
    """
    starts = _transit_options(from_floor)
    ends = {r['call_start']: r for r in _transit_options(to_floor)}
    candidates = [(s, ends[s['call_start']]) for s in starts if s['call_start'] in ends]
    if not candidates:
        return None, None
    return min(
        candidates,
        key=lambda pair: (int(pair[0]['x']) - x) ** 2 + (int(pair[0]['y']) - y) ** 2,
    )


def get_directions(destination, start=None):
    """Generate walking directions and return (text_msg, [(floor, jpeg_bytes), ...]).

    `start` defaults to the library Entrance & Exit. Same-floor trips return one
    annotated map; cross-floor trips route via the stairs and return one map per
    floor. Raises ValueError if either endpoint cannot be resolved.
    """
    dest = find_location(destination)
    if not dest:
        raise ValueError(f"Destination not found for '{destination}'.")

    if start:
        src = find_location(start)
        if not src:
            raise ValueError(f"Start not found for '{start}'.")
    else:
        src = find_location("Entrance")
        if not src:
            raise ValueError("Default start 'Entrance & Exit' not found in locations.csv.")

    s_floor, d_floor = src['floor'], dest['floor']
    s_xy = (int(src['x']), int(src['y']))
    d_xy = (int(dest['x']), int(dest['y']))

    # Already there.
    if src['name'] == dest['name']:
        img = _draw_route(CORRIDORS[d_floor]["map_file"], [d_xy, d_xy],
                          start_color="red", end_color="red")
        msg = f"You're already at '{dest['name']}' on the {d_floor} floor."
        return msg, [(d_floor, img)]

    # Same floor: a single routed map. State plainly that the trip stays on one
    # floor so the answer never invents a stairs/elevator step.
    if s_floor == d_floor:
        pts = _path_points(s_floor, s_xy, d_xy)
        img = _draw_route(CORRIDORS[s_floor]["map_file"], pts)
        msg = (f"'{src['name']}' and '{dest['name']}' are both on the {s_floor} "
               f"floor, so this is a single-floor walk -- no stairs or elevator "
               f"and no floor change are needed. Follow the route on the {s_floor} "
               f"map: green marker = start, red marker = destination.")
        return msg, [(s_floor, img)]

    # Cross floor: route start -> nearest transit, then transit -> destination.
    # The transit structure (stairs/elevator) is chosen by distance from the
    # start, and the SAME structure is used to arrive on the destination floor.
    s_transit, d_transit = _nearest_transit(s_floor, d_floor, *s_xy)
    if not s_transit:
        raise ValueError(
            f"No transit (stairs/elevator) defined between {s_floor} and {d_floor}; "
            f"add Transit rows to locations.csv."
        )
    transit_name = s_transit['name']
    s_transit_xy = (int(s_transit['x']), int(s_transit['y']))
    d_transit_xy = (int(d_transit['x']), int(d_transit['y']))

    pts1 = _path_points(s_floor, s_xy, s_transit_xy)
    img1 = _draw_route(CORRIDORS[s_floor]["map_file"], pts1,
                       start_color="green", end_color="red")
    pts2 = _path_points(d_floor, d_transit_xy, d_xy)
    img2 = _draw_route(CORRIDORS[d_floor]["map_file"], pts2,
                       start_color="green", end_color="red")

    msg = (f"'{src['name']}' is on {s_floor} and '{dest['name']}' is on {d_floor}. "
           f"On {s_floor}, follow the route to the {transit_name} (red marker). "
           f"Take the {transit_name} to {d_floor}, then follow the route from there "
           f"(green marker) to your destination. Two maps are returned, one per floor.")
    return msg, [(s_floor, img1), (d_floor, img2)]
