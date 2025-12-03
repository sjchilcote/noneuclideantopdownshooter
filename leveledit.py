#!/usr/bin/env python3
"""

"""

import pygame, pickle, math, sys, time, copy, numpy as np, json, os
pygame.init()

# =============================================================================
# Global Editor Settings and Variables
# =============================================================================
SNAP_TO_GRID = True
GRID_SIZE = 50
EDGE_CAMERA_MOVEMENT = True
F1_DOCUMENT_ACTIVE = False
WINDOW_SIZE = (1600, 900)
VERTEX_MERGE_THRESHOLD = 8
MATCHED_EDGE_FUDGE = 2  # tolerance for colinearity (world units)
MATCHED_EDGE_CONNECTION_THRESHOLD = 8
POINTING_TOLERANCE = 8
BUTTON_NORMAL_COLOR = (200,200,200)
BUTTON_HOVER_COLOR = (200,200,100)
BUTTON_ACTIVE_COLOR = (100,200,100)
BUTTON_TEXT_COLOR = (0,0,0)

FONT_NAME = "Fixedsys Excelsior 3.01"
FONT_SMALL = pygame.font.SysFont(FONT_NAME, 16)
FONT_MEDIUM = pygame.font.SysFont(FONT_NAME, 16)
FONT_HELP = pygame.font.SysFont(FONT_NAME, 16)
FONT_LARGE = pygame.font.SysFont(FONT_NAME, 32)
SCREEN_CENTER = (WINDOW_SIZE[0] / 2, WINDOW_SIZE[1] / 2)

camera_offset = np.array([0.0, 0.0])
zoom = 1.0
is_resizing = False
last_resize_time = 0
current_save_file = None


# =============================================================================
# Helper Functions: Coordinate Conversion and Basic Geometry
# =============================================================================
def world_to_screen(pt, cam, zm, scr):
    global SCREEN_CENTER
    return ((pt[0] - cam[0]) * zm + SCREEN_CENTER[0],
            (pt[1] - cam[1]) * zm + SCREEN_CENTER[1])


def screen_to_world(pt, cam, zm, scr):
    return ((pt[0] - scr[0] / 2) / zm + cam[0], (pt[1] - scr[1] / 2) / zm + cam[1])


def snap_point(pt):
    if SNAP_TO_GRID:
        return (round(pt[0] / GRID_SIZE) * GRID_SIZE, round(pt[1] / GRID_SIZE) * GRID_SIZE)
    return pt


def point_line_distance(p, a, b):
    px, py = p;
    ax, ay = a;
    bx, by = b
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0: return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0, min(1, t))
    proj = (ax + t * dx, ay + t * dy)
    return math.hypot(px - proj[0], py - proj[1])


def project_point_on_line(p, a, b):
    ax, ay = a;
    bx, by = b;
    px, py = p
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0: return a
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    return (ax + t * dx, ay + t * dy)


def draw_dotted_line(surf, start, end, color, dot_len=5, gap=3):
    sx, sy = start;
    ex, ey = end
    dist = math.hypot(ex - sx, ey - sy)
    if dist == 0: return
    ux, uy = (ex - sx) / dist, (ey - sy) / dist
    seg = dot_len + gap
    n = int(dist // seg)
    for i in range(n + 1):
        st = (sx + i * seg * ux, sy + i * seg * uy)
        en = (st[0] + dot_len * ux, st[1] + dot_len * uy)
        pygame.draw.line(surf, color, st, en, 1)


def point_in_polygon(pt, verts):
    x, y = pt;
    inside = False;
    n = len(verts);
    j = n - 1
    for i in range(n):
        xi, yi = verts[i];
        xj, yj = verts[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-10) + xi):
            inside = not inside
        j = i
    return inside

def get_polygon_under_cursor(world, pt):
    candidates = []
    for room in world.rooms:
        if point_in_polygon(pt, room.vertices):
            center = room.get_center()
            d = math.hypot(pt[0] - center[0], pt[1] - center[1])
            candidates.append((room, d))
    if candidates:
        return sorted(candidates, key=lambda x: x[1])[0][0]
    return None

def edges_are_collinear(a1, a2, b1, b2, tol):
    dx1, dy1 = a2[0] - a1[0], a2[1] - a1[1]
    dx2, dy2 = b2[0] - b1[0], b2[1] - b1[1]
    l1 = math.hypot(dx1, dy1);
    l2 = math.hypot(dx2, dy2)
    if l1 == 0 or l2 == 0: return False
    ux1, uy1 = dx1 / l1, dy1 / l1;
    ux2, uy2 = dx2 / l2, dy2 / l2
    if abs(abs(ux1 * ux2 + uy1 * uy2) - 1) > 0.01: return False
    return point_line_distance(b1, a1, a2) <= tol


def set_cursor(cursor_type):
    pygame.mouse.set_cursor(pygame.cursors.Cursor(cursor_type))


def edges_share_vertex(room1, edge_index1, room2, edge_index2):
    if room1.id == room2.id:
        n = len(room1.vertices)
        return (edge_index1 == edge_index2 or
                (edge_index1 + 1) % n == edge_index2 or
                (edge_index2 + 1) % n == edge_index1)
    v1_start = room1.vertices[edge_index1]
    v1_end = room1.vertices[(edge_index1 + 1) % len(room1.vertices)]
    v2_start = room2.vertices[edge_index2]
    v2_end = room2.vertices[(edge_index2 + 1) % len(room2.vertices)]
    return (v1_start == v2_start or v1_start == v2_end or v1_end == v2_start or v1_end == v2_end)

def find_closest_edge_index(mid, vertices):
    best_idx = None; best_dist = float('inf'); n = len(vertices)
    for i in range(n):
        A = vertices[i]; B = vertices[(i+1)%n]
        edge_mid = ((A[0]+B[0])/2, (A[1]+B[1])/2)
        d = math.hypot(edge_mid[0]-mid[0], edge_mid[1]-mid[1])
        if d < best_dist:
            best_dist = d; best_idx = i
    return best_idx, best_dist


def export_level_to_json(world, grid_size, snap_to_grid, edge_camera_movement, filename="level.json"):
    data = {
        "version": "1.0",
        "meta": {
            "grid_size": grid_size,
            "snap_to_grid": snap_to_grid,
            "edge_camera_movement": edge_camera_movement
        },
        "rooms": []
    }

    for room in world.rooms:
        room_data = {
            "id": room.id,
            "vertices": room.vertices,
            "connections": {},
            "entities": []
        }

        # Only save valid connections
        for edge_index, (target_room, target_edge) in room.connections.items():
            room_data["connections"][str(edge_index)] = {
                "target_room": target_room,
                "target_edge": target_edge
            }

        for entity in room.entities:
            room_data["entities"].append({
                "type": entity.__class__.__name__,
                "pos": [float(entity.pos[0]), float(entity.pos[1])]
            })

        data["rooms"].append(room_data)

    with open(filename, "w") as f:
        json.dump(data, f, indent=2)

def import_level_from_json(filename):
    global GRID_SIZE, SNAP_TO_GRID, EDGE_CAMERA_MOVEMENT
    with open(filename, "r") as f:
        data = json.load(f)
    meta = data.get("meta", {})
    GRID_SIZE = meta.get("grid_size", GRID_SIZE)
    SNAP_TO_GRID = meta.get("snap_to_grid", SNAP_TO_GRID)
    EDGE_CAMERA_MOVEMENT = meta.get("edge_camera_movement", EDGE_CAMERA_MOVEMENT)
    world = EditorWorld()
    max_id = 0
    from main import get_all_entity_subclasses
    entity_classes = get_all_entity_subclasses()
    entity_dict = {cls.__name__: cls for cls in entity_classes}
    for room_data in data.get("rooms", []):
        room = EditorRoom(room_data["vertices"])
        room.id = room_data["id"]
        max_id = max(max_id, room.id)
        room.connections = {int(k): (v["target_room"], v["target_edge"])
                            for k, v in room_data.get("connections", {}).items()}
        room.entities = []
        for ent in room_data.get("entities", []):
            ent_type = ent.get("type")
            pos = ent.get("pos")
            if ent_type in entity_dict:
                entity_instance = entity_dict[ent_type](room, pos)
                room.entities.append(entity_instance)
            else:
                print(f"Warning: Unknown entity type '{ent_type}' in room {room.id}")
        world.rooms.append(room)
    EditorRoom._id_counter = max_id + 1
    return world

def pygame_file_dialog(mode="open", initial_path=".", default_name=""):
    surface = pygame.display.get_surface()
    sw, sh = surface.get_size()
    dialog_width, dialog_height = 400, 300
    dialog_rect = pygame.Rect((sw - dialog_width)//2, (sh - dialog_height)//2, dialog_width, dialog_height)
    font = FONT_SMALL
    clock = pygame.time.Clock()
    current_path = os.path.abspath(initial_path)
    selected_index = None
    input_text = default_name if mode=="save" else ""
    file_list = []
    scroll_offset = 0

    def refresh_file_list():
        nonlocal file_list
        try:
            items = os.listdir(current_path)
        except Exception:
            items = []
        items = sorted(items, key=lambda x: (not os.path.isdir(os.path.join(current_path, x)), x.lower()))
        file_list = [".."] + items
    refresh_file_list()

    running = True
    result = None
    while running:
        clock.tick(30)
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            elif event.type == pygame.KEYDOWN:
                if mode=="save":
                    if event.key == pygame.K_BACKSPACE:
                        input_text = input_text[:-1]
                    elif event.key == pygame.K_RETURN:
                        result = input_text
                        running = False
                    elif event.key == pygame.K_ESCAPE:
                        running = False
                    else:
                        input_text += event.unicode
                else:
                    if event.key == pygame.K_ESCAPE:
                        running = False
            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:
                    mx, my = event.pos
                    list_rect = pygame.Rect(dialog_rect.x+10, dialog_rect.y+40, dialog_width-20, dialog_height-100)
                    if list_rect.collidepoint(mx, my):
                        rel_y = my - list_rect.y
                        index = rel_y // 25 + scroll_offset
                        if 0 <= index < len(file_list):
                            selected_index = index
                            item = file_list[index]
                            full_path = os.path.join(current_path, item)
                            if os.path.isdir(full_path):
                                current_path = os.path.abspath(full_path) if item != ".." else os.path.dirname(current_path)
                                refresh_file_list()
                                selected_index = None
                            else:
                                if mode=="open":
                                    result = item
                                    running = False
                    # Check OK and Cancel buttons
                    ok_rect = pygame.Rect(dialog_rect.x+dialog_width-180, dialog_rect.y+dialog_height-50, 80, 30)
                    cancel_rect = pygame.Rect(dialog_rect.x+dialog_width-90, dialog_rect.y+dialog_height-50, 80, 30)
                    if ok_rect.collidepoint(mx, my):
                        if mode=="open":
                            if selected_index is not None:
                                item = file_list[selected_index]
                                full_path = os.path.join(current_path, item)
                                if os.path.isfile(full_path):
                                    result = item
                                    running = False
                        else:  # save mode
                            result = input_text
                            running = False
                    elif cancel_rect.collidepoint(mx, my):
                        running = False

        # Draw dialog overlay
        overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        overlay.fill((0,0,0,150))
        surface.blit(overlay, (0,0))
        # Draw dialog box
        pygame.draw.rect(surface, (200,200,200), dialog_rect)
        pygame.draw.rect(surface, (0,0,0), dialog_rect, 2)
        title = "Open File" if mode=="open" else "Save File"
        title_surf = font.render(title, True, (0,0,0))
        surface.blit(title_surf, (dialog_rect.x+10, dialog_rect.y+10))
        # Draw current path
        path_surf = font.render(current_path, True, (0,0,0))
        surface.blit(path_surf, (dialog_rect.x+10, dialog_rect.y+30))
        # Draw file list area
        list_rect = pygame.Rect(dialog_rect.x+10, dialog_rect.y+40, dialog_width-20, dialog_height-100)
        pygame.draw.rect(surface, (255,255,255), list_rect)
        pygame.draw.rect(surface, (0,0,0), list_rect, 1)
        # Draw file items
        for i, item in enumerate(file_list[scroll_offset:scroll_offset + list_rect.height//25]):
            item_rect = pygame.Rect(list_rect.x, list_rect.y + i*25, list_rect.width, 25)
            color = (180,180,250) if (i+scroll_offset)==selected_index else (255,255,255)
            pygame.draw.rect(surface, color, item_rect)
            item_surf = font.render(item, True, (0,0,0))
            surface.blit(item_surf, (item_rect.x+5, item_rect.y+5))
        # Draw input box for save mode
        if mode=="save":
            input_rect = pygame.Rect(dialog_rect.x+10, dialog_rect.y+dialog_height-80, dialog_width-20, 30)
            pygame.draw.rect(surface, (255,255,255), input_rect)
            pygame.draw.rect(surface, (0,0,0), input_rect, 1)
            input_surf = font.render(input_text, True, (0,0,0))
            surface.blit(input_surf, (input_rect.x+5, input_rect.y+5))
        # Draw OK and Cancel buttons
        ok_rect = pygame.Rect(dialog_rect.x+dialog_width-180, dialog_rect.y+dialog_height-50, 80, 30)
        cancel_rect = pygame.Rect(dialog_rect.x+dialog_width-90, dialog_rect.y+dialog_height-50, 80, 30)
        pygame.draw.rect(surface, (200,200,200), ok_rect)
        pygame.draw.rect(surface, (0,0,0), ok_rect, 2)
        pygame.draw.rect(surface, (200,200,200), cancel_rect)
        pygame.draw.rect(surface, (0,0,0), cancel_rect, 2)
        ok_text = font.render("OK", True, (0,0,0))
        cancel_text = font.render("Cancel", True, (0,0,0))
        surface.blit(ok_text, (ok_rect.x+20, ok_rect.y+5))
        surface.blit(cancel_text, (cancel_rect.x+5, cancel_rect.y+5))
        pygame.display.flip()

    if result:
        return os.path.join(current_path, result)
    else:
        return None

def ask_save_filename():
    return pygame_file_dialog(mode="save", initial_path=".", default_name="level.json")

def ask_load_filename():
    return pygame_file_dialog(mode="open", initial_path=".")

class Button:
    def __init__(self, rect, text, callback, toggle=False, active=False, font=None, enabled=True):
        self.rect = pygame.Rect(rect)
        self.text = text
        self.callback = callback
        self.toggle = toggle
        self.active = active
        self.font = font or FONT_SMALL
        self.enabled = enabled
    def update(self):
        self.hovered = self.rect.collidepoint(pygame.mouse.get_pos())
    def handle_event(self, event):
        if not self.enabled:
            return
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                if self.toggle:
                    self.active = not self.active
                if self.callback:
                    self.callback()
    def draw(self, surface):
        self.update()
        color = BUTTON_ACTIVE_COLOR if (self.toggle and self.active) else (BUTTON_HOVER_COLOR if self.hovered else BUTTON_NORMAL_COLOR)
        if not self.enabled:
            color = (150,150,150)
        pygame.draw.rect(surface, color, self.rect)
        txt_surface = self.font.render(self.text, True, BUTTON_TEXT_COLOR)
        txt_rect = txt_surface.get_rect(center=self.rect.center)
        surface.blit(txt_surface, txt_rect)
    def collidepoint(self, pos):
        return self.rect.collidepoint(pos)


# =============================================================================
# Data Classes: EditorRoom, EditorWorld, UndoManager
# =============================================================================
class EditorRoom:
    _id_counter = 1

    def __init__(self, vertices=None):
        self.vertices = vertices[:] if vertices else []
        self.connections = {}  # key: edge index, value: (target_room_id, target_edge_index)
        self.id = EditorRoom._id_counter
        EditorRoom._id_counter += 1
        self.is_spawn = False
        self.selected = False
        self.entities = []

    def get_center(self):
        n = len(self.vertices)
        return (sum(v[0] for v in self.vertices) / n, sum(v[1] for v in self.vertices) / n)

    def is_convex(self):
        n = len(self.vertices)
        if n < 3: return True
        sign = None
        for i in range(n):
            A = self.vertices[i]
            B = self.vertices[(i + 1) % n]
            C = self.vertices[(i + 2) % n]
            cross = (B[0] - A[0]) * (C[1] - B[1]) - (B[1] - A[1]) * (C[0] - B[0])
            if cross != 0:
                curr = cross > 0
                if sign is None:
                    sign = curr
                elif sign != curr:
                    return False
        return True

    def move(self, dx, dy):
        self.vertices = [(v[0] + dx, v[1] + dy) for v in self.vertices]

    def fix_winding(self, desired_sign, world):
        n = len(self.vertices)
        area = sum(self.vertices[i][0]*self.vertices[(i+1)%n][1] -
                   self.vertices[(i+1)%n][0]*self.vertices[i][1]
                   for i in range(n))
        current_sign = area < 0
        if current_sign != desired_sign:
            old_connections = self.connections.copy()
            old_vertices = self.vertices.copy()
            self.vertices.reverse()
            self.connections = {}
            for old_edge_idx, conn in old_connections.items():
                A_old = old_vertices[old_edge_idx]
                B_old = old_vertices[(old_edge_idx+1)%len(old_vertices)]
                old_mid = ((A_old[0]+B_old[0])/2, (A_old[1]+B_old[1])/2)
                new_idx, dist = find_closest_edge_index(old_mid, self.vertices)
                # Only reassign if the new edge is within a reasonable distance.
                if dist < 30:
                    self.connections[new_idx] = conn
                    target = next((r for r in world.rooms if r.id == conn[0]), None)
                    if target and conn[1] in target.connections and target.connections[conn[1]][0] == self.id:
                        target.connections[conn[1]] = (self.id, new_idx)
            return True
        return False

    def detect_vertex_list_changes(self, world):
        return EditorRoom.VertexListChangeDetector(self, world)
    class VertexListChangeDetector:
        def __init__(self, room, world):
            self.room = room
            self.world = world
            self.old_mapping = {}  # Maps original edge index to (fractional position, connection tuple)
        def __enter__(self):
            n = len(self.room.vertices)
            if n == 0:
                return self
            total = 0
            lengths = []
            for i in range(n):
                a = self.room.vertices[i]
                b = self.room.vertices[(i+1) % n]
                d = math.hypot(b[0] - a[0], b[1] - a[1])
                lengths.append(d)
                total += d
            for edge_idx, conn in self.room.connections.items():
                # Compute fractional position along perimeter at the midpoint of the edge.
                cum = sum(lengths[:edge_idx]) + lengths[edge_idx] / 2
                f = cum / total if total > 0 else 0
                self.old_mapping[edge_idx] = (f, conn)
            return self
        def __exit__(self, exc_type, exc_val, traceback):
            n = len(self.room.vertices)
            if n == 0:
                return
            total = 0
            new_lengths = []
            for i in range(n):
                a = self.room.vertices[i]
                b = self.room.vertices[(i+1) % n]
                d = math.hypot(b[0] - a[0], b[1] - a[1])
                new_lengths.append(d)
                total += d
            new_connections = {}
            for old_edge_idx, (f, conn) in self.old_mapping.items():
                best_edge = None
                best_diff = float('inf')
                cum_inner = 0
                for i in range(n):
                    pos = (cum_inner + new_lengths[i] / 2) / total if total > 0 else 0
                    diff = abs(pos - f)
                    if diff < best_diff:
                        best_diff = diff
                        best_edge = i
                    cum_inner += new_lengths[i]
                if best_edge is not None:
                    new_connections[best_edge] = conn
                    target = next((r for r in self.world.rooms if r.id == conn[0]), None)
                    if target and conn[1] in target.connections and target.connections[conn[1]][0] == self.room.id:
                        target.connections[conn[1]] = (self.room.id, best_edge)
            self.room.connections = new_connections

    def draw(self, surf, cam, zm, scr, world):
        sverts = [world_to_screen(v, cam, zm, scr) for v in self.vertices]
        fill = (50, 50, 50) if self.is_convex() else (70, 0, 0)
        pygame.draw.polygon(surf, fill, sverts, 0)
        n = len(self.vertices)
        temp = pygame.Surface(scr, pygame.SRCALPHA)  # preallocate one temporary surface for all alpha lines
        for i in range(n):
            A = self.vertices[i]
            B = self.vertices[(i + 1) % n]
            sA = world_to_screen(A, cam, zm, scr)
            sB = world_to_screen(B, cam, zm, scr)
            if self.is_convex():
                if i in self.connections:
                    pygame.draw.line(temp, (150, 150, 255, 128), sA, sB, 7)
                else:
                    pygame.draw.line(surf, (128, 128, 128), sA, sB, 4)
            else:
                if i in self.connections:
                    pygame.draw.line(temp, (255, 0, 0, 128), sA, sB, 9)
                else:
                    pygame.draw.line(surf, (255, 0, 0), sA, sB, 6)
        surf.blit(temp, (0, 0))
        for i, conn in self.connections.items():
            target = next((r for r in world.rooms if r.id == conn[0]), None)
            if target:
                n1 = len(self.vertices)
                A = self.vertices[i]
                B = self.vertices[(i + 1) % n1]
                mid1 = ((A[0] + B[0]) / 2, (A[1] + B[1]) / 2)
                n2 = len(target.vertices)
                C = target.vertices[conn[1]]
                D = target.vertices[(conn[1] + 1) % n2]
                mid2 = ((C[0] + D[0]) / 2, (C[1] + D[1]) / 2)
                draw_dotted_line(surf, world_to_screen(mid1, cam, zm, scr),
                                 world_to_screen(mid2, cam, zm, scr), (0, 0, 255))
        for pt in sverts:
            pygame.draw.circle(surf, (255, 0, 0), (int(pt[0]), int(pt[1])), max(2, int(4 * zm)))
        T_cam = np.array([[zm, 0, scr[0] / 2 - zm * camera_offset[0]],
                          [0, zm, scr[1] / 2 - zm * camera_offset[1]],
                          [0, 0, 1]])
        for entity in self.entities:
            entity.draw(surf, T_cam)

    def draw_highlight(self, surf, cam, zm, scr, state):
        # Per requirements: hover = yellow, selected = green.
        sverts = [world_to_screen(v, cam, zm, scr) for v in self.vertices]
        col = (255, 255, 0) if state == "hover" else (0, 255, 0)
        thick = 3 if state == "hover" else 5
        pygame.draw.polygon(surf, col, sverts, thick)

    def __repr__(self):
        return f"<EditorRoom id={self.id}>"


class EditorWorld:
    def __init__(self):
        self.rooms = []

    def add_room(self, room):
        self.rooms.append(room)

    def draw(self, surf, cam, zm, scr):
        # Draw grid
        top_left = screen_to_world((0, 0), cam, zm, scr)
        bot_right = screen_to_world(scr, cam, zm, scr)
        start_x = math.floor(top_left[0] / GRID_SIZE) * GRID_SIZE
        end_x = math.ceil(bot_right[0] / GRID_SIZE) * GRID_SIZE
        start_y = math.floor(top_left[1] / GRID_SIZE) * GRID_SIZE
        end_y = math.ceil(bot_right[1] / GRID_SIZE) * GRID_SIZE
        grid_col = (128, 128, 128) if SNAP_TO_GRID else (64, 64, 64)
        for x in range(int(start_x), int(end_x) + 1, GRID_SIZE):
            pygame.draw.line(surf, grid_col, world_to_screen((x, start_y), cam, zm, scr),
                             world_to_screen((x, end_y), cam, zm, scr), 1)
        for y in range(int(start_y), int(end_y) + 1, GRID_SIZE):
            pygame.draw.line(surf, grid_col, world_to_screen((start_x, y), cam, zm, scr),
                             world_to_screen((end_x, y), cam, zm, scr), 1)
        # Draw rooms
        for room in self.rooms:
            room.draw(surf, cam, zm, scr, self)

    def get_room_at_point(self, pt):
        candidates = []
        for room in self.rooms:
            if point_in_polygon(pt, room.vertices):
                center = room.get_center()
                d = math.hypot(pt[0] - center[0], pt[1] - center[1])
                candidates.append((room, d))
        if candidates:
            return sorted(candidates, key=lambda x: x[1])[0][0]
        return None


class UndoManager:
    def __init__(self):
        self.undo_stack = []
        self.redo_stack = []

    def record_state(self, world):
        self.undo_stack.append(copy.deepcopy(world))
        self.redo_stack = []

    def can_undo(self):
        return len(self.undo_stack) > 0

    def can_redo(self):
        return len(self.redo_stack) > 0

    def undo(self, current):
        if self.can_undo():
            self.redo_stack.append(copy.deepcopy(current))
            return self.undo_stack.pop()
        return current

    def redo(self, current):
        if self.can_redo():
            self.undo_stack.append(copy.deepcopy(current))
            return self.redo_stack.pop()
        return current


undo_manager = UndoManager()


# =============================================================================
# Base Class for Editor Tools
# =============================================================================
class EditorTool:
    desc = "Tool description."
    buttons = "Button help."
    help_text = ""

    def __init__(self):
        self.current_highlight = None
        self.box_select = False
        self.start_box = None
        self.dragging = False

    def update_highlight(self, world, pt):
        self.current_highlight = self.what_is_mouse_over(world, pt)

    def what_is_mouse_over(self, world, pt):
        return None

    def handle_event(self, event, world, scr):
        pass

    def draw(self, surf, world, scr):
        pass

    def box_select_rooms(self, world, rect, mode="inclusive"):
        sels = []
        for room in world.rooms:
            xs = [v[0] for v in room.vertices]
            ys = [v[1] for v in room.vertices]
            room_rect = pygame.Rect(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
            if mode == "inclusive":
                if rect.colliderect(room_rect):
                    sels.append(room)
            elif mode == "exclusive":
                if rect.contains(room_rect):
                    sels.append(room)
        return sels

    def box_select_edges(self, world, rect, mode="inclusive"):
        sels = []
        for room in world.rooms:
            n = len(room.vertices)
            for i in range(n):
                A = room.vertices[i]
                B = room.vertices[(i + 1) % n]
                if mode == "inclusive":
                    mid = ((A[0] + B[0]) / 2, (A[1] + B[1]) / 2)
                    if rect.collidepoint(mid):
                        sels.append((room, i))
                elif mode == "exclusive":
                    if rect.collidepoint(A) and rect.collidepoint(B):
                        sels.append((room, i))
        return sels


# =============================================================================
# Polygon Tool
# =============================================================================
class PolygonTool(EditorTool):
    desc = "Make new rooms"
    buttons = ("Left-click: add vertex / drag room\n"
               "Right-click: finish polygon / delete room\n"
               "Enter: finish polygon\nEsc: cancel")
    help_text = (
        "Polygon Tool Help:\n"
        "• When the cursor is over empty space, a semi‑transparent preview vertex follows the cursor.\n"
        "• Left-click in empty space adds a proposed vertex (snapped if enabled).\n"
        "  If clicking near an existing vertex or the first vertex, that vertex is used and if it’s the first, finalizes the room.\n"
        "• When no proposed vertices exist, clicking inside a room selects it for dragging.\n"
        "• Right-click finishes the polygon (if ≥3 vertices) or deletes a room if clicked on one.\n"
        "• New rooms auto‑connect along edges with exact vertex matches."
    )

    def __init__(self):
        super().__init__()
        self.proposed = []
        self.dragging_room = None
        self.drag_offset = (0, 0)

    def what_is_mouse_over(self, world, pt):
        # If there are proposed vertices, try to find a nearby vertex (for snapping)
        if self.proposed:
            nv = get_nearest_vertex(world, pt, threshold=POINTING_TOLERANCE)
            return nv  # returns tuple ('vertex', data)
        else:
            return get_polygon_under_cursor(world, pt)

    def handle_event(self, event, world, scr):
        if hasattr(event, 'pos'):
            wp = screen_to_world(event.pos, camera_offset, zoom, scr)
            self.update_highlight(world, wp)
        # Finalize room if clicking near first proposed vertex
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            wp = screen_to_world(event.pos, camera_offset, zoom, scr)
            if self.proposed:
                first = self.proposed[0]
                if math.hypot(wp[0] - first[0], wp[1] - first[1]) < VERTEX_MERGE_THRESHOLD:
                    if len(self.proposed) >= 3:
                        new_room = EditorRoom(self.proposed[:])
                        # Enforce counterclockwise winding (desired_sign False means area ≥ 0)
                        new_room.fix_winding(False, world)
                        world.add_room(new_room)
                        self._auto_connect(new_room, world)
                        undo_manager.record_state(world)
                    self.proposed = []
                    return
            # If no proposed vertices, check if clicking inside a room to drag it
            room = get_polygon_under_cursor(world, wp)
            if room and not self.proposed:
                self.dragging_room = room
                center = room.get_center()
                self.drag_offset = (center[0] - wp[0], center[1] - wp[1])
            else:
                # Otherwise add a vertex
                candidate = get_nearest_vertex(world, wp, threshold=VERTEX_MERGE_THRESHOLD)
                if candidate:
                    room_ref, vi, _ = candidate
                    self.proposed.append(room_ref.vertices[vi])
                else:
                    self.proposed.append(snap_point(wp) if SNAP_TO_GRID else wp)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
            wp = screen_to_world(event.pos, camera_offset, zoom, scr)
            if self.proposed:
                if len(self.proposed) >= 3:
                    new_room = EditorRoom(self.proposed[:])
                    new_room.fix_winding(False, world)
                    world.add_room(new_room)
                    self._auto_connect(new_room, world)
                    undo_manager.record_state(world)
                self.proposed = []
            else:
                room = get_polygon_under_cursor(world, wp)
                if room:
                    world.rooms.remove(room)
                    undo_manager.record_state(world)
        elif event.type == pygame.MOUSEMOTION:
            if self.dragging_room:
                wp = screen_to_world(event.pos, camera_offset, zoom, scr)
                new_center = (wp[0] + self.drag_offset[0], wp[1] + self.drag_offset[1])
                dx = new_center[0] - self.dragging_room.get_center()[0]
                dy = new_center[1] - self.dragging_room.get_center()[1]
                if SNAP_TO_GRID:
                    dx = round(dx / GRID_SIZE) * GRID_SIZE
                    dy = round(dy / GRID_SIZE) * GRID_SIZE
                self.dragging_room.move(dx, dy)
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self.dragging_room:
                undo_manager.record_state(world)
                self.dragging_room = None
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_RETURN:
                if self.proposed and len(self.proposed) >= 3:
                    new_room = EditorRoom(self.proposed[:])
                    new_room.fix_winding(False, world)
                    world.add_room(new_room)
                    self._auto_connect(new_room, world)
                    undo_manager.record_state(world)
                    self.proposed = []
            elif event.key == pygame.K_ESCAPE:
                self.proposed = []
                self.dragging_room = None

    def _auto_connect(self, new_room, world):
        eps = 1e-5
        n = len(new_room.vertices)
        for i in range(n):
            A = new_room.vertices[i]
            B = new_room.vertices[(i + 1) % n]
            for other in world.rooms:
                if other.id == new_room.id: continue
                m = len(other.vertices)
                for j in range(m):
                    C = other.vertices[j]
                    D = other.vertices[(j + 1) % m]
                    if ((abs(A[0] - C[0]) < eps and abs(A[1] - C[1]) < eps and abs(B[0] - D[0]) < eps and abs(
                            B[1] - D[1]) < eps) or
                            (abs(A[0] - D[0]) < eps and abs(A[1] - D[1]) < eps and abs(B[0] - C[0]) < eps and abs(
                                B[1] - C[1]) < eps)):
                        new_room.connections[i] = (other.id, j)
                        other.connections[j] = (new_room.id, i)

    def draw(self, surf, world, scr):
        overlay = pygame.Surface(scr, pygame.SRCALPHA)
        mouse_pos = pygame.mouse.get_pos()
        wp = screen_to_world(mouse_pos, camera_offset, zoom, scr)
        cand = get_nearest_vertex(world, wp, threshold=VERTEX_MERGE_THRESHOLD)
        if cand:
            room_ref, vi, _ = cand
            cand_pos = room_ref.vertices[vi]
            scand = world_to_screen(cand_pos, camera_offset, zoom, scr)
            pygame.draw.circle(overlay, (255, 255, 0, 200), (int(scand[0]), int(scand[1])), 6)
            if self.proposed:
                base = self.proposed[-1]
                sbase = world_to_screen(base, camera_offset, zoom, scr)
                pygame.draw.circle(overlay, (0, 255, 0, 200), (int(sbase[0]), int(sbase[1])), 6)
                pts = [world_to_screen(p, camera_offset, zoom, scr) for p in self.proposed]
                pygame.draw.lines(overlay, (255, 255, 0, 200), False, pts + [scand], 2)
        else:
            preview = snap_point(wp) if SNAP_TO_GRID else wp
            sprev = world_to_screen(preview, camera_offset, zoom, scr)
            pygame.draw.circle(overlay, (255, 255, 0, 150), (int(sprev[0]), int(sprev[1])), 4)
            if self.proposed:
                pts = [world_to_screen(p, camera_offset, zoom, scr) for p in self.proposed]
                pygame.draw.lines(overlay, (255, 255, 0, 200), False, pts + [sprev], 2)
        if self.proposed:
            pts = [world_to_screen(p, camera_offset, zoom, scr) for p in self.proposed]
            if cand:
                for pt in pts[:-1]:
                    pygame.draw.circle(overlay, (255, 0, 0, 150), (int(pt[0]), int(pt[1])), 4)
                # The last proposed vertex is already highlighted in green above.
            else:
                for pt in pts:
                    pygame.draw.circle(overlay, (255, 0, 0, 150), (int(pt[0]), int(pt[1])), 4)
        if self.dragging_room:
            self.dragging_room.draw_highlight(overlay, camera_offset, zoom, scr, "selected")
        if not self.proposed and self.current_highlight and isinstance(self.current_highlight, EditorRoom):
            self.current_highlight.draw_highlight(overlay, camera_offset, zoom, scr, "hover")
        surf.blit(overlay, (0, 0))



# =============================================================================
# Vertex Tool
# =============================================================================
def get_nearest_vertex(world, pt, threshold=10):
    best = None;
    bestd = threshold
    for room in world.rooms:
        for i, v in enumerate(room.vertices):
            d = math.hypot(pt[0] - v[0], pt[1] - v[1])
            if d < bestd:
                best = (room, i, d)
                bestd = d
    return best


def get_nearest_edge(world, pt, threshold=10):
    best = None;
    bestd = threshold
    for room in world.rooms:
        n = len(room.vertices)
        for i in range(n):
            A = room.vertices[i]
            B = room.vertices[(i + 1) % n]
            d = point_line_distance(pt, A, B)
            if d < bestd:
                best = (room, i, d)
                bestd = d
    return best


class VertexTool(EditorTool):
    desc = "Edit room vertices"
    buttons = ("Left-click: drag vertex or add vertex on edge\n"
               "Right-click: delete vertex\nEsc: cancel")
    help_text = (
        "Vertex Tool Help:\n"
        "• Left-click near a vertex to drag it (preview becomes yellow; active is green).\n"
        "• If no vertex is nearby, clicking near an edge inserts a new vertex at the perpendicular projection.\n"
        "• Right-click a vertex to delete it (if the room remains with ≥3 vertices).\n"
        "• When dragging, the tool preserves the original winding (auto‑corrects if reversed).\n"
        "• A preview vertex is shown when hovering over an edge."
    )

    def __init__(self):
        super().__init__()
        self.dragging_vertex = None  # (room, vertex_index, offset, orig_winding)

    def what_is_mouse_over(self, world, pt):
        nv = get_nearest_vertex(world, pt, threshold=VERTEX_MERGE_THRESHOLD)
        if nv: return ('vertex', nv)
        ne = get_nearest_edge(world, pt, threshold=VERTEX_MERGE_THRESHOLD)
        if ne: return ('edge', ne)
        return None

    def handle_event(self, event, world, scr):
        if hasattr(event, 'pos'):
            wp = screen_to_world(event.pos, camera_offset, zoom, scr)
            self.update_highlight(world, wp)
        if event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:
                hit = self.what_is_mouse_over(world, screen_to_world(event.pos, camera_offset, zoom, scr))
                if hit:
                    typ, data = hit
                    if typ == 'vertex':
                        room, vi, _ = data
                        # store original winding sign
                        area = 0
                        n = len(room.vertices)
                        for i in range(n):
                            x1, y1 = room.vertices[i]
                            x2, y2 = room.vertices[(i + 1) % n]
                            area += (x1 * y2 - x2 * y1)
                        orig_sign = area < 0
                        offset = (room.vertices[vi][0] - wp[0], room.vertices[vi][1] - wp[1])
                        self.dragging_vertex = (room, vi, offset, orig_sign)
                        set_cursor(pygame.SYSTEM_CURSOR_SIZEALL)
                        return
                    elif typ == 'edge':
                        room, ei, _ = data
                        # Insert new vertex on the edge
                        A = room.vertices[ei];
                        B = room.vertices[(ei + 1) % len(room.vertices)]
                        proj = project_point_on_line(wp, A, B)
                        # For snap exception: if snap would move more than 8px, use projection.
                        sp = snap_point(wp) if SNAP_TO_GRID else wp
                        new_pt = proj if math.hypot(sp[0]-wp[0], sp[1]-wp[1]) > 8 else sp
                        with room.detect_vertex_list_changes(world):
                            room.vertices.insert(ei+1, new_pt)
                        undo_manager.record_state(world)
            elif event.button == 3:
                wp = screen_to_world(event.pos, camera_offset, zoom, scr)
                hit = self.what_is_mouse_over(world, wp)
                if hit and hit[0] == 'vertex':
                    room, vi, _ = hit[1]
                    if len(room.vertices) > 3:
                        with room.detect_vertex_list_changes(world):
                            del room.vertices[vi]
                        undo_manager.record_state(world)
                self.current_highlight = None
        elif event.type == pygame.MOUSEMOTION:
            if self.dragging_vertex:
                room, vi, offset, orig_sign = self.dragging_vertex
                wp = screen_to_world(event.pos, camera_offset, zoom, scr)
                new_pt = (wp[0] + offset[0], wp[1] + offset[1])
                if SNAP_TO_GRID:
                    new_pt = snap_point(new_pt)
                room.vertices[vi] = new_pt
                # Structural changes (e.g. reversal) will be handled on mouse release.
        elif event.type == pygame.MOUSEBUTTONUP:
            if event.button == 1 and self.dragging_vertex:
                self.dragging_vertex = None
                set_cursor(pygame.SYSTEM_CURSOR_ARROW)
                undo_manager.record_state(world)
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.dragging_vertex = None
                set_cursor(pygame.SYSTEM_CURSOR_ARROW)

    def draw(self, surf, world, scr):
        overlay = pygame.Surface(scr, pygame.SRCALPHA)
        if self.current_highlight:
            typ, data = self.current_highlight
            if typ == 'vertex':
                room, vi, _ = data
                try:
                    pos = world_to_screen(room.vertices[vi], camera_offset, zoom, scr)
                except IndexError: #maybe we just deleted that highlighted vertex
                    pass
                else:
                    pygame.draw.circle(overlay, (255, 255, 0), (int(pos[0]), int(pos[1])), 6, 2)
            elif typ == 'edge':
                room, ei, _ = data
                A = room.vertices[ei];
                B = room.vertices[(ei + 1) % len(room.vertices)]
                proj = project_point_on_line(screen_to_world(pygame.mouse.get_pos(), camera_offset, zoom, scr), A, B)
                pos = world_to_screen(proj, camera_offset, zoom, scr)
                pygame.draw.circle(overlay, (255, 255, 0), (int(pos[0]), int(pos[1])), 6, 2)
        if self.dragging_vertex:
            room, vi, _, _ = self.dragging_vertex
            pos = world_to_screen(room.vertices[vi], camera_offset, zoom, scr)
            pygame.draw.circle(overlay, (0, 255, 0, 150), (int(pos[0]), int(pos[1])), 8)
        surf.blit(overlay, (0, 0))


# =============================================================================
# Connection Tool
# =============================================================================
class ConnectionTool(EditorTool):
    desc = "Link room edges"
    buttons = ("Left-click: select edge\n"
               "Click second edge: create connection\n"
               "Right-click: break connection\n"
               "Shift+Click/Drag: matched edge mode (box-select to connect pairs)")
    help_text = (
        "Connection Tool Help:\n"
        "• In normal mode, click one unconnected edge then another to connect them (edges must not share vertices).\n"
        "• Right-click on a connected edge to remove its connection.\n"
        "• In matched edges mode (hold Shift), edges nearly colinear (within tolerance) are highlighted in yellow,\n"
        "  and clicking one creates a connection with its matched partner (pre‑highlighted in blue).\n"
        "• Box‑select in Shift mode connects eligible pairs (ignoring edges sharing vertices)."
    )

    def __init__(self):
        super().__init__()
        self.first_edge = None
        self.box_select = False
        self.start_box = None

    def what_is_mouse_over(self, world, pt):
        cand = get_nearest_edge(world, pt, threshold=10)
        if cand:
            room, ei, _ = cand
            if ei in room.connections:
                return None
            return cand
        return None

    def handle_event(self, event, world, scr):
        mods = pygame.key.get_mods()
        shift_mode = bool(mods & pygame.KMOD_SHIFT)
        if hasattr(event, 'pos'):
            wp = screen_to_world(event.pos, camera_offset, zoom, scr)
            self.update_highlight(world, wp)
        if event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:
                if shift_mode:
                    if self.current_highlight:
                        if not self.first_edge:
                            self.first_edge = self.current_highlight
                        else:
                            r1, e1, _ = self.first_edge
                            r2, e2, _ = self.current_highlight
                            if r1.id != r2.id:
                                A = r1.vertices[e1]
                                B = r1.vertices[(e1+1)%len(r1.vertices)]
                                C = r2.vertices[e2]
                                D = r2.vertices[(e2+1)%len(r2.vertices)]
                                min_dist = min(math.hypot(A[0]-C[0], A[1]-C[1]),
                                               math.hypot(A[0]-D[0], A[1]-D[1]),
                                               math.hypot(B[0]-C[0], B[1]-C[1]),
                                               math.hypot(B[0]-D[0], B[1]-D[1]))
                                if edges_are_collinear(A, B, C, D, MATCHED_EDGE_FUDGE) and min_dist < MATCHED_EDGE_CONNECTION_THRESHOLD:
                                    r1.connections[e1] = (r2.id, e2)
                                    r2.connections[e2] = (r1.id, e1)
                            self.first_edge = None
                    else:
                        self.box_select = True
                        self.start_box = screen_to_world(event.pos, camera_offset, zoom, scr)
                else:
                    if self.current_highlight:
                        if not self.first_edge:
                            self.first_edge = self.current_highlight
                        else:
                            r1, e1, _ = self.first_edge
                            r2, e2, _ = self.current_highlight
                            if not edges_share_vertex(r1, e1, r2, e2):
                                r1.connections[e1] = (r2.id, e2)
                                r2.connections[e2] = (r1.id, e1)
                            self.first_edge = None
            elif event.button == 3:
                wp = screen_to_world(event.pos, camera_offset, zoom, scr)
                cand = get_nearest_edge(world, wp, threshold=10)
                if cand:
                    room, e, _ = cand
                    if e in room.connections:
                        conn = room.connections.pop(e)
                        other = next((r for r in world.rooms if r.id == conn[0]), None)
                        if other and conn[1] in other.connections:
                            del other.connections[conn[1]]
                        undo_manager.record_state(world)
        elif event.type == pygame.MOUSEBUTTONUP:
            if event.button == 1 and self.box_select:
                end_wp = screen_to_world(event.pos, camera_offset, zoom, scr)
                rect = pygame.Rect(min(self.start_box[0], end_wp[0]),
                                   min(self.start_box[1], end_wp[1]),
                                   abs(end_wp[0]-self.start_box[0]),
                                   abs(end_wp[1]-self.start_box[1]))
                edges_in_box = self.box_select_edges(world, rect)
                for i in range(len(edges_in_box)):
                    for j in range(i+1, len(edges_in_box)):
                        r1, e1 = edges_in_box[i]
                        r2, e2 = edges_in_box[j]
                        if r1.id != r2.id:
                            A = r1.vertices[e1]
                            B = r1.vertices[(e1+1)%len(r1.vertices)]
                            C = r2.vertices[e2]
                            D = r2.vertices[(e2+1)%len(r2.vertices)]
                            min_dist = min(math.hypot(A[0]-C[0], A[1]-C[1]),
                                           math.hypot(A[0]-D[0], A[1]-D[1]),
                                           math.hypot(B[0]-C[0], B[1]-C[1]),
                                           math.hypot(B[0]-D[0], B[1]-D[1]))
                            if edges_are_collinear(A, B, C, D, MATCHED_EDGE_FUDGE) and min_dist < MATCHED_EDGE_CONNECTION_THRESHOLD:
                                r1.connections[e1] = (r2.id, e2)
                                r2.connections[e2] = (r1.id, e1)
                self.box_select = False
                self.start_box = None
                self.first_edge = None
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.first_edge = None
                self.box_select = False
                self.start_box = None
    def draw(self, surf, world, scr):
        overlay = pygame.Surface(scr, pygame.SRCALPHA)
        mods = pygame.key.get_mods()
        shift_mode = bool(mods & pygame.KMOD_SHIFT)
        # Set up our glowing line parameters (blue glow for Connection tool)
        inner_color = (0, 0, 255, 178)  # 70% alpha, 3px line (bright blue)
        outer_color = (0, 0, 255, 89)    # 35% alpha, 6px line (wider glow)
        if shift_mode:
            for room in world.rooms:
                n = len(room.vertices)
                for i in range(n):
                    if i in room.connections:
                        continue
                    A = room.vertices[i]
                    B = room.vertices[(i+1)%n]
                    has_match = False
                    for other in world.rooms:
                        if other is room:
                            continue
                        m = len(other.vertices)
                        for j in range(m):
                            if j in other.connections:
                                continue
                            C = other.vertices[j]
                            D = other.vertices[(j+1)%m]
                            min_dist = min(math.hypot(A[0]-C[0], A[1]-C[1]),
                                           math.hypot(A[0]-D[0], A[1]-D[1]),
                                           math.hypot(B[0]-C[0], B[1]-C[1]),
                                           math.hypot(B[0]-D[0], B[1]-D[1]))
                            if edges_are_collinear(A, B, C, D, MATCHED_EDGE_FUDGE) and min_dist < MATCHED_EDGE_CONNECTION_THRESHOLD:
                                has_match = True
                                break
                        if has_match:
                            break
                    if has_match:
                        sA = world_to_screen(A, camera_offset, zoom, scr)
                        sB = world_to_screen(B, camera_offset, zoom, scr)
                        pygame.draw.line(overlay, outer_color, sA, sB, 6)
                        pygame.draw.line(overlay, inner_color, sA, sB, 3)
            if self.current_highlight:
                r, e, _ = self.current_highlight
                A = r.vertices[e]
                B = r.vertices[(e+1)%len(r.vertices)]
                sA = world_to_screen(A, camera_offset, zoom, scr)
                sB = world_to_screen(B, camera_offset, zoom, scr)
                pygame.draw.line(overlay, outer_color, sA, sB, 6)
                pygame.draw.line(overlay, inner_color, sA, sB, 3)
            if self.box_select and self.start_box:
                cur = screen_to_world(pygame.mouse.get_pos(), camera_offset, zoom, scr)
                pts = [(min(self.start_box[0], cur[0]), min(self.start_box[1], cur[1])),
                       (max(self.start_box[0], cur[0]), min(self.start_box[1], cur[1])),
                       (max(self.start_box[0], cur[0]), max(self.start_box[1], cur[1])),
                       (min(self.start_box[0], cur[0]), max(self.start_box[1], cur[1]))]
                spts = [world_to_screen(p, camera_offset, zoom, scr) for p in pts]
                pygame.draw.polygon(overlay, (0, 255, 255, 128), spts, 1)
        else:
            if self.first_edge:
                r, e, _ = self.first_edge
                A = r.vertices[e]
                B = r.vertices[(e+1)%len(r.vertices)]
                sA = world_to_screen(A, camera_offset, zoom, scr)
                sB = world_to_screen(B, camera_offset, zoom, scr)
                pygame.draw.line(overlay, outer_color, sA, sB, 6)
                pygame.draw.line(overlay, inner_color, sA, sB, 3)
            if self.current_highlight:
                r, e, _ = self.current_highlight
                A = r.vertices[e]
                B = r.vertices[(e+1)%len(r.vertices)]
                sA = world_to_screen(A, camera_offset, zoom, scr)
                sB = world_to_screen(B, camera_offset, zoom, scr)
                pygame.draw.line(overlay, outer_color, sA, sB, 6)
                pygame.draw.line(overlay, inner_color, sA, sB, 3)
            if self.box_select and self.start_box:
                cur = screen_to_world(pygame.mouse.get_pos(), camera_offset, zoom, scr)
                pts = [(min(self.start_box[0], cur[0]), min(self.start_box[1], cur[1])),
                       (max(self.start_box[0], cur[0]), min(self.start_box[1], cur[1])),
                       (max(self.start_box[0], cur[0]), max(self.start_box[1], cur[1])),
                       (min(self.start_box[0], cur[0]), max(self.start_box[1], cur[1]))]
                spts = [world_to_screen(p, camera_offset, zoom, scr) for p in pts]
                pygame.draw.polygon(overlay, (0, 255, 255, 128), spts, 1)
        surf.blit(overlay, (0, 0))

# =============================================================================
# Entities Tool
# =============================================================================
class EntitiesTool(EditorTool):
    desc = "Place and edit entities"
    buttons = ("Left-click: place entity / drag entity\n"
               "Right-click: delete entity\nEsc: cancel")
    help_text = ("Entities Tool Help:\n"
                 "• Use the ribbon below to select an entity type.\n"
                 "• Left-click in a room to place an instance of the selected entity.\n"
                 "• Click and drag an entity to move it. Hovering shows a yellow highlight; dragging shows green.\n"
                 "• Right-click an entity to delete it.\n"
                 "• When dragging, releasing the mouse outside any room deletes the entity; releasing inside a different room moves it.")
    last_selected_entity_class = None

    def __init__(self):
        super().__init__()
        from main import get_all_entity_subclasses
        self.entity_classes = get_all_entity_subclasses()
        if EntitiesTool.last_selected_entity_class is not None:
            self.selected_entity_class = EntitiesTool.last_selected_entity_class
        else:
            self.selected_entity_class = None
            for cls in self.entity_classes:
                if cls.__name__ == "Player":
                    self.selected_entity_class = cls
                    break
            if self.selected_entity_class is None and self.entity_classes:
                self.selected_entity_class = self.entity_classes[0]
        self.dragging_entity = None  # Tuple: (entity, parent_room, offset)
        self.hovered_entity = None
        self.ribbon_height = 70  # Height of the entities ribbon
        self.entity_button_size = (60, 60)
        self.entity_button_margin = 10
        self.right_click_candidate = None
        self.preview_cache = {}
        # Create a dummy room for instantiation so we can use the actual draw method.
        class DummyRoom:
            pass
        dummy_room = DummyRoom()
        dummy_room.entities = []
        for cls in self.entity_classes:
            try:
                instance = cls(dummy_room, np.array([0.0, 0.0]))
            except Exception as e:
                print(f"Failed to instantiate {cls.__name__}: {e}")
                continue
            if instance in dummy_room.entities:
                dummy_room.entities.remove(instance)
            preview = pygame.Surface(self.entity_button_size, pygame.SRCALPHA)
            scale = 0.8
            tx = self.entity_button_size[0] / 2
            ty = self.entity_button_size[1] / 2
            T = np.array([[scale, 0, tx],
                          [0, scale, ty],
                          [0, 0, 1]])
            instance.draw(preview, T)
            self.preview_cache[cls] = preview

    def what_is_mouse_over(self, world, pt):
        room = get_polygon_under_cursor(world, pt)
        if room:
            for entity in room.entities:
                d = math.hypot(pt[0] - entity.pos[0], pt[1] - entity.pos[1])
                if d < 15/zoom:
                    return ('entity', (entity, room))
        return None

    def handle_event(self, event, world, scr):
        mouse_pos = event.pos if hasattr(event, 'pos') else None
        if event.type == pygame.MOUSEBUTTONDOWN and mouse_pos:
            # Check if click is in the entities ribbon area (below main ribbon)
            if mouse_pos[1] < 80 + self.ribbon_height:
                self.handle_ribbon_click(event, scr)
                return
            if event.button == 1:
                wp = screen_to_world(mouse_pos, camera_offset, zoom, scr)
                room = get_polygon_under_cursor(world, wp)
                if room:
                    for entity in room.entities:
                        if math.hypot(wp[0] - entity.pos[0], wp[1] - entity.pos[1]) < 15/zoom:
                            offset = (entity.pos[0] - wp[0], entity.pos[1] - wp[1])
                            self.dragging_entity = (entity, room, offset)
                            return
                    if self.selected_entity_class:
                        # The Entity constructor already adds the entity to the parent room,
                        # so we don't need to append it again
                        new_entity = self.selected_entity_class(room, wp)
                        # Set parent_room if it has that attribute (redundant but kept for safety)
                        if hasattr(new_entity, 'parent_room'):
                            new_entity.parent_room = room
                        # Note: removed the redundant room.entities.append(new_entity) line
                        undo_manager.record_state(world)
            elif event.button == 3:
                wp = screen_to_world(mouse_pos, camera_offset, zoom, scr)
                room = get_polygon_under_cursor(world, wp)
                if room:
                    for entity in room.entities:
                        if math.hypot(wp[0] - entity.pos[0], wp[1] - entity.pos[1]) < 15/zoom:
                            self.right_click_candidate = (entity, room)
                            break
        elif event.type == pygame.MOUSEMOTION and mouse_pos:
            if self.dragging_entity:
                wp = screen_to_world(mouse_pos, camera_offset, zoom, scr)
                entity, orig_room, offset = self.dragging_entity
                entity.pos = (wp[0] + offset[0], wp[1] + offset[1])
            else:
                wp = screen_to_world(mouse_pos, camera_offset, zoom, scr)
                room = get_polygon_under_cursor(world, wp)
                self.hovered_entity = None
                if room:
                    for entity in room.entities:
                        if math.hypot(wp[0] - entity.pos[0], wp[1] - entity.pos[1]) < 15/zoom:
                            self.hovered_entity = (entity, room)
                            break
        elif event.type == pygame.MOUSEBUTTONUP and mouse_pos:
            if event.button == 1 and self.dragging_entity:
                entity, orig_room, offset = self.dragging_entity
                wp = screen_to_world(mouse_pos, camera_offset, zoom, scr)
                new_room = get_polygon_under_cursor(world, wp)
                if new_room:
                    if new_room != orig_room:
                        if entity in orig_room.entities:
                            orig_room.entities.remove(entity)
                        new_room.entities.append(entity)
                        if hasattr(entity, 'parent_room'):
                            entity.parent_room = new_room
                else:
                    if entity in orig_room.entities:
                        orig_room.entities.remove(entity)
                self.dragging_entity = None
                undo_manager.record_state(world)
            elif event.button == 3:
                if self.right_click_candidate:
                    wp = screen_to_world(mouse_pos, camera_offset, zoom, scr)
                    candidate_entity, candidate_room = self.right_click_candidate
                    if math.hypot(wp[0] - candidate_entity.pos[0], wp[1] - candidate_entity.pos[1]) < 15/zoom:
                        if candidate_entity in candidate_room.entities:
                            candidate_room.entities.remove(candidate_entity)
                        undo_manager.record_state(world)
                    self.right_click_candidate = None
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.dragging_entity = None
                self.right_click_candidate = None

    def handle_ribbon_click(self, event, scr):
        mx, my = event.pos
        if not (80 <= my <= 80 + self.ribbon_height):
            return
        buttons = []
        x = 10
        y = 80 + self.entity_button_margin
        for cls in self.entity_classes:
            rect = pygame.Rect(x, y, self.entity_button_size[0], self.entity_button_size[1])
            buttons.append((cls, rect))
            x += self.entity_button_size[0] + self.entity_button_margin
        for cls, rect in buttons:
            if rect.collidepoint((mx, my)):
                self.selected_entity_class = cls
                EntitiesTool.last_selected_entity_class = cls
                break

    def draw(self, surf, world, scr):
        overlay = pygame.Surface(scr, pygame.SRCALPHA)
        if self.hovered_entity:
            entity, _ = self.hovered_entity
            sp = world_to_screen(entity.pos, camera_offset, zoom, scr)
            pygame.draw.circle(overlay, (255, 255, 0, 128), (int(sp[0]), int(sp[1])), int(20 * zoom))
        if self.dragging_entity:
            entity, _, _ = self.dragging_entity
            sp = world_to_screen(entity.pos, camera_offset, zoom, scr)
            pygame.draw.circle(overlay, (0, 255, 0, 128), (int(sp[0]), int(sp[1])), int(20 * zoom))
        ribbon_rect = pygame.Rect(0, 80, scr[0], self.ribbon_height)
        pygame.draw.rect(overlay, (50, 50, 50, 220), ribbon_rect)
        x = 10
        y = 80 + self.entity_button_margin
        mouse_pos = pygame.mouse.get_pos()
        for cls in self.entity_classes:
            btn_rect = pygame.Rect(x, y, self.entity_button_size[0], self.entity_button_size[1])
            color = BUTTON_ACTIVE_COLOR if cls == self.selected_entity_class else BUTTON_NORMAL_COLOR
            if btn_rect.collidepoint(mouse_pos):
                color = BUTTON_HOVER_COLOR
            pygame.draw.rect(overlay, color, btn_rect)
            overlay.blit(self.preview_cache[cls], (x, y - 6))
            txt = FONT_SMALL.render(cls.__name__, True, (0, 0, 0))
            txt_rect = txt.get_rect(midbottom=(x + self.entity_button_size[0] // 2, y + self.entity_button_size[1] - 2))
            overlay.blit(txt, txt_rect)
            x += self.entity_button_size[0] + self.entity_button_margin
        surf.blit(overlay, (0, 0))


# =============================================================================
# Move Tool
# =============================================================================
class MoveTool(EditorTool):
    desc = "Move many rooms together"
    buttons = ("Left-click: select & drag room(s)\n"
               "Right-click: toggle selection\n"
               "Drag empty space: box select")
    help_text = (
        "Move Tool Help:\n"
        "• Left-click a room to select it; if Shift is held, add to selection.\n"
        "• Dragging moves all selected rooms together with grid snapping (based on initial drag position).\n"
        "• Right-click toggles selection of a room.\n"
        "• Box-select (drag on empty space) selects rooms (clearing previous selection unless Shift is held).\n"
        "• Middle-click on a room (or anywhere over it) splits a concave room into two convex parts."
    )

    def __init__(self):
        super().__init__()
        self.selected_rooms = []
        self.drag_start = None
        self.initial_positions = {}  # room -> (x,y)
        self.box_select = False
        self.box_start = None

    def what_is_mouse_over(self, world, pt):
        return get_polygon_under_cursor(world, pt)

    def handle_event(self, event, world, scr):
        mods = pygame.key.get_mods()
        shift = bool(mods & pygame.KMOD_SHIFT)
        if hasattr(event, 'pos'):
            wp = screen_to_world(event.pos, camera_offset, zoom, scr)
            self.update_highlight(world, wp)
        if event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:
                wp = screen_to_world(event.pos, camera_offset, zoom, scr)
                room = self.what_is_mouse_over(world, wp)
                if room:
                    # If already selected, leave selection intact; otherwise, update it.
                    if room not in self.selected_rooms:
                        if not shift:
                            self.selected_rooms = [room]
                        else:
                            self.selected_rooms.append(room)
                    self.drag_start = wp
                    self.initial_room_vertices = {r: [v for v in r.vertices] for r in self.selected_rooms}
                else:
                    self.box_select = True
                    self.box_start = wp
            elif event.button == 3:
                wp = screen_to_world(event.pos, camera_offset, zoom, scr)
                room = self.what_is_mouse_over(world, wp)
                if room:
                    if room in self.selected_rooms:
                        self.selected_rooms.remove(room)
                    else:
                        self.selected_rooms.append(room)
            elif event.button == 2:
                # Universal room splitting on middle-click
                wp = screen_to_world(event.pos, camera_offset, zoom, scr)
                room = get_polygon_under_cursor(world, wp)
                if room:
                    parts = fix_room(room, world)
                    if parts:
                        world.rooms.remove(room)
                        world.rooms.extend(parts)
                        # Reassign connections: for simplicity, connect any connection to the first new room.
                        for r in world.rooms:
                            for ei, conn in list(r.connections.items()):
                                if conn[0] == room.id:
                                    r.connections[ei] = (parts[0].id, 0)
                        undo_manager.record_state(world)
        elif event.type == pygame.MOUSEMOTION:
            if self.drag_start and self.selected_rooms:
                wp = screen_to_world(event.pos, camera_offset, zoom, scr)
                dx = wp[0] - self.drag_start[0]
                dy = wp[1] - self.drag_start[1]
                if SNAP_TO_GRID:
                    dx = round(dx / GRID_SIZE) * GRID_SIZE
                    dy = round(dy / GRID_SIZE) * GRID_SIZE
                for r in self.selected_rooms:
                    initial = self.initial_room_vertices[r]
                    r.vertices = [(v[0] + dx, v[1] + dy) for v in initial]
        elif event.type == pygame.MOUSEBUTTONUP:
            if event.button == 1:
                if self.box_select:
                    wp = screen_to_world(event.pos, camera_offset, zoom, scr)
                    rect = pygame.Rect(min(self.box_start[0], wp[0]),
                                       min(self.box_start[1], wp[1]),
                                       abs(wp[0] - self.box_start[0]),
                                       abs(wp[1] - self.box_start[1]))
                    dx = wp[0] - self.box_start[0]
                    dy = wp[1] - self.box_start[1]
                    mode = "inclusive" if (dx >= 0 and dy >= 0) else ("exclusive" if (dx <= 0 and dy <= 0) else "inclusive")
                    rooms = self.box_select_rooms(world, rect, mode)
                    if not shift:
                        self.selected_rooms = rooms
                    else:
                        for r in rooms:
                            if r not in self.selected_rooms:
                                self.selected_rooms.append(r)
                    self.box_select = False
                    self.box_start = None
                    self.drag_start = None
                    undo_manager.record_state(world)
                else:
                    self.drag_start = None
                    undo_manager.record_state(world)
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.selected_rooms = []
                self.drag_start = None
                self.box_select = False

    def draw(self, surf, world, scr):
        overlay = pygame.Surface(scr, pygame.SRCALPHA)
        for r in self.selected_rooms:
            r.draw_highlight(overlay, camera_offset, zoom, scr, "selected")
        if self.box_select and self.box_start:
            wp = screen_to_world(pygame.mouse.get_pos(), camera_offset, zoom, scr)
            rect = pygame.Rect(min(self.box_start[0], wp[0]),
                               min(self.box_start[1], wp[1]),
                               abs(wp[0] - self.box_start[0]),
                               abs(wp[1] - self.box_start[1]))
            dx = wp[0] - self.box_start[0]
            dy = wp[1] - self.box_start[1]
            mode = "inclusive" if (dx >= 0 and dy >= 0) else ("exclusive" if (dx <= 0 and dy <= 0) else "inclusive")
            preselect = self.box_select_rooms(world, rect, mode)
            for r in preselect:
                if r not in self.selected_rooms:
                    r.draw_highlight(overlay, camera_offset, zoom, scr, "hover")
            tl = world_to_screen((rect.x, rect.y), camera_offset, zoom, scr)
            br = world_to_screen((rect.x + rect.width, rect.y + rect.height), camera_offset, zoom, scr)
            srect = pygame.Rect(tl, (br[0] - tl[0], br[1] - tl[1]))
            if mode == "exclusive":
                self.draw_dashed_rect(overlay, srect, (0, 255, 255))
            else:
                pygame.draw.rect(overlay, (0, 255, 255), srect, 1)
        elif self.current_highlight and not self.box_select:
            self.current_highlight.draw_highlight(overlay, camera_offset, zoom, scr, "hover")
        surf.blit(overlay, (0, 0))
    def draw_dashed_rect(self, surf, rect, color, dash_length=5):
        x, y, w, h = rect
        self.draw_dashed_line(surf, (x, y), (x+w, y), color, dash_length)
        self.draw_dashed_line(surf, (x, y+h), (x+w, y+h), color, dash_length)
        self.draw_dashed_line(surf, (x, y), (x, y+h), color, dash_length)
        self.draw_dashed_line(surf, (x+w, y), (x+w, y+h), color, dash_length)
    def draw_dashed_line(self, surf, start, end, color, dash_length=5):
        x1, y1 = start; x2, y2 = end
        dx = x2 - x1; dy = y2 - y1
        distance = math.hypot(dx, dy)
        dash_count = int(distance / dash_length)
        for i in range(dash_count):
            start_pos = (x1 + dx * (i/dash_count), y1 + dy * (i/dash_count))
            end_pos = (x1 + dx * ((i+0.5)/dash_count), y1 + dy * ((i+0.5)/dash_count))
            pygame.draw.line(surf, color, start_pos, end_pos, 1)



# =============================================================================
# Polygon Partitioning (Room Splitting)
# =============================================================================
def fix_room_by_chord(room, world):
    verts = room.vertices; n = len(verts)
    def is_reflex(i):
        prev = verts[(i-1)%n]; curr = verts[i]; nxt = verts[(i+1)%n]
        return (curr[0]-prev[0])*(nxt[1]-prev[1]) - (curr[1]-prev[1])*(nxt[0]-prev[0]) < 0
    def segments_intersect(A, B, C, D):
        def ccw(P, Q, R): return (R[1]-P[1])*(Q[0]-P[0]) > (Q[1]-P[1])*(R[0]-P[0])
        return (ccw(A, C, D) != ccw(B, C, D)) and (ccw(A, B, C) != ccw(A, B, D))
    def chord_valid(i, j):
        A, B = verts[i], verts[j]
        for k in range(n):
            k2 = (k+1)%n
            if k in (i, j) or k2 in (i, j): continue
            if segments_intersect(A, B, verts[k], verts[k2]):
                return False
        mid = ((A[0]+B[0])/2, (A[1]+B[1])/2)
        return point_in_polygon(mid, verts)
    for i in range(n):
        if is_reflex(i):
            for j in range(i+2, n if i > 0 else n-1):
                if chord_valid(i, j):
                    poly1 = verts[i:j+1]
                    poly2 = verts[j:] + verts[:i+1]
                    new_room1 = EditorRoom(poly1)
                    new_room2 = EditorRoom(poly2)
                    old_conns = room.connections.copy()
                    for old_edge_idx, conn in old_conns.items():
                        A_old = verts[old_edge_idx]
                        B_old = verts[(old_edge_idx+1)%n]
                        old_mid = ((A_old[0]+B_old[0])/2, (A_old[1]+B_old[1])/2)
                        idx1, d1 = find_closest_edge_index(old_mid, new_room1.vertices)
                        idx2, d2 = find_closest_edge_index(old_mid, new_room2.vertices)
                        # Only assign if the distance is within a tolerance.
                        if d1 <= d2 and d1 < 30:
                            new_room1.connections[idx1] = conn
                            target = next((r for r in world.rooms if r.id == conn[0]), None)
                            if target and conn[1] in target.connections and target.connections[conn[1]][0] == room.id:
                                target.connections[conn[1]] = (room.id, idx1)
                        elif d2 < 30:
                            new_room2.connections[idx2] = conn
                            target = next((r for r in world.rooms if r.id == conn[0]), None)
                            if target and conn[1] in target.connections and target.connections[conn[1]][0] == room.id:
                                target.connections[conn[1]] = (room.id, idx2)
                    # The chord edge is the new shared edge; we set it explicitly.
                    chord_idx1 = len(new_room1.vertices) - 1
                    chord_idx2 = len(new_room2.vertices) - 1
                    new_room1.connections[chord_idx1] = (new_room2.id, chord_idx2)
                    new_room2.connections[chord_idx2] = (new_room1.id, chord_idx1)
                    return [new_room1, new_room2]
    return None


def fix_room_by_circular(room, world):
    verts = room.vertices; n = len(verts)
    L = [math.hypot(verts[(i+1)%n][0]-verts[i][0], verts[(i+1)%n][1]-verts[i][1]) for i in range(n)]
    total = sum(L)
    R_low = max(L)/2
    R_high = total/(2*math.pi) if total/(2*math.pi) > R_low else R_low*2
    def f(R):
        s = 0
        for length in L:
            val = length/(2*R)
            if val > 1: return float('inf')
            s += 2*math.asin(val)
        return s
    for _ in range(50):
        R_mid = (R_low+R_high)/2
        if f(R_mid) > 2*math.pi: R_low = R_mid
        else: R_high = R_mid
    R = (R_low+R_high)/2
    angles = [2*math.asin(length/(2*R)) for length in L]
    cum_angles = [0]
    for angle in angles[:-1]:
        cum_angles.append(cum_angles[-1]+angle)
    cx = sum(v[0] for v in verts)/n; cy = sum(v[1] for v in verts)/n
    new_verts = [(cx+R*math.cos(theta), cy+R*math.sin(theta)) for theta in cum_angles]
    new_room = EditorRoom(new_verts)
    for old_edge_idx, conn in room.connections.items():
        A_old = verts[old_edge_idx]
        B_old = verts[(old_edge_idx+1)%n]
        old_mid = ((A_old[0]+B_old[0])/2, (A_old[1]+B_old[1])/2)
        new_idx, d = find_closest_edge_index(old_mid, new_room.vertices)
        if d < 30:
            new_room.connections[new_idx] = conn
            target = next((r for r in world.rooms if r.id == conn[0]), None)
            if target and conn[1] in target.connections and target.connections[conn[1]][0] == room.id:
                target.connections[conn[1]] = (room.id, new_idx)
    return new_room


def fix_room(room, world):
    parts = fix_room_by_chord(room, world)
    return parts if parts else [fix_room_by_circular(room, world)]

# =============================================================================
# UI Helper Functions: Toolbar and Hotkey Guide
# =============================================================================
def draw_tool_ribbon(surf, current_key, tool_keys, scr, undo_mgr, status_text, tool_desc, btn_help):
    ribbon_height = 80
    ribbon = pygame.Surface((scr[0], ribbon_height), pygame.SRCALPHA)
    ribbon.fill((50, 50, 50, 220))
    btn_width = 100
    tool_buttons = {}
    for i, key in enumerate(tool_keys):
        rect = (10 + i * (btn_width + 10), 8, btn_width, 30)
        btn = Button(rect, key.capitalize(), callback=lambda k=key: None, toggle=True, active=(key == current_key))
        tool_buttons[key] = btn
        btn.draw(ribbon)
    btn_size = (40, 24)
    undo_btn = Button((scr[0] - btn_size[0] - 10, 8, btn_size[0], btn_size[1]), "Undo", callback=lambda: None)
    redo_btn = Button((scr[0] - btn_size[0] - 10, 8 + btn_size[1] + 4, btn_size[0], btn_size[1]), "Redo", callback=lambda: None)
    undo_btn.draw(ribbon)
    redo_btn.draw(ribbon)
    desc_font = FONT_SMALL
    desc_text = desc_font.render(tool_desc, True, (255, 255, 255))
    ribbon.blit(desc_text, (10, 40))
    start_x = 10 + len(tool_keys) * (btn_width + 10) + 20
    status_font = FONT_SMALL
    txt_status = status_font.render(status_text, True, (255, 255, 255))
    ribbon.blit(txt_status, (start_x, 55))
    help_font = FONT_HELP
    help_x = start_x + txt_status.get_width() + 20
    help_y = 8
    for line in btn_help.split("\n"):
        txt_help = help_font.render(line, True, (255, 255, 255))
        ribbon.blit(txt_help, (help_x, help_y))
        help_y += txt_help.get_height()
        if help_y > 55:
            help_x += 200
            help_y = 8
    surf.blit(ribbon, (0, 0))
    return {"tools": tool_buttons, "undo": undo_btn, "redo": redo_btn}

def draw_hotkey_guide(surf, scr, tip):
    font = FONT_SMALL
    overlay = pygame.Surface((scr[0], scr[1] - 80), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 180))
    y = 80 + 8
    for line in tip.split("\n"):
        txt = font.render(line, True, (255, 255, 255))
        overlay.blit(txt, (50, y))
        y += txt.get_height() + 5
    surf.blit(overlay, (0, 0))


# =============================================================================
# Camera Movement and Visual Effects
# =============================================================================
def edge_camera_movement(dt, scr):
    global camera_offset, zoom
    if not EDGE_CAMERA_MOVEMENT or not pygame.mouse.get_focused():
        return
    mx, my = pygame.mouse.get_pos()
    sw, sh = scr
    border = 8
    vec = np.array([0.0, 0.0])
    if mx < border:
        vec[0] = -(border - mx) / border
    elif mx > sw - border:
        vec[0] = (mx - (sw - border)) / border
    if my < border:
        vec[1] = -(border - my) / border
    elif my > sh - border:
        vec[1] = (my - (sh - border)) / border
    if np.linalg.norm(vec) > 0:
        speed = 300
        vec = vec / np.linalg.norm(vec)
        camera_offset += (vec * speed * dt) / zoom


def shake_camera(duration=500, magnitude=10):
    #This doesn't work - there needs to be some global "shake duration left" variable and the main loop can apply
    #the offset, with this it just silently delays - the shake needs to be integrated in to the main draw loop
    global camera_offset
    orig = camera_offset.copy()
    start = pygame.time.get_ticks()
    while pygame.time.get_ticks() - start < duration:
        t = pygame.time.get_ticks() - start
        offset = magnitude * math.sin(t / 50.0)
        camera_offset = orig + np.array([offset, 0])
        pygame.time.delay(16)
        pygame.display.flip()
    camera_offset = orig

def draw_save_warning(surf, concave_count, scr):
    msg = f"Cannot save - there {'is' if concave_count == 1 else 'are'} {concave_count} concave polygon{'s' if concave_count > 1 else ''}."
    text_surface = FONT_SMALL.render(msg, True, (255, 255, 255))
    padding = 10
    btn_width, btn_height = 80, 30
    text_width, text_height = text_surface.get_size()
    box_width = max(text_width + 2 * padding, btn_width + 2 * padding)
    box_height = text_height + btn_height + 3 * padding
    warn_box = pygame.Rect(scr[0] - box_width - 20, scr[1] - box_height - 20, box_width, box_height)
    pygame.draw.rect(surf, (100, 0, 0), warn_box)
    surf.blit(text_surface, (warn_box.x + padding, warn_box.y + padding))
    btn_rect = (warn_box.x + (box_width - btn_width) // 2,
                warn_box.y + text_height + 2 * padding, btn_width, btn_height)
    goto_btn = Button(btn_rect, "Go To", callback=lambda: None)
    goto_btn.draw(surf)
    return goto_btn


# =============================================================================
# Main Editor Loop
# =============================================================================
def draw_tool_ribbon(surf, current_key, tool_keys, scr, undo_mgr, status_text, tool_desc, btn_help):
    ribbon_height = 80
    ribbon = pygame.Surface((scr[0], ribbon_height), pygame.SRCALPHA)
    ribbon.fill((50, 50, 50, 220))
    file_btns = {}
    file_keys = ["load", "save", "save_as", "new"]
    file_labels = {"load": "Load", "save": "Save", "save_as": "Save As", "new": "New"}
    file_btn_width = 80
    file_btn_height = 30
    margin = 10
    x_offset = margin
    for key in file_keys:
        rect = (x_offset, 8, file_btn_width, file_btn_height)
        btn = Button(rect, file_labels[key], callback=lambda: None)
        file_btns[key] = btn
        btn.draw(ribbon)
        x_offset += file_btn_width + margin
    tool_btns = {}
    tool_btn_width = 100
    x_offset += margin
    slugline_x = x_offset
    for key in tool_keys:
        rect = (x_offset, 8, tool_btn_width, 30)
        btn = Button(rect, key.capitalize(), callback=lambda k=key: None,
                     toggle=True, active=(key == current_key))
        tool_btns[key] = btn
        btn.draw(ribbon)
        x_offset += tool_btn_width + margin
    btn_size = (40, 24)
    undo_btn = Button((scr[0] - btn_size[0] - 10, 8, btn_size[0], btn_size[1]),
                      "Undo", callback=lambda: None)
    redo_btn = Button((scr[0] - btn_size[0] - 10, 8 + btn_size[1] + 4,
                       btn_size[0], btn_size[1]), "Redo", callback=lambda: None)
    undo_btn.draw(ribbon)
    redo_btn.draw(ribbon)
    desc_text = FONT_MEDIUM.render(tool_desc, True, (255, 255, 255))
    ribbon.blit(desc_text, (slugline_x, 40))
    start_x = x_offset + 10
    txt_status = FONT_SMALL.render(status_text, True, (255, 255, 255))
    ribbon.blit(txt_status, (start_x, 10))
    help_x = start_x + txt_status.get_width() + 20
    help_y = 8
    for line in btn_help.split("\n"):
        txt_help = FONT_HELP.render(line, True, (255, 255, 255))
        ribbon.blit(txt_help, (help_x, help_y))
        help_y += txt_help.get_height()
        if help_y > 55:
            help_x += 200
            help_y = 8
    surf.blit(ribbon, (0, 0))
    return {"file": file_btns, "tools": tool_btns, "undo": undo_btn, "redo": redo_btn}


def process_window_event(ev):
    global is_resizing, last_resize_time
    if ev.type == pygame.QUIT:
        pygame.quit(); sys.exit()
    if ev.type == pygame.VIDEORESIZE:
        is_resizing = True
        last_resize_time = pygame.time.get_ticks()

def switch_tool(key, tools):
    global current_tool, current_tool_key, tooltip_text
    mapping = {pygame.K_1: "polygon", pygame.K_2: "vertex", pygame.K_3: "connection", pygame.K_4: "entities", pygame.K_5: "move"}
    if key in mapping:
        current_tool_key = mapping[key]
        current_tool = tools[current_tool_key]
        tooltip_text = current_tool.help_text

def handle_save(world, mods):
    global current_save_file, concave_warning
    concave = [r for r in world.rooms if not r.is_convex()]
    if concave:
        shake_camera(500, 10)
        concave_warning = concave
    else:
        concave_warning = None
        if mods & pygame.KMOD_SHIFT:
            fn = ask_save_filename()
            if fn:
                current_save_file = fn
                export_level_to_json(world, GRID_SIZE, SNAP_TO_GRID, EDGE_CAMERA_MOVEMENT, fn)
        else:
            if current_save_file:
                export_level_to_json(world, GRID_SIZE, SNAP_TO_GRID, EDGE_CAMERA_MOVEMENT, current_save_file)
            else:
                fn = ask_save_filename()
                if fn:
                    current_save_file = fn
                    export_level_to_json(world, GRID_SIZE, SNAP_TO_GRID, EDGE_CAMERA_MOVEMENT, fn)

def process_key_event(ev, world, tools):
    mods = pygame.key.get_mods()
    if ev.key == pygame.K_F1:
        global F1_DOCUMENT_ACTIVE
        F1_DOCUMENT_ACTIVE = not F1_DOCUMENT_ACTIVE
    elif ev.key in (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4):
        switch_tool(ev.key, tools)
    elif ev.key == pygame.K_g:
        global SNAP_TO_GRID
        SNAP_TO_GRID = not SNAP_TO_GRID
    elif ev.key == pygame.K_e:
        global EDGE_CAMERA_MOVEMENT
        EDGE_CAMERA_MOVEMENT = not EDGE_CAMERA_MOVEMENT
    elif ev.key in (pygame.K_EQUALS, pygame.K_PLUS):
        global GRID_SIZE
        GRID_SIZE += 5
    elif ev.key == pygame.K_MINUS:
        GRID_SIZE = max(5, GRID_SIZE - 5)
    elif ev.key == pygame.K_z and mods & pygame.KMOD_CTRL:
        world = undo_manager.undo(world)
    elif ev.key == pygame.K_y and mods & pygame.KMOD_CTRL:
        world = undo_manager.redo(world)
    elif ev.key == pygame.K_s:
        handle_save(world, mods)
    return world

def process_mouse_event(ev, world):
    global dragging_camera, last_pan, camera_offset, zoom
    if ev.type == pygame.MOUSEWHEEL:
        zoom *= 1.1 ** ev.y
    elif ev.type == pygame.MOUSEBUTTONDOWN:
        if ev.button == 2:
            wp = screen_to_world(ev.pos, camera_offset, zoom, WINDOW_SIZE)
            r = get_polygon_under_cursor(world, wp)
            if r:
                parts = fix_room(r, world)
                if parts:
                    world.rooms.remove(r)
                    world.rooms.extend(parts)
                    undo_manager.record_state(world)
            else:
                dragging_camera = True
                last_pan = ev.pos
        elif ev.button == 1 and ev.pos[1] < 100:
            process_toolbar_click(ev, world)
    elif ev.type == pygame.MOUSEBUTTONUP:
        if ev.button == 2:
            dragging_camera = False
    elif ev.type == pygame.MOUSEMOTION and dragging_camera:
        dx = (ev.pos[0] - last_pan[0]) / zoom
        dy = (ev.pos[1] - last_pan[1]) / zoom
        camera_offset -= np.array([dx, dy])
        last_pan = ev.pos

def process_toolbar_click(ev, world):
    global current_save_file, concave_warning
    tb = draw_tool_ribbon(screen, current_tool_key, tool_keys, WINDOW_SIZE, undo_manager,
          f"Snap: {'ON' if SNAP_TO_GRID else 'OFF'}, Grid: {GRID_SIZE}, Edge: {'ON' if EDGE_CAMERA_MOVEMENT else 'OFF'}",
          current_tool.desc, current_tool.buttons)
    fb = tb.get("file")
    if fb:
        if fb["load"].collidepoint(ev.pos):
            fn = ask_load_filename()
            if fn:
                undo_manager.record_state(world)
                loaded_world = import_level_from_json(fn)
                world.rooms[:] = loaded_world.rooms
                current_save_file = fn
            return
        if fb["save_as"].collidepoint(ev.pos):
            concave = [r for r in world.rooms if not r.is_convex()]
            if concave:
                shake_camera(500, 10)
                concave_warning = concave
            else:
                concave_warning = None
                fn = ask_save_filename()
                if fn:
                    current_save_file = fn
                    export_level_to_json(world, GRID_SIZE, SNAP_TO_GRID, EDGE_CAMERA_MOVEMENT, fn)
            return
        if fb["save"].collidepoint(ev.pos):
            concave = [r for r in world.rooms if not r.is_convex()]
            if concave:
                shake_camera(500, 10)
                concave_warning = concave
            else:
                concave_warning = None
                if current_save_file:
                    export_level_to_json(world, GRID_SIZE, SNAP_TO_GRID, EDGE_CAMERA_MOVEMENT, current_save_file)
            return
        if fb["new"].collidepoint(ev.pos):
            undo_manager.record_state(world)
            world.rooms.clear()
            current_save_file = None
            return
    for k, btn in tb.get("tools", {}).items():
        if btn.collidepoint(ev.pos):
            tool_key_map = {"polygon": pygame.K_1,
                            "vertex": pygame.K_2,
                            "connection": pygame.K_3,
                            "entities": pygame.K_4,
                            "move": pygame.K_5}
            switch_tool(tool_key_map[k], tools)
            return

def process_event(ev, world, tools):
    consumed = False
    if ev.type in (pygame.QUIT, pygame.VIDEORESIZE):
        process_window_event(ev)
    elif ev.type == pygame.KEYDOWN:
        world = process_key_event(ev, world, tools)
    elif ev.type in (pygame.MOUSEWHEEL, pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION):
        process_mouse_event(ev, world)
        if hasattr(ev, 'pos') and ev.pos[1] < 100:
            consumed = True
    if not consumed:
        current_tool.handle_event(ev, world, WINDOW_SIZE)
    return world

def handle_resize():
    global is_resizing, last_resize_time, WINDOW_SIZE, screen
    if pygame.time.get_ticks() - last_resize_time > 500:
        WINDOW_SIZE = pygame.display.get_window_size()
        screen = pygame.display.set_mode(WINDOW_SIZE, pygame.RESIZABLE)
        is_resizing = False
    else:
        screen.fill((0, 0, 0))
        txt = FONT_LARGE.render("RESIZING...", True, (255, 255, 255))
        screen.blit(txt, txt.get_rect(center=(WINDOW_SIZE[0] // 2, WINDOW_SIZE[1] // 2)))
        pygame.display.flip()

def draw_tooltip(surface, text, scr):
    overlay = pygame.Surface((scr[0], scr[1] - 80), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 180))
    y = 88
    for line in text.split("\n"):
        t = FONT_HELP.render(line, True, (255, 255, 255))
        overlay.blit(t, (50, y))
        y += t.get_height() + 5
    surface.blit(overlay, (0, 0))


def level_editor():
    global WINDOW_SIZE, dragging_camera, last_pan, is_resizing, last_resize_time
    global camera_offset, zoom, current_save_file, F1_DOCUMENT_ACTIVE, screen
    global current_tool_key, current_tool, tooltip_text, concave_warning, tools, tool_keys, SCREEN_CENTER
    screen = pygame.display.set_mode(WINDOW_SIZE, pygame.RESIZABLE)
    clock = pygame.time.Clock()
    world = EditorWorld()
    undo_manager.record_state(world)
    tools = {
        "polygon": PolygonTool(),
        "vertex": VertexTool(),
        "connection": ConnectionTool(),
        "entities": EntitiesTool(),
        "move": MoveTool()
    }
    tool_keys = list(tools.keys())
    current_tool_key = "polygon"
    current_tool = tools[current_tool_key]
    tooltip_text = current_tool.help_text
    dragging_camera = False
    last_pan = None
    concave_warning = None
    while True:
        dt = clock.tick(60) / 1000.0
        SCREEN_CENTER = (WINDOW_SIZE[0] / 2, WINDOW_SIZE[1] / 2)
        for ev in pygame.event.get():
            world = process_event(ev, world, tools)
        if is_resizing:
            handle_resize()
            continue
        edge_camera_movement(dt, WINDOW_SIZE)
        screen.fill((30, 30, 30))
        world.draw(screen, camera_offset, zoom, WINDOW_SIZE)
        current_tool.draw(screen, world, WINDOW_SIZE)
        draw_tool_ribbon(screen, current_tool_key, tool_keys, WINDOW_SIZE, undo_manager,
            f"Snap: {'ON' if SNAP_TO_GRID else 'OFF'}, Grid: {GRID_SIZE}, Edge: {'ON' if EDGE_CAMERA_MOVEMENT else 'OFF'}",
            current_tool.desc, current_tool.buttons)
        if F1_DOCUMENT_ACTIVE:
            draw_tooltip(screen, tooltip_text, WINDOW_SIZE)
        if concave_warning:
            btn = draw_save_warning(screen, len(concave_warning), WINDOW_SIZE)
            if pygame.mouse.get_pressed()[0] and btn.collidepoint(pygame.mouse.get_pos()):
                cx, cy = concave_warning[0].get_center()
                camera_offset = np.array([cx, cy])
                concave_warning = None
        pygame.display.flip()


if __name__ == "__main__":
    level_editor()

