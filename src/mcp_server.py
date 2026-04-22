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


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
