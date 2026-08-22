"""Regenerate src/raster_pygame_fixtures.rs from the installed pygame-ce.

Each fixture draws one primitive in white on a small black surface via real
pygame and records the lit-pixel set; raster.rs unit tests assert bit parity.

    uv run python engine/necore/gen_fixtures.py
"""
import os
import pathlib

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pygame  # noqa: E402

pygame.init()

OUT = pathlib.Path(__file__).parent / "src" / "raster_pygame_fixtures.rs"
W = (255, 255, 255)
fixtures = []


def mask(surf):
    w, h = surf.get_size()
    return [(x, y) for y in range(h) for x in range(w)
            if surf.get_at((x, y))[:3] != (0, 0, 0)]


def fx(name, size, draw_fn):
    s = pygame.Surface(size)
    s.fill((0, 0, 0))
    draw_fn(s)
    fixtures.append((name, size, mask(s)))


# triangles (filltri path: exactly 3 points)
fx("tri_basic", (12, 12), lambda s: pygame.draw.polygon(s, W, [(2, 2), (9, 3), (4, 9)]))
fx("tri_flat_top", (12, 12), lambda s: pygame.draw.polygon(s, W, [(2, 2), (8, 2), (5, 8)]))
fx("tri_sliver", (16, 8), lambda s: pygame.draw.polygon(s, W, [(1, 2), (14, 3), (1, 4)]))
fx("tri_degen_vline", (8, 8), lambda s: pygame.draw.polygon(s, W, [(3, 1), (3, 5), (6, 3)]))

# fillpoly path (>3 points)
fx("quad_square", (10, 10), lambda s: pygame.draw.polygon(s, W, [(2, 2), (7, 2), (7, 7), (2, 7)]))
fx("quad_diamond", (12, 12), lambda s: pygame.draw.polygon(s, W, [(5, 1), (10, 5), (5, 10), (1, 5)]))
fx("poly_concave", (14, 14), lambda s: pygame.draw.polygon(s, W, [(2, 2), (11, 2), (11, 11), (7, 6), (2, 11)]))
fx("poly_horiz_bottom_notch", (14, 10),
   lambda s: pygame.draw.polygon(s, W, [(1, 1), (12, 1), (12, 8), (8, 8), (8, 4), (5, 4), (5, 8), (1, 8)]))
# CW winding (chirality-flipped portals produce CW polys)
fx("quad_square_cw", (10, 10), lambda s: pygame.draw.polygon(s, W, [(2, 2), (2, 7), (7, 7), (7, 2)]))

# thin lines
fx("line_h", (10, 6), lambda s: pygame.draw.line(s, W, (1, 2), (8, 2), 1))
fx("line_v", (6, 10), lambda s: pygame.draw.line(s, W, (2, 1), (2, 8), 1))
fx("line_diag", (10, 10), lambda s: pygame.draw.line(s, W, (1, 1), (8, 6), 1))
fx("line_diag_rev", (10, 10), lambda s: pygame.draw.line(s, W, (8, 6), (1, 1), 1))
fx("line_steep", (8, 12), lambda s: pygame.draw.line(s, W, (2, 1), (5, 10), 1))
fx("line_point", (5, 5), lambda s: pygame.draw.line(s, W, (2, 2), (2, 2), 1))
fx("line_offscreen", (6, 6), lambda s: pygame.draw.line(s, W, (-3, -2), (8, 4), 1))

# thick lines (walls w=2, doors w=3; w=4 pins the even-width asymmetry)
fx("line_w2_h", (12, 8), lambda s: pygame.draw.line(s, W, (2, 3), (9, 3), 2))
fx("line_w2_diag", (12, 12), lambda s: pygame.draw.line(s, W, (2, 2), (9, 8), 2))
fx("line_w3_diag", (12, 12), lambda s: pygame.draw.line(s, W, (2, 2), (9, 8), 3))
fx("line_w3_v", (8, 12), lambda s: pygame.draw.line(s, W, (4, 2), (4, 9), 3))
fx("line_w2_steep", (10, 14), lambda s: pygame.draw.line(s, W, (3, 1), (6, 12), 2))
fx("line_w2_v", (8, 12), lambda s: pygame.draw.line(s, W, (4, 2), (4, 9), 2))
fx("line_w4_h", (12, 10), lambda s: pygame.draw.line(s, W, (2, 4), (9, 4), 4))

# polyline (open) and closed outline via polygon(width)
fx("lines_open_w1", (14, 12), lambda s: pygame.draw.lines(s, W, False, [(1, 1), (8, 3), (11, 9)], 1))
fx("lines_open_w2", (14, 12), lambda s: pygame.draw.lines(s, W, False, [(1, 1), (8, 3), (11, 9)], 2))
fx("poly_outline_w1", (12, 12), lambda s: pygame.draw.polygon(s, W, [(2, 2), (9, 3), (4, 9)], 1))
fx("poly_outline_w2", (14, 14), lambda s: pygame.draw.polygon(s, W, [(2, 2), (11, 3), (5, 11)], 2))

# circles fill + thin outline
for r in [1, 2, 3, 4, 5, 6, 10]:
    fx(f"circle_fill_r{r}", (2 * r + 6, 2 * r + 6),
       lambda s, r=r: pygame.draw.circle(s, W, (r + 3, r + 3), r))
for r in [1, 2, 3, 4, 5, 6, 10]:
    fx(f"circle_thin_r{r}", (2 * r + 6, 2 * r + 6),
       lambda s, r=r: pygame.draw.circle(s, W, (r + 3, r + 3), r, 1))
# circle clipped at edge
fx("circle_fill_clipped", (8, 8), lambda s: pygame.draw.circle(s, W, (1, 1), 4))
fx("circle_thin_clipped", (8, 8), lambda s: pygame.draw.circle(s, W, (0, 4), 3, 1))

# rects, incl. both sides of the too-thin-outline fill fallback (which
# pygame evaluates on the CLIPPED rect) and the w2 boundary case
fx("rect_fill", (10, 10), lambda s: pygame.draw.rect(s, W, pygame.Rect(2, 3, 5, 4)))
fx("rect_fill_clipped", (6, 6), lambda s: pygame.draw.rect(s, W, pygame.Rect(-2, -1, 5, 4)))
fx("rect_outline_w1", (12, 12), lambda s: pygame.draw.rect(s, W, pygame.Rect(2, 2, 7, 6), 1))
fx("rect_outline_thin_fallback", (12, 12), lambda s: pygame.draw.rect(s, W, pygame.Rect(2, 2, 2, 6), 1))
fx("rect_outline_clipped_thin", (8, 8), lambda s: pygame.draw.rect(s, W, pygame.Rect(-6, 2, 8, 6), 1))
fx("rect_outline_w2", (14, 12), lambda s: pygame.draw.rect(s, W, pygame.Rect(2, 2, 8, 7), 2))
fx("rect_outline_w2_tight", (12, 12), lambda s: pygame.draw.rect(s, W, pygame.Rect(2, 2, 4, 8), 2))

ver = pygame.version.ver
lines = [
    "//! pygame-ce %s ground-truth pixel fixtures for raster parity tests." % ver,
    "//! Each entry is (surface_w, surface_h, &[(x, y) of lit pixels]).",
    "//! (rustfmt: skipped via the outer attribute on the mod declaration.)",
    "#![allow(clippy::all)]",
    "",
    "// GENERATED by gen_fixtures.py against pygame-ce %s -- do not edit." % ver,
    "",
]
for name, size, pts in fixtures:
    vec = "&[" + ", ".join(f"({x}, {y})" for x, y in pts) + "]"
    lines.append("pub const %s: (i32, i32, &[(i32, i32)]) = (%d, %d, %s);"
                 % (name.upper(), size[0], size[1], vec))
OUT.write_text("\n".join(lines) + "\n")
print(f"wrote {OUT} ({len(fixtures)} fixtures)")
