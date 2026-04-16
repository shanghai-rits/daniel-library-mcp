import library
import os

def quick_test():
    target = "Resercher"  # Replace with any name or call number from locations.csv
    print(f"--- Testing search: {target} ---")

    try:
        msg, img_path = library.search_and_draw(target)
        print(f"Success! Result: {msg}")
        print(f"Map path: {os.path.abspath(img_path)}")

        # Auto-open the generated map
        if os.name == 'nt': os.startfile(img_path)
        else: os.system(f"open '{img_path}'")
    except Exception as e:
        print(f"Failed: {e}")

if __name__ == "__main__":
    quick_test()
