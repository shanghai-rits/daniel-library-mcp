import library


def quick_test():
    target = "Resercher"  # Replace with any name or call number from locations.csv
    print(f"--- Testing search: {target} ---")

    try:
        msg, image_bytes = library.search_and_draw(target)
        print(f"Success! Result: {msg}")
        print(f"Image bytes: {len(image_bytes)}")
    except Exception as e:
        print(f"Failed: {e}")


if __name__ == "__main__":
    quick_test()
