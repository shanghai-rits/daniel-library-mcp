import csv
import io
from PIL import Image, ImageDraw
import os
import re
import difflib

# Config: absolute path based on project root
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_FILE = os.path.join(BASE_DIR, 'locations.csv')

# A query "looks like a call number" when it is a Library of Congress style
# class (1-3 letters) optionally followed by a number, e.g. QA76, PN, B105.3.
CALL_NUMBER_RE = re.compile(r'^[A-Z]{1,3}\d')


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
