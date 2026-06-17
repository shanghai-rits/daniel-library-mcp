import csv
import io
from PIL import Image, ImageDraw
import os
import re
import difflib
from collections import deque

# Config: absolute path based on project root
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_FILE = os.path.join(BASE_DIR, 'locations.csv')

# A query "looks like a call number" when it is a Library of Congress style
# class (1-3 letters) optionally followed by a number, e.g. QA76, PN, B105.3.
CALL_NUMBER_RE = re.compile(r'^[A-Z]{1,3}\d')

# Corridor "spine" per floor: a small hand-authored graph of hallway waypoints
# (full-res pixel coords) connected by axis-aligned segments. There is no
# walkability map, so directions snap each location to its nearest waypoint and
# route along the spine -- this keeps the drawn path inside corridors instead of
# cutting diagonally through walls. Coordinates are starter values; calibrate
# them against the floor JPGs (e.g. via calibrate.html) and nudge as needed.
CORRIDORS = {
    "5F": {
        "map_file": "5f_base.jpg",
        "waypoints": {
            "ent": (3360, 805),     # at the Entrance & Exit
            "top_w": (1500, 805),   # west end of the top corridor
            "top_e": (5400, 805),   # east end of the top corridor
            "stair": (820, 900),    # near the 5F staircase
            "ww_top": (900, 1540),  # west wing, top
            "ww_mid": (700, 2228),  # west wing, middle (W508-W512 row)
            "ww_bot": (700, 3200),  # west wing, bottom
            "nrow": (3360, 1497),   # N51x classroom row
        },
        "edges": [
            ("ent", "top_w"), ("ent", "top_e"), ("ent", "nrow"),
            ("top_w", "stair"), ("top_w", "ww_top"),
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

    start -> nearest start waypoint -> spine waypoints -> nearest end waypoint
    -> end. Consecutive duplicate points are collapsed.
    """
    s_id, s_xy = _nearest_waypoint(floor, *start_xy)
    e_id, e_xy = _nearest_waypoint(floor, *end_xy)
    spine = _spine_route(floor, s_id, e_id)
    wps = CORRIDORS[floor]["waypoints"]

    pts = [start_xy, s_xy] + [wps[w] for w in spine[1:-1]] + [e_xy, end_xy]
    out = [pts[0]]
    for p in pts[1:]:
        if p != out[-1]:
            out.append(p)
    return out


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


def _stairs_on(floor):
    """Return the locations.csv row for the stairs on `floor`, or None.

    Stairs share the call id "STAIRS" on both floors, so resolution is by floor.
    """
    if not os.path.exists(DATA_FILE):
        return None
    with open(DATA_FILE, mode='r', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            if row['call_start'].upper() == 'STAIRS' and row['floor'] == floor:
                return row
    return None


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

    # Same floor: a single routed map.
    if s_floor == d_floor:
        pts = _path_points(s_floor, s_xy, d_xy)
        img = _draw_route(CORRIDORS[s_floor]["map_file"], pts)
        msg = (f"Directions from '{src['name']}' to '{dest['name']}' on the "
               f"{s_floor} floor. Green = start, red = destination.")
        return msg, [(s_floor, img)]

    # Cross floor: route start -> stairs, then stairs -> destination.
    s_stair = _stairs_on(s_floor)
    d_stair = _stairs_on(d_floor)
    if not s_stair or not d_stair:
        raise ValueError(
            f"No stairs defined for {s_floor}/{d_floor}; add a STAIRS row to locations.csv."
        )
    s_stair_xy = (int(s_stair['x']), int(s_stair['y']))
    d_stair_xy = (int(d_stair['x']), int(d_stair['y']))

    pts1 = _path_points(s_floor, s_xy, s_stair_xy)
    img1 = _draw_route(CORRIDORS[s_floor]["map_file"], pts1,
                       start_color="green", end_color="red")
    pts2 = _path_points(d_floor, d_stair_xy, d_xy)
    img2 = _draw_route(CORRIDORS[d_floor]["map_file"], pts2,
                       start_color="green", end_color="red")

    msg = (f"'{src['name']}' is on {s_floor} and '{dest['name']}' is on {d_floor}. "
           f"On {s_floor}, follow the route to the stairs/elevator (red marker). "
           f"Take them to {d_floor}, then follow the route from the stairs (green "
           f"marker) to your destination. Two maps are returned, one per floor.")
    return msg, [(s_floor, img1), (d_floor, img2)]
