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


def directions_test():
    print("\n--- Testing directions ---")

    # 1. Same-floor: Entrance (5F) -> W522 (5F).
    msg, images = library.get_directions("W522")
    assert len(images) == 1, f"same-floor should be 1 image, got {len(images)}"
    assert images[0][0] == "5F" and len(images[0][1]) > 0
    assert "5F" in msg
    print(f"[ok] same-floor: {len(images)} image, {len(images[0][1])} bytes")

    # 2. Cross-floor: Entrance (5F) -> N607 (6F).
    msg, images = library.get_directions("N607")
    assert len(images) == 2, f"cross-floor should be 2 images, got {len(images)}"
    assert {f for f, _ in images} == {"5F", "6F"}
    assert "stairs" in msg.lower()
    print(f"[ok] cross-floor: {len(images)} images, floors {[f for f, _ in images]}")

    # 3. Explicit start, both 5F.
    msg, images = library.get_directions("N509", start="W516")
    assert len(images) == 1 and images[0][0] == "5F"
    print(f"[ok] explicit start W516 -> N509: {len(images)} image")

    # 4. Call-number destination still resolves via find_location.
    msg, images = library.get_directions("QA76")
    assert len(images) >= 1
    print(f"[ok] call-number dest QA76: {len(images)} image(s)")

    # 5. Errors raise ValueError.
    for bad in [("nonexistent", None), ("N607", "nonexistent")]:
        try:
            library.get_directions(bad[0], bad[1])
            raise AssertionError(f"expected ValueError for {bad}")
        except ValueError:
            pass
    print("[ok] unknown start/destination raise ValueError")

    # 6. Unit checks on the spine helpers.
    assert library._nearest_waypoint("5F", 3360, 805)[0] == "ent"
    route = library._spine_route("5F", "ww_bot", "top_e")
    for wp in ("ww_mid", "ww_top", "top_w", "ent"):
        assert wp in route, f"{wp} missing from spine route {route}"
    pts = library._path_points("5F", (3360, 805), (700, 3200))
    assert all(pts[i] != pts[i + 1] for i in range(len(pts) - 1)), "duplicate consecutive points"
    assert library._stairs_on("6F")["floor"] == "6F"
    print(f"[ok] unit checks: spine route {route}")

    print("All directions tests passed.")


if __name__ == "__main__":
    quick_test()
    directions_test()
