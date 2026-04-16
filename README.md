# NYUSH Library Visual Navigator

A specialized visual grounding tool designed to enhance the NYU Shanghai Library AI Chatbot.

## The Problem
Currently, the library chatbot provides text-based answers. However, patrons often struggle to find physical locations (rooms and bookshelves) using text alone.

## The Solution
This project bridges the gap by:
- Mapping **Room Names** (e.g., N607) to floor plan coordinates.
- Using a range-based algorithm to locate **Library of Congress Call Numbers** (e.g., QA76).
- Generating a **Visual Map** with a pinpoint to guide patrons instantly.

## Tech Stack
- **Language**: Python (Pillow for image processing)
- **Architecture**: Designed for **MCP (Model Context Protocol)** integration.
- **Maintenance**: Includes a web-based Calibration Tool for easy coordinate updates.

## Roadmap
- [ ] Integration with official Chatbot via MCP Server.
- [ ] Mobile-friendly auto-cropping for generated maps.
- [ ] Real-time emergency status updates (e.g., floor closures).
