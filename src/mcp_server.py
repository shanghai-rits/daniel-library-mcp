import base64

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, ImageContent, TextContent

import library

mcp = FastMCP("NYUSH_Library_Navigator", host="0.0.0.0", port=8000)


@mcp.tool()
def get_library_map(query: str) -> CallToolResult:
    """Show WHERE a single library location is by pinning it on the floor map.

    Use this when the user asks where something is and does NOT ask how to get
    there -- e.g. "Where is room N607?", "Which floor is the Scholars Space on?",
    "Find call number QA76.5", "Where are the PN books?". For step-by-step
    walking directions between two places, use get_library_directions instead.

    Args:
        query: A room name or number (e.g. 'N607', 'The Hub', 'IDRL'), a call
            number (e.g. 'QA76.5'), or a shelf range. Acronyms and minor typos
            are tolerated.

    Returns:
        A short text description plus one annotated floor-map image (JPEG) with
        a red marker on the location. Always show the returned image to the user.
    """
    try:
        result_msg, image_bytes = library.search_and_draw(query)
    except Exception as e:
        return CallToolResult(
            content=[TextContent(type="text", text=f"Query failed: {e}")],
            isError=True,
        )

    return CallToolResult(
        content=[
            TextContent(type="text", text=result_msg),
            ImageContent(
                type="image",
                data=base64.b64encode(image_bytes).decode("ascii"),
                mimeType="image/jpeg",
            ),
        ],
    )


@mcp.tool()
def get_library_directions(destination: str, start: str = None) -> CallToolResult:
    """Show HOW TO WALK to a place by drawing the route on the floor map.

    Use this whenever the user wants to get somewhere -- e.g. "How do I get to
    N607?", "Directions to the Scholars Space", "Take me from The Hub to the XR
    Space", "Where's QA76 and how do I walk there?". For simply showing where a
    place is (a single pin, no route), use get_library_map instead.

    The library occupies only the 5th floor (5F) and 6th floor (6F); the
    Entrance & Exit is ON 5F (there is no separate ground floor). Do NOT add a
    floor-change step on your own -- rely on the returned text: if it says the
    trip stays on one floor, there are no stairs or elevator; only a 5F<->6F
    trip involves a vertical connection.

    Args:
        destination: Where the user wants to go -- a room name/number, call
            number, or shelf (e.g. 'N607', 'XR Space', 'QA76.5'). Acronyms and
            minor typos are tolerated.
        start: Where the user is starting FROM. Pass this whenever the user
            states their current location (e.g. "I'm at the entrance", "from
            N509"). If omitted, the route begins at the library Entrance & Exit.

    Returns:
        Text directions plus annotated floor-map image(s) (JPEG) showing the
        route -- green marker = start, red marker = destination. A trip that
        stays on one floor returns ONE map. A trip between 5F and 6F returns TWO
        maps (one per floor) and routes via the nearest vertical connection --
        stairs or the elevator, chosen by proximity (use this for accessibility
        when the user needs the elevator). Always show every returned image, in
        order, to the user.
    """
    try:
        result_msg, images = library.get_directions(destination, start)
    except Exception as e:
        return CallToolResult(
            content=[TextContent(type="text", text=f"Directions failed: {e}")],
            isError=True,
        )

    content = [TextContent(type="text", text=result_msg)]
    for _floor, image_bytes in images:
        content.append(
            ImageContent(
                type="image",
                data=base64.b64encode(image_bytes).decode("ascii"),
                mimeType="image/jpeg",
            )
        )
    return CallToolResult(content=content)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
