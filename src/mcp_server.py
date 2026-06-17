import base64

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, ImageContent, TextContent

import library

mcp = FastMCP("NYUSH_Library_Navigator", host="0.0.0.0", port=8000)


@mcp.tool()
def get_library_map(query: str) -> CallToolResult:
    """
    Find the physical location of a room (e.g. 'N607') or a call number (e.g. 'QA76.5').
    Returns a description and the generated map image.
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
    """
    Draw walking directions to a room or call number (e.g. 'N607', 'QA76.5').
    If `start` is omitted, directions begin at the library Entrance & Exit.
    Cross-floor trips (5F<->6F) route via the stairs and return one map per floor.
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
