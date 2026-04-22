import csv
import io
from PIL import Image, ImageDraw
import os
import difflib

# Config: absolute path based on project root
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_FILE = os.path.join(BASE_DIR, 'locations.csv')

def find_location(query):
    query = query.strip().upper()
    if not os.path.exists(DATA_FILE): return None

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

        # --- Strategy 2: Fuzzy matching (handles typos) ---
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

    # --- Strategy 3: Call number range ---
    for row in rows:
        if row['type'].lower() == 'shelf':
            if row['call_start'].upper() <= query <= row['call_end'].upper():
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
