from mcp.server.fastmcp import FastMCP
import os
import library

mcp = FastMCP("NYUSH_Library_Navigator", host="0.0.0.0", port=8000)

@mcp.tool()
def get_library_map(query: str) -> str:
    """
    Find the physical location of a room (e.g. 'N607') or a call number (e.g. 'QA76.5').
    Returns a description and the path to the generated map image.
    """
    try:
        result_msg, image_path = library.search_and_draw(query)
        full_path = os.path.abspath(image_path)
        return f"{result_msg} Map saved to: {full_path}"
    except Exception as e:
        return f"Query failed: {str(e)}"

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
