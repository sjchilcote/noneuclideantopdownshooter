import gc
import heapq
import json
import os
from collections import deque, namedtuple
import itertools

import pygame
import numpy as np
import networkx as nx
from dataclasses import dataclass, field
import random
from typing import List, Dict, Tuple, Optional, Set, Union, NamedTuple
from abc import ABC, abstractmethod
import math

from pygame import BLEND_RGBA_MULT

# CollisionInfo for handling collision results
CollisionInfo = namedtuple('CollisionInfo', ['hit_object', 'collision_time'])

# Global draw cache using minimal transform components
_draw_cache: Set[Tuple[int, tuple]] = set()  # (room_id, (x, y, cos_theta))


def get_transform_key(transform: np.ndarray) -> tuple:
    """Get a minimal unique key from a transform matrix by extracting essential components."""
    # Extract x, y translation and cos(theta) for rotation
    x = round(transform[0, 2], 3)
    y = round(transform[1, 2], 3)
    cos_theta = round(transform[0, 0], 3)
    return (x, y, cos_theta)


def clear_draw_cache():
    """Clear the global draw cache."""
    _draw_cache.clear()


# Global debug flags
DRAW_CONNECTED_EDGES = False  # Toggle with F=2
DRAW_ROOM_NUMBERS = False  # Toggle with F3
SHOW_PERFORMANCE = 0  # 0 = off, 1 = print, 2 = print + display; Toggle with F4
DEBUG_VISIBILITY = False # Toggle with F5
VISUALIZE_CONSTRUCTION = False # F7 - Animate the level drawing process, one room segment drawn per frame
UPDATE_ENTITES = True #F9
DEBUG_COLLISIONS = False # Toggle with F6 - Show collision points and remaining movement

EPSILON = np.finfo(float).eps * 2


class Edge:
    """
    Holds connection information for one side of a Room's polygon.
    Each Edge can connect to another Room, specifying which edge
    in the target Room we line up with, plus a 3x3 transform matrix
    that maps from the child Room's coordinates into this Room's.
    """
    def __init__(
        self,
        target_room: Optional["Room"] = None,
        target_edge_idx: Optional[int] = None,
        transform: Optional[np.ndarray] = None
    ):
        self.target_room = target_room
        self.target_edge_idx = target_edge_idx
        self.transform = transform if transform is not None else np.eye(3)

import math, random, numpy as np, pygame
import math, random, numpy as np, pygame


# Assume global constants are defined:
# DEBUG_VISIBILITY, DRAW_CONNECTED_EDGES, DRAW_ROOM_NUMBERS

import math, random, numpy as np, pygame


# Assume global constants are defined elsewhere:
# DEBUG_VISIBILITY, DRAW_CONNECTED_EDGES, DRAW_ROOM_NUMBERS

class Room:
    _next_room_number = 1

    def __init__(self, num_sides: int):
        self.room_number = Room._next_room_number
        Room._next_room_number += 1
        self.num_sides = num_sides
        self.edges = [Edge() for _ in range(num_sides)]
        self.entities = []
        base = -math.pi / 2
        angs = base + np.arange(num_sides) * (2 * math.pi / num_sides)
        r = 50 / np.sin(math.pi / num_sides)
        self.vertices = np.column_stack((r * np.cos(angs), r * np.sin(angs)))
        self.vertices_h = np.hstack((self.vertices, np.ones((num_sides, 1))))
        self.color = (random.randint(20, 235), random.randint(20, 235), random.randint(20, 235))
        self.room_radius = r
        ts = int(r * 2.2)
        gs = 20
        self.grid_size = gs
        self.texture = pygame.Surface((ts, ts), pygame.SRCALPHA)
        offx = int(r) % gs;
        offy = int(r) % gs
        for y in range(-gs, ts + gs, gs):
            for x in range(-gs, ts + gs, gs):
                if ((x + y) // gs) % 2 == 0:
                    rect = pygame.Rect(x + offx, y + offy, gs, gs)
                    pygame.draw.rect(self.texture, self.color + (255,), rect)
        self.scaled_texture = pygame.transform.scale(self.texture, (ts, ts))

    def __repr__(self):
        return f"<Room #{self.room_number}>"

    def get_edge_vertices(self, edge_idx: int):
        start = self.vertices[edge_idx]
        end = self.vertices[(edge_idx + 1) % self.num_sides]
        return tuple(start), tuple(end)

    @staticmethod
    def _angle_between_rays(r1: np.ndarray, r2: np.ndarray) -> float:
        if np.cross(r1, r2) < 0:
            r1, r2 = r2, r1
        a1 = math.atan2(r1[1], r1[0])
        a2 = math.atan2(r2[1], r2[0])
        return abs((a2 - a1 + math.pi) % (2 * math.pi) - math.pi)

    @staticmethod
    def _furthest_vertex_distance(vantage: np.ndarray, verts: np.ndarray) -> float:
        return np.linalg.norm(verts - vantage, axis=1).max()

    @staticmethod
    def _ray_segment_intersect(o: np.ndarray, d: np.ndarray, s: np.ndarray, v: np.ndarray):
        denom = np.cross(d, v)
        if abs(denom) < 1e-9:
            return None
        diff = s - o
        t = np.cross(diff, v) / denom
        u = np.cross(diff, d) / denom
        if t <= 0:
            return None
        return max(0.0, min(1.0, u))

    @staticmethod
    def _compute_edge_frustum_intersection(f_o: np.ndarray, f_bs: np.ndarray, f_be: np.ndarray, e_s: np.ndarray,
                                           e_e: np.ndarray, eps: float = 0.5):
        # Optimized version using scalar math where possible
        ev_x = e_e[0] - e_s[0]
        ev_y = e_e[1] - e_s[1]
        elen_sq = ev_x * ev_x + ev_y * ev_y
        if elen_sq < eps * eps:
            return None

        # Check if frustum origin is on the edge
        diff_x = f_o[0] - e_s[0]
        diff_y = f_o[1] - e_s[1]
        ev_dot_ev = elen_sq
        t = (diff_x * ev_x + diff_y * ev_y) / ev_dot_ev
        if 0 <= t <= 1:
            # Check distance from point to line
            proj_x = diff_x - t * ev_x
            proj_y = diff_y - t * ev_y
            dist_sq = proj_x * proj_x + proj_y * proj_y
            if dist_sq < eps * eps:
                return None

        r1_x = f_bs[0] - f_o[0]
        r1_y = f_bs[1] - f_o[1]
        r2_x = f_be[0] - f_o[0]
        r2_y = f_be[1] - f_o[1]
        
        # Inline cross product for 2D: a x b = a[0]*b[1] - a[1]*b[0]
        def cross2d(ax, ay, bx, by):
            return ax * by - ay * bx
        
        def inside(px, py):
            dx = px - f_o[0]
            dy = py - f_o[1]
            c1 = cross2d(r1_x, r1_y, dx, dy)
            c2 = cross2d(r2_x, r2_y, dx, dy)
            return c1 * c2 <= 0

        ints = []
        if inside(e_s[0], e_s[1]): ints.append(0.0)
        if inside(e_e[0], e_e[1]): ints.append(1.0)
        
        # Inline ray-segment intersection
        for ray_x, ray_y in ((r1_x, r1_y), (r2_x, r2_y)):
            denom = cross2d(ray_x, ray_y, ev_x, ev_y)
            if abs(denom) >= 1e-9:
                diff_x = e_s[0] - f_o[0]
                diff_y = e_s[1] - f_o[1]
                t_ray = cross2d(diff_x, diff_y, ev_x, ev_y) / denom
                u = cross2d(diff_x, diff_y, ray_x, ray_y) / denom
                if t_ray > 0:
                    ints.append(max(0.0, min(1.0, u)))
        
        if not ints:
            return None
        t1, t2 = min(ints), max(ints)
        elen = math.sqrt(elen_sq)
        if (t2 - t1) * elen < eps:
            return None
        mid_x = e_s[0] + ((t1 + t2) / 2) * ev_x
        mid_y = e_s[1] + ((t1 + t2) / 2) * ev_y
        if not inside(mid_x, mid_y):
            return None
        return (t1, t2)

    def draw(self, room_layer: pygame.Surface, entity_layer: pygame.Surface,
             mask_layer1: pygame.Surface, mask_layer2: pygame.Surface,
             entities_mask: pygame.Surface, work_layer: pygame.Surface,
             local_to_screen: np.ndarray, viewpoint: np.ndarray,
             recursion_depth: int = 0, max_recursion_depth: int = 12,
             entry_edge_index: int = None, visible_entry_segment: tuple = None,
             view_cone_rays: tuple = None, wide_angle_threshold_degs: float = 170.0,
             draw_cache: set = None):
        viewport_rect = room_layer.get_rect()
        if draw_cache is None:
            draw_cache = set()

        rooms_to_draw = []
        stack = [(self, local_to_screen, viewpoint, entry_edge_index, visible_entry_segment, view_cone_rays,
                  recursion_depth)]

        while stack:
            room, l2s, vp, eei, ves, vcr, depth = stack.pop()
            #print(f"Considering drawing {room}")
            if depth > max_recursion_depth:
                continue

            # Simplified cache key - just room id and rounded transform position/rotation
            # View cone info causes too many cache misses for minimal visual benefit
            tx, ty = round(l2s[0, 2], 1), round(l2s[1, 2], 1)
            cos_theta = round(l2s[0, 0], 2)
            cache_key = (id(room), tx, ty, cos_theta)

            if cache_key in draw_cache:
                #print(f"Cache hit on #{room.room_number}")
                continue
            draw_cache.add(cache_key)

            full = (eei is None)
            if (not full) and (vcr is not None):
                ang = Room._angle_between_rays(np.array(vcr[0], dtype=float), np.array(vcr[1], dtype=float))
                if math.degrees(ang) > wide_angle_threshold_degs:
                    full = True
            if full:
                vis_reg = room.vertices.copy()
            else:
                s_pt, e_pt = np.array(room.get_edge_vertices(eei)[0]), np.array(room.get_edge_vertices(eei)[1])
                ev = e_pt - s_pt
                f_bs = s_pt + ves[0] * ev
                f_be = s_pt + ves[1] * ev
                r1, r2 = np.array(vcr[0], dtype=float), np.array(vcr[1], dtype=float)
                if np.linalg.norm(r1) > 1e-9: r1 /= np.linalg.norm(r1)
                if np.linalg.norm(r2) > 1e-9: r2 /= np.linalg.norm(r2)
                vant = vp if vp is not None else 0.5 * (f_bs + f_be)
                ext = 10.0
                maxd = Room._furthest_vertex_distance(vant, room.vertices)
                rl = maxd * ext
                vis_reg = np.array([f_bs, f_bs + r1 * rl, f_be + r2 * rl, f_be])

            scr = (l2s @ room.vertices_h.T).T[:, :2]
            x_min, y_min = scr.min(axis=0)
            x_max, y_max = scr.max(axis=0)
            room_rect = pygame.Rect(x_min, y_min, x_max - x_min, y_max - y_min)
            if not viewport_rect.colliderect(room_rect):
                continue

            center_screen = (l2s @ np.array([0, 0, 1]))[:2]
            projected_radius = np.linalg.norm(scr - center_screen, axis=1).max()
            push_children = True
            if projected_radius < 10 and depth > 0:
                push_children = False

            rooms_to_draw.append((room, l2s, vp, full, vis_reg, depth, eei, ves, vcr))

            if push_children:
                for i, edge in enumerate(room.edges):
                    if i == eei:
                        #This is the edge we're looking in through! Obvs. can't look back out through it
                        continue
                    if edge.target_room is None:
                        continue
                    nxt_l2s = l2s @ edge.transform
                    if not hasattr(edge, 'inv_transform'):
                        try:
                            edge.inv_transform = np.linalg.inv(edge.transform)
                        except np.linalg.LinAlgError:
                            continue
                    nxt_inv = edge.inv_transform
                    vp_next = (nxt_inv @ np.array([vp[0], vp[1], 1.0]))[:2]

                    s_pt, e_pt = np.array(room.get_edge_vertices(i)[0]), np.array(room.get_edge_vertices(i)[1])
                    if full:
                        s_next = (nxt_inv @ np.append(s_pt, 1.0))[:2]
                        e_next = (nxt_inv @ np.append(e_pt, 1.0))[:2]
                        new_r1 = e_next - vp_next
                        new_r2 = s_next - vp_next
                        new_ves = (0.0, 1.0)
                        new_vcr = (new_r1, new_r2)
                        new_eei = edge.target_edge_idx
                        stack.append((edge.target_room, nxt_l2s, vp_next, new_eei, new_ves, new_vcr, depth + 1))
                    else:
                        fr = Room._compute_edge_frustum_intersection(np.array(vp), vis_reg[0], vis_reg[-1], s_pt, e_pt)
                        if fr is None:
                            continue
                        vstart, vend = fr
                        child_ves = (1.0 - vend, 1.0 - vstart)
                        vis_p_parent_start = s_pt + vstart * (e_pt - s_pt)
                        vis_p_parent_end = s_pt + vend * (e_pt - s_pt)
                        cp_start = (nxt_inv @ np.append(vis_p_parent_start, 1.0))[:2]
                        cp_end = (nxt_inv @ np.append(vis_p_parent_end, 1.0))[:2]
                        new_r1 = cp_end - vp_next
                        new_r2 = cp_start - vp_next
                        new_vcr = (new_r1, new_r2)
                        new_eei = edge.target_edge_idx
                        stack.append((edge.target_room, nxt_l2s, vp_next, new_eei, child_ves, new_vcr, depth + 1))
                        #print(f"{room}[{i}] -> {edge.target_room}[{edge.target_edge_idx}] - {fr =}")

        for (room, l2s, vp, full, vis_reg, depth, eei, ves, vcr) in rooms_to_draw:
            room_center_screen = l2s @ np.array([0.0, 0.0, 1.0])
            scr = (l2s @ room.vertices_h.T).T[:, :2]
            
            # Calculate bounding rect for this room to limit fill operations
            x_min, y_min = scr.min(axis=0)
            x_max, y_max = scr.max(axis=0)
            pad = 10
            clip_rect = pygame.Rect(int(x_min) - pad, int(y_min) - pad,
                                    int(x_max - x_min) + pad * 2, int(y_max - y_min) + pad * 2)
            clip_rect = clip_rect.clip(viewport_rect)
            
            if clip_rect.width <= 0 or clip_rect.height <= 0:
                continue
            
            # Only clear the region we're drawing to
            work_layer.fill((0, 0, 0, 0), clip_rect)
            
            ts = room.scaled_texture.get_width()
            tx = int(room_center_screen[0] - ts // 2)
            ty = int(room_center_screen[1] - ts // 2)
            work_layer.blit(room.scaled_texture, (tx, ty))
            
            for i, edge in enumerate(room.edges):
                s_coord = scr[i]
                e_coord = scr[(i + 1) % room.num_sides]
                if edge.target_room is None:
                    pygame.draw.line(work_layer, (255, 255, 255), s_coord, e_coord, 4)
                elif DRAW_CONNECTED_EDGES:
                    pygame.draw.line(work_layer, (200, 200, 200), s_coord, e_coord, 1)
                if DEBUG_VISIBILITY and (i == eei) and (ves is not None):
                    vs = np.array(room.vertices[i])
                    ve = np.array(room.vertices[(i + 1) % room.num_sides])
                    if ves[0] > 0:
                        p1 = (l2s @ np.append(vs, 1.0))[:2]
                        p2 = (l2s @ np.append(vs + ves[0] * (ve - vs), 1.0))[:2]
                        pygame.draw.line(entity_layer, (255, 0, 0), p1, p2, 4)
                    if ves[1] < 1:
                        p1 = (l2s @ np.append(vs + ves[1] * (ve - vs), 1.0))[:2]
                        p2 = (l2s @ np.append(ve, 1.0))[:2]
                        pygame.draw.line(entity_layer, (255, 0, 0), p1, p2, 4)
                    p1 = (l2s @ np.append(vs + ves[0] * (ve - vs), 1.0))[:2]
                    p2 = (l2s @ np.append(vs + ves[1] * (ve - vs), 1.0))[:2]
                    pygame.draw.line(entity_layer, (0, 255, 0), p1, p2, 4)
            if DRAW_ROOM_NUMBERS:
                font = pygame.font.Font(None, 28)
                lab = font.render(f"#{room.room_number}", True, (255, 255, 255))
                rct = lab.get_rect()
                rct.center = (room_center_screen[0], room_center_screen[1])
                work_layer.blit(lab, rct)
            
            # Only clear mask regions we need
            mask_layer1.fill((0, 0, 0, 0), clip_rect)
            mask_layer2.fill((0, 0, 0, 0), clip_rect)
            
            room_poly = scr.tolist()
            pygame.draw.polygon(mask_layer1, (255, 255, 255, 255), room_poly)
            if not full:
                frustum_poly = (l2s @ np.hstack((vis_reg, np.ones((vis_reg.shape[0], 1)))).T).T[:, :2]
                if DEBUG_VISIBILITY:
                    pygame.draw.polygon(entity_layer, (0, 0, 255, 64), frustum_poly.tolist())
                else:
                    pygame.draw.polygon(mask_layer2, (255, 255, 255, 255), frustum_poly.tolist())
            else:
                mask_layer2.fill((255, 255, 255, 255), clip_rect)
            mask_layer1.blit(mask_layer2, clip_rect, clip_rect, special_flags=pygame.BLEND_RGBA_MIN)
            work_layer.blit(mask_layer1, clip_rect, clip_rect, special_flags=pygame.BLEND_RGBA_MIN)
            room_layer.blit(work_layer, clip_rect, clip_rect)
            entities_mask.blit(mask_layer1, clip_rect, clip_rect, special_flags=pygame.BLEND_RGBA_MAX)
            for ent in room.entities:
                ent.draw(entity_layer, l2s)

            if VISUALIZE_CONSTRUCTION:
                screen.blit(room_layer, (0, 0))
                import time
                time.sleep(0.1)
                pygame.display.flip()


def get_all_entity_subclasses():
    """Returns a list of all classes that inherit from Entity, directly or indirectly."""

    def get_subclasses(cls):
        # Get immediate subclasses
        subclasses = cls.__subclasses__()
        # For each subclass, recursively get its subclasses
        for subclass in list(subclasses):  # Create a copy of the list to iterate over
            subclasses.extend(get_subclasses(subclass))
        return subclasses

    return [x for x in get_subclasses(Entity) if x.__name__ not in ('Bullet', 'LightningDart')]

class Entity(ABC):
    def __init__(self, parent_room: Room, pos: np.ndarray, direction: np.ndarray = None):
        self.parent_room = parent_room
        self.pos = np.array(pos, dtype=float)  # Position relative to room center
        # Default direction is along +X axis if none provided
        self.direction = np.array([1.0, 0.0]) if direction is None else direction / np.linalg.norm(direction)
        self.velocity = np.zeros(2, dtype=float)
        self.sprite_size = 20  # Size in pixels
        self.max_step_distance = 100.0  # Maximum distance to move in a single step
        self.is_gone = False  # Flag for pending removal

        # Collision properties
        self.collision_radius = self.sprite_size * 0.9  # Slightly smaller than visual size
        self.mass = 1.0  # Default mass for physics calculations

        # Track last room we came from
        self.previous_room = None

        # For debug visualization
        self.collision_points = []  # List of (pos, remaining_movement) tuples

        # Generate random color for entity
        self.color = (
            random.randint(50, 255),
            random.randint(50, 255),
            random.randint(50, 255)
        )

        # Create base sprite vertices (relative to entity position)
        # Front point
        self.sprite_vertices = np.array([
            [self.sprite_size * 1.5, 0],  # Front point
            # Back points (spread apart, making an isosceles triangle)
            [-self.sprite_size * 0.8, self.sprite_size * 0.8],  # Back right
            [-self.sprite_size * 0.8, -self.sprite_size * 0.8]  # Back left
        ], dtype=float)

        # Add entity to parent room
        parent_room.entities.append(self)

    def point_at(self, target_pos: np.ndarray):
        """Point entity at a target position in the same room's coordinate system."""
        to_target = target_pos - self.pos
        norm = np.linalg.norm(to_target)
        if norm > 1e-10:  # Avoid division by zero
            self.direction = to_target / norm

    def handle_collision(self, other: Union["Entity", Edge], collision_normal: np.ndarray):
        """Handle collision with another entity or edge.
        collision_normal points from other to self.
        Returns True if physics processing should stop (e.g. the entity was a bullet that hit a target and has been
        deleted.)"""
        if isinstance(other, Edge):
            # Basic bounce - reflect velocity about the normal
            self.velocity = self.velocity - 2 * np.dot(self.velocity, collision_normal) * collision_normal
        else:
            # Entity-entity collision using conservation of momentum
            # Calculate relative velocity along normal
            relative_velocity = self.velocity - other.velocity
            vel_along_normal = np.dot(relative_velocity, collision_normal)

            # If entities are moving away from each other, no collision response needed
            if vel_along_normal > 0:
                return False

            # Calculate impulse scalar
            restitution = 0.8  # Coefficient of restitution (bounciness)
            impulse_scalar = -(1 + restitution) * vel_along_normal
            impulse_scalar /= (1/self.mass + 1/other.mass)

            # Apply impulse
            impulse = impulse_scalar * collision_normal
            self.velocity += impulse / self.mass
            other.velocity -= impulse / other.mass
            
        return False

    def _get_world_vertices(self) -> np.ndarray:
        """Get entity vertices in world space (relative to room)."""
        # Calculate rotation matrix from direction vector
        rotation_matrix = np.array([
            [self.direction[0], -self.direction[1]],
            [self.direction[1], self.direction[0]]
        ])

        # Rotate vertices and add entity position
        return (rotation_matrix @ self.sprite_vertices.T).T + self.pos

    def _check_polygon_collision(self, other: "Entity") -> Tuple[bool, Optional[np.ndarray]]:
        """Check if polygons of two entities intersect.
        Returns (collision_detected, collision_normal)."""
        # Get vertices in world space
        self_vertices = self._get_world_vertices()
        other_vertices = other._get_world_vertices()

        # Use separating axis theorem (SAT) to check collision
        # For each edge of both polygons, project both polygons onto the normal of that edge
        # If there's a gap in any projection, there's no collision

        # Check edges of self
        for i in range(len(self_vertices)):
            edge = self_vertices[(i + 1) % len(self_vertices)] - self_vertices[i]
            normal = np.array([-edge[1], edge[0]])  # Perpendicular to edge
            normal = normal / np.linalg.norm(normal)  # Normalize

            self_min = float('inf')
            self_max = float('-inf')
            other_min = float('inf')
            other_max = float('-inf')

            # Project self vertices
            for vertex in self_vertices:
                projection = np.dot(vertex, normal)
                self_min = min(self_min, projection)
                self_max = max(self_max, projection)

            # Project other vertices
            for vertex in other_vertices:
                projection = np.dot(vertex, normal)
                other_min = min(other_min, projection)
                other_max = max(other_max, projection)

            # Check for gap
            if self_min > other_max or other_min > self_max:
                return False, None

        # Check edges of other
        for i in range(len(other_vertices)):
            edge = other_vertices[(i + 1) % len(other_vertices)] - other_vertices[i]
            normal = np.array([-edge[1], edge[0]])  # Perpendicular to edge
            normal = normal / np.linalg.norm(normal)  # Normalize

            self_min = float('inf')
            self_max = float('-inf')
            other_min = float('inf')
            other_max = float('-inf')

            # Project self vertices
            for vertex in self_vertices:
                projection = np.dot(vertex, normal)
                self_min = min(self_min, projection)
                self_max = max(self_max, projection)

            # Project other vertices
            for vertex in other_vertices:
                projection = np.dot(vertex, normal)
                other_min = min(other_min, projection)
                other_max = max(other_max, projection)

            # Check for gap
            if self_min > other_max or other_min > self_max:
                return False, None

        # If we get here, there's a collision
        # Use vector between centers as collision normal
        collision_normal = self.pos - other.pos
        norm = np.linalg.norm(collision_normal)
        if norm > 1e-10:
            collision_normal = collision_normal / norm
        else:
            # If entities are at same position, use arbitrary normal
            collision_normal = np.array([1.0, 0.0])

        return True, collision_normal

    def _check_entity_collisions(self, new_pos: np.ndarray) -> Tuple[np.ndarray, Optional[CollisionInfo]]:
        """Check for collisions with other entities.
        Returns (collision_position, collision_info)."""
        # Store original position
        original_pos = self.pos
        # Temporarily update position for collision checks
        self.pos = new_pos

        for entity in self.parent_room.entities:
            if entity is self:
                continue

            # Quick circle collision check first
            dist = np.linalg.norm(self.pos - entity.pos)
            if dist >= self.collision_radius + entity.collision_radius:
                continue

            # More precise polygon collision check
            collision, normal = self._check_polygon_collision(entity)
            if collision:
                # Restore original position
                self.pos = original_pos

                # Calculate movement vector and distance
                movement = new_pos - original_pos
                movement_dist = np.linalg.norm(movement)

                # Calculate collision position - point of first contact
                # Instead of assuming halfway, we calculate more precisely
                # For now, a simple approximation based on radii
                penetration_dist = (self.collision_radius + entity.collision_radius) - dist
                collision_ratio = 1.0

                if movement_dist > 0:
                    # How far along our movement path did we collide?
                    # Move back by penetration amount along movement direction
                    # Plus a little fudge factor to make sure we don't collide again
                    penetration_dist *= 1.5
                    collision_ratio = max(0.0, min(1.0, (movement_dist - penetration_dist) / movement_dist))

                collision_pos = original_pos + movement * collision_ratio

                # Handle collision physics
                was_removed = self.handle_collision(entity, normal)
                if was_removed:
                    return collision_pos, None
                if entity in self.parent_room.entities:  # Check if other entity still exists
                    entity.handle_collision(self, -normal)  # Opposite normal for other entity

                # Return collision information
                return collision_pos, CollisionInfo(entity, 0.5)

        # Restore original position if no collision
        self.pos = original_pos
        return new_pos, None

    def _handle_edge_collisions(self, new_pos: np.ndarray) -> Tuple[np.ndarray, Optional[CollisionInfo]]:
        """Handle collisions with room edges.
        Returns:
            Tuple of (final_position, collision_info)
            - final_position is either new_pos, a bounced position, or a transformed position
            - collision_info is None if no collision or room transition, or CollisionInfo with hit details
        """
        import time
        start_time = time.time()
        
        vertices = self.parent_room.vertices
        num_edges = len(vertices)

        original_new_pos = new_pos
        movement = new_pos - self.pos
        movement_dist = np.linalg.norm(movement)

        # For each edge in the room
        for i in range(num_edges):
            edge = self.parent_room.edges[i]
            start = np.array(vertices[i])
            end = np.array(vertices[(i + 1) % num_edges])

            # Calculate edge vector and normal
            edge_vec = end - start
            edge_length = np.linalg.norm(edge_vec)
            edge_dir = edge_vec / edge_length
            edge_normal = np.array([-edge_dir[1], edge_dir[0]])  # Rotate 90° CCW

            # Vector from edge start to current position
            to_pos = new_pos - start

            # Calculate signed distance to edge line
            dist = np.dot(to_pos, edge_normal)
            old_dist = np.dot(self.pos - start, edge_normal)

            # Project position onto edge line
            proj = new_pos - dist * edge_normal
            proj_param = np.dot(proj - start, edge_dir)

            # Check if we've crossed this edge
            if dist < 0 <= proj_param <= edge_length + 1:
                collision_time = time.time() - start_time
                if collision_time > 0.0005:  # Only print if took more than 0.5ms
                    print(f"Edge collision check took {collision_time*1000:.2f}ms")
                
                if edge.target_room is not None:
                    # Block transition if we just came from this room
                    if edge.target_room == self.previous_room:
                        continue

                    # Transfer to new room and get transformed position
                    return self._transfer_to_room(edge.target_room, edge.transform), None
                else:
                    # Solid wall - bounce
                    # Calculate time of collision (fraction of movement completed)
                    collision_time = old_dist / (old_dist - dist)
                    
                    # Move to collision point
                    collision_pos = self.pos + movement * collision_time
                    
                    # Handle the bounce
                    self.handle_collision(edge, edge_normal)

                    # Return collision point and info
                    return collision_pos, CollisionInfo(edge, collision_time)

        end_time = time.time() - start_time
        if end_time > 0.001:  # Only print if took more than 1ms
            print(f"Edge collision checks took {end_time*1000:.2f}ms for {num_edges} edges")
        
        # No collision detected - return original position
        return new_pos, None

    def update(self, dt: float):
        """Update entity position and handle collisions.
        For high-speed entities, movement is broken into smaller steps to avoid missing collisions."""
        import time
        
        if self not in self.parent_room.entities:
            print(f"WHAT THE FUCK??? {self = } not in self.parent_room.entities - {self.velocity = }")
            return
        
        start_time = time.time()
        
        # Clear previous collision points
        self.collision_points = []
            
        # Calculate total intended movement
        total_movement = self.velocity * dt
        total_distance = np.linalg.norm(total_movement)
        
        # Calculate number of steps needed (at least 1)
        num_steps = max(1, math.ceil(total_distance / self.max_step_distance))
        dt_per_step = dt / num_steps
        
        step_start = time.time()
        # Do each step
        for _ in range(num_steps):
            self._update_step(dt_per_step)
        
        total_time = time.time() - start_time
        step_time = time.time() - step_start
        if total_time > 0.001:  # Only print if took more than 1ms
            print(f"Entity update took {total_time*1000:.2f}ms (steps: {num_steps}, step time: {step_time*1000:.2f}ms)")

    def _update_step(self, dt: float):
        """Single step of physics update with collision handling."""
        remaining_time = dt
        iteration = 0
        max_iterations = 10  # Prevent infinite loops

        while remaining_time > 0 and iteration < max_iterations:
            iteration += 1

            # Calculate how far we can move this step
            step_size = remaining_time
            step_movement = self.velocity * step_size

            # Store original position for collision time calculation
            original_position = self.pos.copy()

            # Tentative new position
            new_position = original_position + step_movement

            # First check for entity collisions
            entity_collision_pos, entity_collision = self._check_entity_collisions(new_position)

            if entity_collision is not None:
                # We hit an entity, update position to collision point
                self.pos = entity_collision_pos

                # Store collision point for debug visualization
                self.collision_points.append((entity_collision_pos, self.velocity * remaining_time * (1.0 - entity_collision.collision_time)))

                # If we were removed during collision handling, stop processing
                if self not in self.parent_room.entities:
                    return

                # Calculate refund based on exact collision time
                remaining_time *= (1.0 - entity_collision.collision_time)
                continue

            # Then check edge collisions (walls and transitions)
            edge_collision_pos, edge_collision = self._handle_edge_collisions(new_position)
            self.pos = edge_collision_pos

            # If we hit a wall, continue with remaining time
            if edge_collision is not None:
                # Store collision point for debug visualization
                self.collision_points.append((edge_collision_pos, self.velocity * remaining_time * (1.0 - edge_collision.collision_time)))

                # Calculate refund based on exact collision time
                remaining_time *= (1.0 - edge_collision.collision_time)
            else:
                # No collision or we transitioned rooms, we're done with this step
                remaining_time = 0
                if edge_collision_pos is new_position:  # If we didn't transition rooms
                    self.previous_room = None

    def _transfer_to_room(self, new_room: Room, transform: np.ndarray) -> np.ndarray:
        """Transfer entity to a new room.

        Parameters:
        - new_room: The room we're entering
        - transform: Transform matrix that maps points from new_room's space to old_room's space

        Returns the entity's position in the new room's coordinate system.
        """
        # Remember that we just left this room so we don't "bounce back"
        self.previous_room = self.parent_room

        # Remove from old room's entity list
        try:
            self.parent_room.entities.remove(self)
        except ValueError:
            return self.pos

        # The transform maps new_room -> old_room
        # We want old_room -> new_room
        # So we need to invert the transform
        inv_transform = np.linalg.inv(transform)

        # Convert our current position to the new room's coordinate system
        pos_h = np.array([self.pos[0], self.pos[1], 1.0])
        new_pos = (inv_transform @ pos_h)[:2]

        # Move epsilon units inward towards the center of the room
        towards_center = -new_pos
        norm = np.linalg.norm(towards_center)
        if norm > 1e-10:
            towards_center = towards_center / norm
        else:
            towards_center = np.array([1.0, 0.0])  # Arbitrary direction if at center
        new_pos += towards_center * EPSILON * 2

        # Transform velocity and direction (as vectors, so no translation)
        rot = inv_transform[:2, :2]
        self.velocity = rot @ self.velocity
        self.direction = rot @ self.direction
        # No need to renormalize direction as rotation preserves length

        # Update room reference
        self.parent_room = new_room
        new_room.entities.append(self)

        return new_pos

    def draw(self, screen: pygame.Surface, room_transform: np.ndarray):
        """Draw the entity."""
        # Calculate rotation matrix from direction vector
        # This creates a rotation matrix that would rotate [1,0] to align with direction
        rotation_matrix = np.array([
            [self.direction[0], -self.direction[1]],
            [self.direction[1], self.direction[0]]
        ])

        # Rotate vertices and add entity position
        rotated_vertices = (rotation_matrix @ self.sprite_vertices.T).T + self.pos

        # Transform to screen space (add homogeneous coordinate and apply room transform)
        screen_vertices = []
        for vertex in rotated_vertices:
            pos_homog = np.append(vertex, 1)
            screen_vertex = (room_transform @ pos_homog)[:2]
            screen_vertices.append(tuple(screen_vertex))

        # Draw triangle
        pygame.draw.polygon(screen, self.color, screen_vertices)

class Player(Entity):
    def __init__(self, parent_room: Room, pos: np.ndarray):
        super().__init__(parent_room, pos)
        self.move_force = 300
        self.last_shot_time = 0  # Track when we last fired
        self.shot_cooldown = 0.25  # 4 shots per second
        
        # Lightning cannon properties
        self.last_lightning_time = 0
        self.lightning_cooldown = 30.0  # Special weapon with 30-second cooldown
        #self.lightning_ready_font = pygame.font.Font(None, 28)
        
    def update(self, dt: float):
        """Update player based on input."""
        # Get keyboard input
        keys = pygame.key.get_pressed()

        # Calculate movement direction in screen space based on WASD
        screen_move_dir = np.zeros(2)
        if keys[pygame.K_w]: screen_move_dir[1] -= 1  # Up in screen space
        if keys[pygame.K_s]: screen_move_dir[1] += 1  # Down in screen space
        if keys[pygame.K_a]: screen_move_dir[0] -= 1  # Left in screen space
        if keys[pygame.K_d]: screen_move_dir[0] += 1  # Right in screen space

        # Convert screen space direction to world space by applying inverse camera rotation
        camera_rotation = Camera.get_rotation()
        c, s = np.cos(-camera_rotation), np.sin(-camera_rotation)
        rotation_matrix = np.array([[c, -s], [s, c]])

        # Transform the movement direction to world space
        world_move_dir = screen_move_dir @ rotation_matrix

        # Normalize movement vector if necessary
        if np.any(world_move_dir):
            world_move_dir = world_move_dir / np.linalg.norm(world_move_dir)

        # Apply force (acceleration) rather than directly setting velocity
        acceleration = world_move_dir * self.move_force

        self.velocity += acceleration * dt

        # Optional: Add some friction
        friction = 2  # Adjust this value - smaller = more slippery!
        self.velocity *= (1.0 - friction * dt)

        # Update position using parent class method
        super().update(dt)

        # Update orientation to face mouse
        mouse_pos = pygame.mouse.get_pos()
        self._update_orientation(mouse_pos)

    def try_shoot(self, current_time: float) -> bool:
        """Attempt to shoot. Returns True if shot was fired."""
        if current_time - self.last_shot_time >= self.shot_cooldown:
            self._shoot()
            self.last_shot_time = current_time
            return True
        return False

    def _shoot(self):
        """Create a bullet in the direction the player is facing."""
        bullet_speed = 64000.0
        
        # Calculate spawn position at triangle tip
        # The front vertex of the triangle is at [self.sprite_size * 1.5, 0] in local space
        spawn_offset = self.sprite_size * 1.5
        spawn_pos = self.pos + self.direction * spawn_offset
        
        # Add player velocity to bullet velocity for realistic momentum
        bullet_velocity = self.direction * bullet_speed + self.velocity
        
        Bullet(self.parent_room, spawn_pos, bullet_velocity)

    def _update_orientation(self, mouse_pos: Tuple[int, int]):
        """Update the player's orientation to face the mouse cursor.

        Args:
            mouse_pos: Screen coordinates of the mouse cursor as (x, y)
        """
        # Get inverse of camera transform to map from screen to world space
        inv_camera = np.linalg.inv(Camera.transform)

        # Convert to homogeneous coordinates (add 1 as third component)
        screen_pos_h = np.append(mouse_pos, 1.0)

        # Transform to get world position
        world_pos = (inv_camera @ screen_pos_h)[:2]

        # Point the player at this position
        self.point_at(world_pos)

    def _transfer_to_room(self, new_room: Room, transform: np.ndarray) -> np.ndarray:
        Camera.handle_room_transition(self.parent_room, new_room, transform)
        return super()._transfer_to_room(new_room, transform)

    def try_lightning(self, current_time: float) -> bool:
        """Attempt to fire the lightning cannon. Returns True if shot was fired."""
        if current_time - self.last_lightning_time >= self.lightning_cooldown:
            self._fire_lightning()
            self.last_lightning_time = current_time
            return True
        return False
        
    def _fire_lightning(self):
        """Fire the lightning dart projectile in the direction the player is facing."""
        dart_speed = 800.0  # Much slower than bullets
        
        # Calculate spawn position at triangle tip
        spawn_offset = self.sprite_size * 1.5
        spawn_pos = self.pos + self.direction * spawn_offset
        
        # Add player velocity to dart velocity for realistic momentum
        dart_velocity = self.direction * dart_speed + self.velocity
        
        # Create the lightning dart
        LightningDart(self.parent_room, spawn_pos, dart_velocity)

    def draw(self, screen: pygame.Surface, room_transform: np.ndarray):
        """Draw the player and cooldown indicators."""
        # Draw player body using parent method
        super().draw(screen, room_transform)
        
        # Draw lightning cooldown indicator if not ready
        current_time = pygame.time.get_ticks() / 1000.0
        time_since_lightning = current_time - self.last_lightning_time
        
        if time_since_lightning < self.lightning_cooldown:
            # Get player position in screen space
            pos_h = np.append(self.pos, 1)
            screen_pos = (room_transform @ pos_h)[:2]
            
            # Calculate cooldown percentage
            cooldown_percent = time_since_lightning / self.lightning_cooldown
            
            # Draw cooldown circle around player
            radius = self.sprite_size * 1.8
            angle = 2 * math.pi * cooldown_percent
            
            # Draw background circle (full cooldown)
            pygame.draw.circle(screen, (50, 50, 80), (int(screen_pos[0]), int(screen_pos[1])), int(radius), 2)
            
            # Draw arc showing progress (if any progress has been made)
            if cooldown_percent > 0.01:
                # Create points for the arc
                points = [(screen_pos[0], screen_pos[1])]
                num_segments = max(20, int(30 * cooldown_percent))
                
                for i in range(num_segments + 1):
                    segment_angle = 2 * math.pi * (i / num_segments) * cooldown_percent - math.pi/2
                    x = screen_pos[0] + radius * math.cos(segment_angle)
                    y = screen_pos[1] + radius * math.sin(segment_angle)
                    points.append((x, y))
                
                # Close the arc back to center
                points.append((screen_pos[0], screen_pos[1]))
                
                # Draw the progress arc
                if len(points) > 2:
                    color = (50, 100, 255, 150)
                    pygame.draw.polygon(screen, color, points)
        else:
            # Lightning is ready - draw "READY" indicator above player
            pos_h = np.append(self.pos, 1)
            screen_pos = (room_transform @ pos_h)[:2]
            
            # Draw pulsing "READY" text
            pulse = (math.sin(current_time * 5) + 1) / 2  # 0 to 1 pulsing value
            alpha = int(155 + 100 * pulse)  # 155-255 alpha range
            color = (50, 200, 255, alpha)
            
            # Create text surface with alpha
            #text_surf = self.lightning_ready_font.render("⚡ READY", True, color)
            #text_rect = text_surf.get_rect(center=(screen_pos[0], screen_pos[1] - self.sprite_size * 2.5))
            
            # Create a surface with per-pixel alpha
            #alpha_surf = pygame.Surface(text_surf.get_size(), pygame.SRCALPHA)
            #alpha_surf.fill((255, 255, 255, alpha))
            
            # Blit the text with alpha
            #alpha_surf.blit(text_surf, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
            #screen.blit(alpha_surf, text_rect)

class Bullet(Entity):
    def __init__(self, parent_room: Room, pos: np.ndarray, velocity: np.ndarray):
        super().__init__(parent_room, pos)
        self.velocity = velocity
        self.sprite_size = 5  # Smaller size for bullets
        self.collision_radius = 3  # Even smaller collision radius
        self.color = (255, 255, 0)  # Yellow color
        self.mass = 0.0008  # Very light
        self.max_step_distance = 20.0  # Smaller steps for better collision detection
        self.min_speed = 100.0  # Minimum speed before bullet is removed
        self.initial_pos = pos.copy()  # Store initial firing position
        self.last_drawn_pos = self.initial_pos  # Start trail from firing position
        self.has_drawn = False  # Track if we've drawn at least once
        self.trail_points = [pos.copy()]  # Track positions at each integration step
        self.max_trail_points = 15  # Maximum number of points to keep in trail
        
        # Override sprite vertices to make a small diamond shape
        self.sprite_vertices = np.array([
            [self.sprite_size, 0],
            [0, self.sprite_size/2],
            [-self.sprite_size/2, 0],
            [0, -self.sprite_size/2]
        ], dtype=float)

        # Point in direction of movement
        if np.any(velocity):
            self.direction = velocity / np.linalg.norm(velocity)

    def draw(self, screen: pygame.Surface, room_transform: np.ndarray):
        """Draw the bullet with a trail effect when moving fast."""
        # Get current speed
        speed = np.linalg.norm(self.velocity)
        
        # Draw trail if moving above minimum speed
        if speed >= self.min_speed:
            # Collect all points for the trail in screen space
            trail_points = []
            
            # Add all trail points in order
            for pos in self.trail_points:
                pos_h = np.append(pos, 1)
                trail_points.append(tuple((room_transform @ pos_h)[:2]))
            
            # Add current position
            pos_h = np.append(self.pos, 1)
            trail_points.append(tuple((room_transform @ pos_h)[:2]))
            
            # Draw the trail if we have enough points
            if len(trail_points) > 1:
                pygame.draw.lines(screen, self.color, False, trail_points, self.sprite_size)
            
            # Update last drawn position and mark that we've drawn
            self.last_drawn_pos = self.pos.copy()
            self.has_drawn = True
            
            # Add current position to trail points and maintain maximum length
            self.trail_points.append(self.pos.copy())
            if len(self.trail_points) > self.max_trail_points:
                self.trail_points = self.trail_points[-self.max_trail_points:]
        
        # Draw the bullet itself using parent method
        super().draw(screen, room_transform)

    def _update_step(self, dt: float):
        """Single step of physics update with collision handling."""
        remaining_time = dt
        iteration = 0
        max_iterations = 10  # Prevent infinite loops

        while remaining_time > 0 and iteration < max_iterations:
            iteration += 1

            # Calculate how far we can move this step
            step_size = remaining_time
            step_movement = self.velocity * step_size

            # Store original position for collision time calculation
            original_position = self.pos.copy()

            # Tentative new position
            new_position = original_position + step_movement

            # First check for entity collisions
            entity_collision_pos, entity_collision = self._check_entity_collisions(new_position)

            if entity_collision is not None:
                # We hit an entity, update position to collision point
                self.pos = entity_collision_pos
                # Add collision point to trail
                self.trail_points.append(self.pos.copy())

                # If we were removed during collision handling, stop processing
                if self not in self.parent_room.entities:
                    return

                # Calculate refund based on exact collision time
                remaining_time *= (1.0 - entity_collision.collision_time)
                continue

            # Then check edge collisions (walls and transitions)
            edge_collision_pos, edge_collision = self._handle_edge_collisions(new_position)
            self.pos = edge_collision_pos

            # If we hit a wall, continue with remaining time
            if edge_collision is not None:
                # Add collision point to trail
                self.trail_points.append(self.pos.copy())
                
                # Calculate refund based on exact collision time
                remaining_time *= (1.0 - edge_collision.collision_time)
            else:
                # No collision or we transitioned rooms, we're done with this step
                remaining_time = 0
                if edge_collision_pos is new_position:  # If we didn't transition rooms
                    self.previous_room = None
                    # Add final position to trail
                    self.trail_points.append(self.pos.copy())

    def _transfer_to_room(self, new_room: Room, transform: np.ndarray) -> np.ndarray:
        """Update trail points when transferring rooms."""
        # Transform all trail points to new room's coordinate system
        inv_transform = np.linalg.inv(transform)
        new_trail_points = []
        for pos in self.trail_points:
            pos_h = np.append(pos, 1)
            new_pos = (inv_transform @ pos_h)[:2]
            new_trail_points.append(new_pos)
        self.trail_points = new_trail_points
        
        return super()._transfer_to_room(new_room, transform)

    def handle_collision(self, other: Union["Entity", Edge], collision_normal: np.ndarray):
        """Handle collision with another entity or edge."""
        # First do physics collision for all entities
        super().handle_collision(other, collision_normal)
        
        # Then handle special bullet effects
        if isinstance(other, Enemy):
            # Try to damage the enemy
            if other.take_damage():
                # Enemy was killed, but we continue moving
                pass
                
            # Only mark for removal if we've had a chance to draw at least once
            if self.has_drawn:
                self.is_gone = True
                return True
        elif isinstance(other, Edge):
            # Lose velocity on bounce
            self.velocity *= 0.5
            
            # Remove if too slow and we've drawn at least once
            if np.linalg.norm(self.velocity) < self.min_speed:
                if self.has_drawn:
                    self.is_gone = True
                    return True
        else:
            # For any other collision, remove only if we've drawn
            if self.has_drawn:
                self.is_gone = True
                return True
        
        return False  # Not removed

    def update(self, dt: float):
        """Update bullet position and check for minimum velocity."""
        # Update direction to match velocity
        speed = np.linalg.norm(self.velocity)
        if speed > 0:
            self.direction = self.velocity / speed
            
        # Check if velocity is below minimum threshold
        if speed < self.min_speed and self.has_drawn:
            self.is_gone = True
            return
                
        super().update(dt)

class LightningDart(Entity):
    def __init__(self, parent_room: Room, pos: np.ndarray, velocity: np.ndarray):
        super().__init__(parent_room, pos)
        self.velocity = velocity
        self.sprite_size = 8  # Slightly larger than normal bullets
        self.collision_radius = 5
        self.color = (50, 150, 255)  # Electric blue color
        self.mass = 0.01
        self.max_step_distance = 20.0
        self.min_speed = 50.0  # Minimum speed before removal
        self.initial_pos = pos.copy()
        self.trail_points = [pos.copy()]
        self.max_trail_points = 20
        self.has_drawn = False
        self.detonation_radius = 100.0  # Much larger blast radius for lightning strike
        self.explosion_force = 2000.0  # Stronger knockback force
        self.damage = 20.0  # Enough damage to one-shot enemies
        
        # Special properties
        self.trail_color = (80, 200, 255)  # Brighter blue for the trail
        self.lightning_time = 0.8  # Slightly longer lightning effects (seconds)
        self.lightning_active = False
        self.lightning_start_time = 0
        self.explosion_pos = None  # Position of explosion when it happens
        self.lightning_branches = []  # To store lightning bolt branch points
        self.world_lightning_branches = []  # Store branches in world space
        
        # Override sprite vertices to make a dart shape
        self.sprite_vertices = np.array([
            [self.sprite_size * 1.5, 0],          # Front point
            [0, self.sprite_size * 0.7],          # Side point
            [-self.sprite_size * 0.5, 0],         # Back point
            [0, -self.sprite_size * 0.7]          # Side point
        ], dtype=float)
        
        # Point in direction of movement
        if np.any(velocity):
            self.direction = velocity / np.linalg.norm(velocity)
    
    def draw(self, screen: pygame.Surface, room_transform: np.ndarray):
        """Draw the lightning dart with trail, and lightning effect when detonated."""
        # Transform position to screen space
        pos_h = np.append(self.pos, 1)
        screen_pos = (room_transform @ pos_h)[:2]
        
        # If lightning is active, draw it
        if self.lightning_active:
            if self.explosion_pos is not None:
                # Transform explosion position to screen space
                exp_pos_h = np.append(self.explosion_pos, 1)
                exp_screen_pos = (room_transform @ exp_pos_h)[:2]
                
                # Draw lightning branches
                self._draw_lightning(screen, room_transform)
                
                # Draw explosion circle
                time_since_explosion = pygame.time.get_ticks() / 1000.0 - self.lightning_start_time
                fade_factor = 1.0 - min(1.0, time_since_explosion / self.lightning_time)
                
                # Size pulses and fades over time
                radius = self.detonation_radius * (0.5 + 0.5 * fade_factor)
                alpha = int(200 * fade_factor)
                color = (80, 140, 255, alpha)
                
                # Create a temporary surface for the semi-transparent explosion
                explosion_surf = pygame.Surface((int(radius * 2), int(radius * 2)), pygame.SRCALPHA)
                pygame.draw.circle(explosion_surf, color, (int(radius), int(radius)), int(radius))
                
                # Blit explosion surface onto screen
                screen.blit(explosion_surf, (int(exp_screen_pos[0] - radius), int(exp_screen_pos[1] - radius)))
                
                return
        
        # Draw trail like the bullet class
        if not self.lightning_active:
            # Collect trail points in screen space
            trail_points = []
            
            # Add all trail points
            for pos in self.trail_points:
                pos_h = np.append(pos, 1)
                trail_points.append(tuple((room_transform @ pos_h)[:2]))
            
            # Add current position
            trail_points.append(tuple(screen_pos))
            
            # Draw the trail as a line
            if len(trail_points) > 1:
                pygame.draw.lines(screen, self.trail_color, False, trail_points, 3)
        
        # Draw the dart itself
        super().draw(screen, room_transform)
    
    def _draw_lightning(self, screen: pygame.Surface, room_transform: np.ndarray):
        """Draw lightning bolt effect from the explosion center.
        The lightning pattern is stored in world coordinates and transformed to screen space for drawing."""
        if not self.world_lightning_branches:
            # Generate new lightning pattern on first draw
            self._generate_lightning_branches()
        
        # Calculate how far into the lightning effect we are
        time_since_explosion = pygame.time.get_ticks() / 1000.0 - self.lightning_start_time
        fade_factor = 1.0 - min(1.0, time_since_explosion / self.lightning_time)
        
        # Draw each branch with appropriate alpha
        for branch in self.world_lightning_branches:
            # Transform world coordinates to screen space
            screen_branch = []
            for point in branch:
                pos_h = np.append(point, 1)
                screen_point = (room_transform @ pos_h)[:2]
                screen_branch.append(tuple(screen_point))
            
            # Random flicker effect
            if random.random() > 0.8:
                continue
                
            alpha = int(255 * fade_factor)
            width = max(1, int(3 * fade_factor))
            
            # Randomize color slightly for more realistic effect
            r = min(255, 200 + random.randint(-20, 50))
            g = min(255, 220 + random.randint(-20, 35))
            color = (r, g, 255)
            
            # Draw the branch
            pygame.draw.lines(screen, color, False, screen_branch, width)
            
            # Draw bright core of the lightning
            if width > 1 and random.random() > 0.5:
                pygame.draw.lines(screen, (255, 255, 255), False, screen_branch, max(1, width-1))
    
    def _generate_lightning_branches(self):
        """Generate the lightning branch pattern in world space."""
        self.world_lightning_branches = []
        
        # Create main branches from center
        num_branches = random.randint(5, 10)
        for _ in range(num_branches):
            # Get random angle and length
            angle = random.uniform(0, 2 * math.pi)
            length = random.uniform(80, 180)  # Longer branches for more impressive effect
            
            # Create zigzag path for this branch
            branch = [self.explosion_pos]
            
            # Current position and direction
            current_pos = np.array(self.explosion_pos)
            direction = np.array([math.cos(angle), math.sin(angle)])
            
            # Number of zigzags
            num_segments = random.randint(4, 10)
            segment_length = length / num_segments
            
            # Create zigzag pattern
            for i in range(num_segments):
                # Randomize direction a bit
                angle_change = random.uniform(-0.5, 0.5)
                new_direction = np.array([
                    direction[0] * math.cos(angle_change) - direction[1] * math.sin(angle_change),
                    direction[0] * math.sin(angle_change) + direction[1] * math.cos(angle_change)
                ])
                direction = new_direction / np.linalg.norm(new_direction)
                
                # Move in this direction
                current_pos = current_pos + direction * segment_length
                branch.append(tuple(current_pos))
                
                # Possibly create a sub-branch
                if i > 0 and random.random() < 0.4:
                    self._add_sub_branch(branch[-2], tuple(current_pos))
            
            self.world_lightning_branches.append(branch)
    
    def _add_sub_branch(self, start_pos, end_pos):
        """Add a sub-branch to the lightning effect in world space."""
        # Direction of parent branch
        dir_vector = np.array(end_pos) - np.array(start_pos)
        length = np.linalg.norm(dir_vector)
        
        if length < 10:  # Too small to branch
            return
            
        # Calculate perpendicular direction with randomness
        angle = math.atan2(dir_vector[1], dir_vector[0]) + random.uniform(math.pi/4, 3*math.pi/4)
        if random.random() < 0.5:
            angle = -angle
            
        # Create sub-branch
        branch = [start_pos]
        
        # Current position and direction
        current_pos = np.array(start_pos)
        direction = np.array([math.cos(angle), math.sin(angle)])
        
        # Sub-branch is shorter
        sub_length = random.uniform(length * 0.3, length * 0.7)
        num_segments = random.randint(2, 4)
        segment_length = sub_length / num_segments
        
        # Create zigzag pattern
        for i in range(num_segments):
            # Randomize direction a bit
            angle_change = random.uniform(-0.4, 0.4)
            new_direction = np.array([
                direction[0] * math.cos(angle_change) - direction[1] * math.sin(angle_change),
                direction[0] * math.sin(angle_change) + direction[1] * math.cos(angle_change)
            ])
            direction = new_direction / np.linalg.norm(new_direction)
            
            # Move in this direction
            current_pos = current_pos + direction * segment_length
            branch.append(tuple(current_pos))
        
        self.world_lightning_branches.append(branch)
    
    def detonate(self):
        """Activate the lightning strike effect and apply damage/knockback to nearby entities."""
        if self.lightning_active:
            return
            
        self.lightning_active = True
        self.lightning_start_time = pygame.time.get_ticks() / 1000.0
        self.explosion_pos = self.pos.copy()
        self.world_lightning_branches = []  # Will be generated on first draw
        
        # Find entities in blast radius
        affected_entities = []
        for entity in self.parent_room.entities:
            if entity is self:
                continue
                
            distance = np.linalg.norm(entity.pos - self.pos)
            if distance <= self.detonation_radius:
                affected_entities.append((entity, distance))
        
        # Apply damage and knockback
        for entity, distance in affected_entities:
            # Calculate damage falloff with distance
            damage_factor = 1.0 - (distance / self.detonation_radius)
            if isinstance(entity, Enemy):
                # Apply damage
                entity.take_damage(self.damage * damage_factor)
                
            # Calculate knockback direction and magnitude
            knockback_dir = entity.pos - self.pos
            if np.linalg.norm(knockback_dir) > 0:
                knockback_dir = knockback_dir / np.linalg.norm(knockback_dir)
                
            # Apply stronger knockback to closer entities
            knockback_magnitude = self.explosion_force * damage_factor
            entity.velocity += knockback_dir * knockback_magnitude
    
    def _transfer_to_room(self, new_room: Room, transform: np.ndarray) -> np.ndarray:
        """Transform lightning branches when transferring rooms."""
        if self.lightning_active and self.world_lightning_branches:
            # Transform all lightning branches to new room's coordinate system
            inv_transform = np.linalg.inv(transform)
            new_branches = []
            
            for branch in self.world_lightning_branches:
                new_branch = []
                for point in branch:
                    pos_h = np.append(point, 1)
                    new_pos = (inv_transform @ pos_h)[:2]
                    new_branch.append(tuple(new_pos))
                new_branches.append(new_branch)
                
            self.world_lightning_branches = new_branches
            
            # Also transform explosion position
            if self.explosion_pos is not None:
                pos_h = np.append(self.explosion_pos, 1)
                self.explosion_pos = (inv_transform @ pos_h)[:2]
        
        # Call parent implementation for trail points
        return super()._transfer_to_room(new_room, transform)
        
    def handle_collision(self, other: Union["Entity", Edge], collision_normal: np.ndarray):
        """When dart hits something, detonate it."""
        # First do normal collision physics
        super().handle_collision(other, collision_normal)
        
        # Then detonate if we've had a chance to draw
        if self.has_drawn:
            self.detonate()
            # Don't remove yet - need to keep entity around for lightning effect
            return False
        
        return False
    
    def update(self, dt: float):
        """Update dart position or lightning effect if active."""
        # If lightning is active, check if effect has expired
        if self.lightning_active:
            time_since_explosion = pygame.time.get_ticks() / 1000.0 - self.lightning_start_time
            if time_since_explosion >= self.lightning_time:
                self.is_gone = True
                return
        else:
            # Normal projectile update
            # Update direction to match velocity
            speed = np.linalg.norm(self.velocity)
            if speed > 0:
                self.direction = self.velocity / speed
                
            # Update trail
            self.trail_points.append(self.pos.copy())
            if len(self.trail_points) > self.max_trail_points:
                self.trail_points = self.trail_points[-self.max_trail_points:]
            
            # Remove if too slow
            if speed < self.min_speed and self.has_drawn:
                self.is_gone = True
                return
            
            # Mark that we've drawn at least once
            self.has_drawn = True
            
            # Call parent update for movement and collision handling
            super().update(dt)

class Enemy(Entity):
    def __init__(self, parent_room: Room, pos: np.ndarray):
        super().__init__(parent_room, pos)
        # Override the sprite vertices to create an octagon shape
        angles = np.linspace(0, 2 * np.pi, 8, endpoint=False)
        radius = self.sprite_size
        self.sprite_vertices = np.array([
            [radius * np.cos(angle), radius * np.sin(angle)]
            for angle in angles
        ])

        # Base color is red
        self.base_color = (255, 50, 50)
        self.color = self.base_color  # Will be updated based on HP

        # Movement parameters
        self.chase_force = 200.0  # Force applied when chasing player
        self.max_speed = 150.0  # Maximum speed
        
        # Combat parameters
        self.max_hp = 15  # Store maximum HP
        self.hp = self.max_hp  # Current HP starts at maximum

    def take_damage(self, amount: float = 1.0) -> bool:
        """Take damage and return True if this killed the enemy."""
        self.hp -= amount
        if self.hp <= 0:
            self.is_gone = True
            return True
            
        # Update color based on HP percentage
        hp_percent = self.hp / self.max_hp
        # Interpolate between 50% and 100% saturation based on HP
        saturation = 0.5 + (0.5 * hp_percent)
        # Apply saturation to base color
        self.color = tuple(int(c * saturation) for c in self.base_color)
        return False

    def update(self, dt: float):
        """Update enemy behavior based on player position."""
        # Check if player is in the same room
        player = None
        for entity in self.parent_room.entities:
            if isinstance(entity, Player):
                player = entity
                break

        if player:
            # Direct chase in same room
            to_player = player.pos - self.pos
            distance = np.linalg.norm(to_player)
            if distance > 1e-6:
                direction = to_player / distance
                self.velocity += direction * self.chase_force * dt

                # Update entity direction to face player
                self.direction = direction
        else:
            # Navigate through rooms to reach player
            next_edge = nav_manager.get_next_edge(self.parent_room, world.player.parent_room)
            if next_edge is not None:
                # Move toward edge midpoint
                edge_start, edge_end = self.parent_room.get_edge_vertices(next_edge)
                edge_mid = (np.array(edge_start) + np.array(edge_end)) / 2
                to_edge = edge_mid - self.pos
                distance = np.linalg.norm(to_edge)
                if distance > 1e-6:
                    direction = to_edge / distance
                    self.velocity += direction * self.chase_force * dt
                    self.direction = direction

        self.velocity *= (1.0 - .2 * dt)

        super().update(dt)

class Camera:
    # Initialize transform to center the view at (400,300)
    transform = np.array([
        [1, 0, 400],
        [0, 1, 300],
        [0, 0, 1]
    ])
    target_room = None

    @classmethod
    def get_position(cls) -> np.ndarray:
        """Get camera position (where in world space the camera is looking)."""
        # Extract rotation matrix
        rot = cls.transform[:2, :2]
        # Extract translation
        trans = cls.transform[:2, 2]
        # The camera position is: inv(rot) * (screen_center - translation)
        screen_center = np.array([400, 300])
        return rot.T @ (screen_center - trans)

    @classmethod
    def get_rotation(cls) -> float:
        """Extract camera rotation from transform matrix."""
        return -np.arctan2(cls.transform[1, 0], cls.transform[0, 0])

    @classmethod
    def handle_room_transition(cls, old_room: 'Room', new_room: 'Room', transform: np.ndarray):
        """Update camera when player moves between rooms to maintain consistent view."""
        if cls.target_room == old_room:
            # Update transform by composing with the room transition transform
            cls.transform = cls.transform @ transform
            cls.target_room = new_room
        else:
            raise ValueError(f"Camera was asked to transition from {old_room} to {new_room}, but it thinks the current"
                             f" room is {cls.target_room}!")

    @classmethod
    def update(cls, player_pos: np.ndarray, dt: float, lerp_speed: float = 5.0):
        """Smoothly move camera to follow player."""
        # Get the current camera position in world space
        camera_pos = cls.get_position()

        # Calculate desired movement in world space
        to_target = player_pos - camera_pos

        # Calculate smooth movement
        movement = to_target * min(1.0, lerp_speed * dt)

        # Convert movement to screen space using current rotation
        rot = cls.transform[:2, :2]
        screen_movement = rot @ movement

        # Create translation matrix to move world opposite to desired camera movement
        translation = np.array([
            [1, 0, -screen_movement[0]],
            [0, 1, -screen_movement[1]],
            [0, 0, 1]
        ])

        cls.transform = translation @ cls.transform


class NavigationManager:
    """
    Manages pathfinding between rooms. For each destination we've pathfound to,
    maintains a cache mapping each explored room to the next edge to take to
    reach that destination.
    """

    def __init__(self):
        # Maps (destination Room) -> Dict[Room, edge_idx]
        # For each destination, maps each room to the next edge to take
        self.cache: Dict[Room, Dict[Room, int]] = {}

    def explore_from_room(self, start: Room) -> Dict[Room, int]:
        """
        Run Dijkstra's algorithm from start room, recording for each room we
        explore what the next edge should be to get back to start.
        Returns dict mapping Room -> edge_idx.
        """
        # Maps each room to the edge we should take to get closer to start
        next_edges: Dict[Room, int] = {}

        # Counter for stable priority queue ordering
        counter = itertools.count()

        # Priority queue: (distance, counter, current_room, previous_room, edge_from_prev)
        pq = [(0, next(counter), start, None, None)]

        while pq:
            dist, _, room, prev_room, edge_from_prev = heapq.heappop(pq)

            # Skip if we've found a better path to this room
            if room in next_edges:
                continue

            # If we got here from a previous room, find the edge in THIS room
            # that connects back to the previous room
            if prev_room is not None:
                for i, edge in enumerate(room.edges):
                    if edge.target_room == prev_room:
                        next_edges[room] = i
                        break
            else:
                next_edges[room] = None

            # Explore neighbors
            for edge_idx, edge in enumerate(room.edges):
                if edge.target_room is None:
                    continue
                # All edges cost 1 for now
                heapq.heappush(pq, (
                    dist + 1,
                    next(counter),
                    edge.target_room,
                    room,
                    edge_idx
                ))

        return next_edges

    def get_next_edge(self, from_room: Room, to_room: Room) -> Optional[int]:
        """
        Get the next edge to take from from_room to reach to_room.
        Will compute and cache navigation data if needed.
        """
        # Get or create cache for the destination
        if to_room not in self.cache:
            self.cache[to_room] = self.explore_from_room(to_room)

        return self.cache[to_room].get(from_room)

    def clear_cache(self):
        """Clear all cached navigation data"""
        self.cache.clear()

class GameWorld:
    def __init__(self):
        self.graph = nx.Graph()
        self.player = None  # Will be set when player is created

    @property
    def root_room(self) -> Room:
        """Get the current root room (room containing player)."""
        return self.player.parent_room if self.player else None

    def create_room(self, num_sides: int) -> Room:
        """Create a new room and add it to the world graph."""
        room = Room(num_sides)
        self.graph.add_node(room)
        return room

    def connect_rooms(self, room1: Room, edge1_idx: int,
                      room2: Room, edge2_idx: int) -> None:
        """Connect two rooms along specified edges."""
        # Calculate the transform that aligns the edges
        # First, get the vertices of both edges
        start1, end1 = room1.get_edge_vertices(edge1_idx)
        start2, end2 = room2.get_edge_vertices(edge2_idx)

        # Calculate vectors representing the edges
        edge1_vec = np.array(end1) - np.array(start1)
        edge2_vec = np.array(end2) - np.array(start2)

        # Calculate angle between edges
        angle1 = np.arctan2(edge1_vec[1], edge1_vec[0])
        angle2 = np.arctan2(edge2_vec[1], edge2_vec[0])
        rotation_angle = angle1 - angle2 + np.pi  # Add pi to flip the edge

        # Create rotation matrix
        c, s = np.cos(rotation_angle), np.sin(rotation_angle)
        rotation = np.array([[c, -s, 0],
                             [s, c, 0],
                             [0, 0, 1]])

        # Calculate the midpoint of edge1
        edge1_mid = (np.array(start1) + np.array(end1)) / 2

        # Transform edge2's midpoint
        edge2_mid = (np.array(start2) + np.array(end2)) / 2
        edge2_mid_transformed = rotation @ np.array([edge2_mid[0], edge2_mid[1], 1])

        # Calculate translation to align the midpoints
        translation = edge1_mid - edge2_mid_transformed[:2]

        # Create translation matrix
        translation_matrix = np.array([[1, 0, translation[0]],
                                       [0, 1, translation[1]],
                                       [0, 0, 1]])

        # Combine transformations
        transform = translation_matrix @ rotation

        # Update edges
        room1.edges[edge1_idx].target_room = room2
        room1.edges[edge1_idx].target_edge_idx = edge2_idx
        room1.edges[edge1_idx].transform = transform

        # Calculate inverse transform for the other direction
        room2.edges[edge2_idx].target_room = room1
        room2.edges[edge2_idx].target_edge_idx = edge1_idx
        room2.edges[edge2_idx].transform = np.linalg.inv(transform)

        # Update graph
        self.graph.add_edge(room1, room2,
                            edge1=edge1_idx,
                            edge2=edge2_idx)

    def collect_nearby_entities(self, max_distance: int = 15) -> list[Entity]:
        """
        Collect all entities within max_distance jumps of the player's room.
        Returns a list of all entities found.
        """
        if not self.player:
            return []

        entities = []
        visited = {self.player.parent_room}
        queue = deque([(self.player.parent_room, 0)])

        while queue:
            room, distance = queue.popleft()

            # Add non-gone entities
            for entity in room.entities[:]:  # Make a copy since we might modify the list
                if entity.is_gone:
                    room.entities.remove(entity)
                else:
                    entities.append(entity)

            if distance < max_distance:
                for edge in room.edges:
                    if edge.target_room and edge.target_room not in visited:
                        visited.add(edge.target_room)
                        queue.append((edge.target_room, distance + 1))

        return entities

def create_test_level() -> GameWorld:
    world = GameWorld()

    # Create root pentagon
    starting_pentagon = world.create_room(5)

    # Create player in center of start room
    world.player = Player(starting_pentagon, np.zeros(2))

    # Test Case 1: Simple linear corridor
    hex_room = world.create_room(6)
    world.connect_rooms(starting_pentagon, 0, hex_room, 0)

    # === Uncomment to test simple corridor ===
    prev_room = hex_room
    for i in range(3):  # Add 5 more rooms
        next_room = world.create_room(4)
        world.connect_rooms(prev_room, 1, next_room, 2)
        prev_room = next_room

    # === Uncomment to test branching paths ===
    # Start from root's edge 1
    branch1 = world.create_room(4)  # square
    world.connect_rooms(starting_pentagon, 1, branch1, 0)
    # Split into two paths
    branch1a = world.create_room(3)  # triangle
    branch1b = world.create_room(5)  # pentagon
    world.connect_rooms(branch1, 1, branch1a, 0)
    world.connect_rooms(branch1, 3, branch1b, 0)
    # Continue one more level on each branch
    world.connect_rooms(branch1a, 1, world.create_room(3), 0)
    world.connect_rooms(branch1b, 2, world.create_room(3), 0)

    # === Uncomment to test self-overlapping structure ===
    # # Create a zigzag pattern that crosses over itself
    overlap1 = world.create_room(4)  # square
    world.connect_rooms(starting_pentagon, 2, overlap1, 0)
    overlap2 = world.create_room(4)
    world.connect_rooms(overlap1, 1, overlap2, 0)
    overlap3 = world.create_room(4)
    world.connect_rooms(overlap2, 1, overlap3, 0)
    overlap4 = world.create_room(4)
    world.connect_rooms(overlap3, 3, overlap4, 0)  # This should cross back
    world.connect_rooms(overlap4, 3, prev_room, 3)

    # === Uncomment to test cycle structure ===
    # Create a diamond-shaped loop
    cycle1 = world.create_room(6)
    cycle2 = world.create_room(7)
    cycle3 = world.create_room(6)
    world.connect_rooms(starting_pentagon, 3, cycle1, 0)
    world.connect_rooms(cycle1, 2, cycle2, 5)
    world.connect_rooms(cycle2, 2, cycle3, 5)
    world.connect_rooms(cycle3, 2, cycle1, 4)  # Complete the cycle

    # === Uncomment to test self-connecting room ===
    # Create a corridor leading to a self-connecting room
    corridor1 = world.create_room(4)
    world.connect_rooms(starting_pentagon, 4, corridor1, 0)
    corridor2 = world.create_room(4)
    world.connect_rooms(corridor1, 2, corridor2, 0)
    mirror_room = world.create_room(8)  # octagon
    world.connect_rooms(corridor2, 2, mirror_room, 0)
    # Connect the mirror room to itself
    world.connect_rooms(mirror_room, 3, mirror_room, 3)  # Connect opposite sides

    return world

def create_large_test_level() -> GameWorld:
    world = GameWorld()
    # Create hubs without scaling modifications.
    hubA = world.create_room(6)
    hubB = world.create_room(8)
    hubC = world.create_room(5)
    hubD = world.create_room(7)
    hubE = world.create_room(4)

    # Helper to connect two rooms via a corridor chain of given length.
    def connect_with_corridor(r1, edge1, r2, edge2, length):
        prev = world.create_room(4)
        world.connect_rooms(r1, edge1, prev, 0)
        for _ in range(length):
            new_corr = world.create_room(random.choice([3, 4, 5]))
            safe_edge = 1 % prev.num_sides
            target_edge = 3 if new_corr.num_sides > 3 else new_corr.num_sides - 1
            world.connect_rooms(prev, safe_edge, new_corr, target_edge)
            prev = new_corr
        world.connect_rooms(prev, 2, r2, edge2)

    # Connect hubs by long corridors instead of directly.
    connect_with_corridor(hubA, 0, hubB, 4, length=5)
    connect_with_corridor(hubB, 2, hubC, 1, length=6)
    connect_with_corridor(hubC, 0, hubD, 3, length=4)
    connect_with_corridor(hubD, 2, hubE, 1, length=5)
    connect_with_corridor(hubE, 3, hubA, 5, length=6)
    connect_with_corridor(hubA, 1, hubC, 2, length=4)
    connect_with_corridor(hubB, 6, hubD, 4, length=5)

    # Additional branching corridors from hubs.
    for hub, edges in [(hubA, [2, 4]), (hubB, [3]), (hubC, [3, 4]), (hubD, [1, 5]), (hubE, [0, 2])]:
        for edge in edges:
            length = random.randint(3, 6)
            prev = world.create_room(4)
            world.connect_rooms(hub, edge, prev, 0)
            for _ in range(length):
                new_corr = world.create_room(random.choice([3, 4, 5]))
                safe_edge = 1 % prev.num_sides
                target_edge = 3 if new_corr.num_sides > 3 else new_corr.num_sides - 1
                world.connect_rooms(prev, safe_edge, new_corr, target_edge)
                prev = new_corr

    # Cycle loop branching off hubB.
    cycle_length = 5
    start_cycle = world.create_room(random.choice([4, 5, 6]))
    world.connect_rooms(hubB, 7, start_cycle, 0)
    cycle_rooms = [start_cycle]
    prev = start_cycle
    for _ in range(cycle_length - 1):
        new_cycle = world.create_room(random.choice([4, 5, 6]))
        safe_edge = 1 if prev.num_sides > 1 else 0
        target_edge = 3 if new_cycle.num_sides > 3 else new_cycle.num_sides - 1
        world.connect_rooms(prev, safe_edge, new_cycle, target_edge)
        cycle_rooms.append(new_cycle)
        prev = new_cycle
    world.connect_rooms(cycle_rooms[-1], 2, start_cycle, 2)

    # Spiral loop branching off hubD.
    spiral_start = world.create_room(6)
    world.connect_rooms(hubD, 0, spiral_start, 0)
    spiral_rooms = [spiral_start]
    prev = spiral_start
    for _ in range(6):
        new_spiral = world.create_room(6)
        world.connect_rooms(prev, 1, new_spiral, 4)
        spiral_rooms.append(new_spiral)
        prev = new_spiral
    world.connect_rooms(spiral_rooms[-1], 2, spiral_start, 3)

    # Mirror corridor: a room that connects to a mirror room.
    mirror_corridor = world.create_room(4)
    world.connect_rooms(hubC, 4, mirror_corridor, 0)
    mirror_room = world.create_room(8)
    world.connect_rooms(mirror_corridor, 2, mirror_room, 0)
    world.connect_rooms(mirror_room, 3, mirror_room, 7)

    # Dense cluster branching off hubE.
    cluster_center = world.create_room(6)
    world.connect_rooms(hubE, 2, cluster_center, 0)
    cluster = [cluster_center]
    for i in range(4):
        periph = world.create_room(random.choice([4, 5, 6]))
        world.connect_rooms(cluster_center, i, periph, 0)
        cluster.append(periph)
    for i in range(1, len(cluster)):
        for j in range(i + 1, len(cluster)):
            try:
                world.connect_rooms(cluster[i], 1, cluster[j], 1)
            except Exception:
                pass

    # Maze-like branch off hubA.
    maze_start = world.create_room(4)
    world.connect_rooms(hubA, 3, maze_start, 0)
    prev = maze_start
    for _ in range(8):
        new_room = world.create_room(random.choice([3, 4, 5]))
        safe_edge = 1 if prev.num_sides > 1 else 0
        target_edge = 3 if new_room.num_sides > 3 else new_room.num_sides - 1
        world.connect_rooms(prev, safe_edge, new_room, target_edge)
        prev = new_room
    world.connect_rooms(prev, 2, hubD, 5)

    # Set the player's starting position at hubA.
    world.player = Player(hubA, np.zeros(2))
    return world


def load_level_from_file(path: str) -> GameWorld:
    with open(path, "r") as f:
        data = json.load(f)

    meta = data.get("meta", {})
    grid_size = meta.get("grid_size", 20)
    world = GameWorld()
    rooms = {}
    player_created = False

    # Create entity type lookup dictionary
    entity_classes = {cls.__name__: cls for cls in get_all_entity_subclasses()}

    # First pass: Create all rooms
    for rdata in data.get("rooms", []):
        rid = rdata["id"]
        verts_abs = np.array(rdata["vertices"], dtype=float)
        center = verts_abs.mean(axis=0)
        verts_local = verts_abs - center
        n = len(verts_local)

        room = Room(n)
        room.vertices = verts_local
        room.vertices_h = np.hstack((verts_local, np.ones((n, 1))))
        room.num_sides = n
        room.room_radius = np.linalg.norm(verts_local, axis=1).max()
        room.grid_size = grid_size

        # Create room texture
        ts = int(room.room_radius * 2.2)
        room.texture = pygame.Surface((ts, ts), pygame.SRCALPHA)
        off = int(room.room_radius) % grid_size
        for y in range(-grid_size, ts + grid_size, grid_size):
            for x in range(-grid_size, ts + grid_size, grid_size):
                if ((x + y) // grid_size) % 2 == 0:
                    rect = pygame.Rect(x + off, y + off, grid_size, grid_size)
                    pygame.draw.rect(room.texture, room.color + (255,), rect)

        room.scaled_texture = pygame.transform.scale(room.texture, (ts, ts))
        room.absolute_center = center
        rooms[rid] = room
        world.graph.add_node(room)

        # Create entities in this room
        for entity_data in rdata.get("entities", []):
            entity_type = entity_data["type"]
            pos = np.array(entity_data["pos"]) - center  # Convert to room-local coordinates

            # Get the entity class from our registry
            entity_class = entity_classes.get(entity_type)
            if entity_class is None:
                print(f"Warning: Unknown entity type '{entity_type}' in room {rid}. Skipping.")
                continue

            # Create entity
            entity = entity_class(room, pos)

            # Special handling for Player
            if entity_type == "Player" and not player_created:
                world.player = entity
                player_created = True
                Camera.target_room = room
            elif entity_type == "Player":
                print(f"Warning: Multiple players found in level. Ignoring player in room {rid}.")
                room.entities.remove(entity)  # Remove the extra player

    # Second pass: Create connections
    for rdata in data.get("rooms", []):
        r1_id = rdata["id"]
        room1 = rooms[r1_id]

        for edge_str, conn in rdata.get("connections", {}).items():
            e1 = int(edge_str)
            r2_id = conn["target_room"]
            e2 = conn["target_edge"]

            if r2_id not in rooms:
                print(f"Warning: Room {r1_id} references missing room {r2_id} on edge {e1}. Skipping connection.")
                continue

            room2 = rooms[r2_id]

            # Create connection if it doesn't exist yet
            if (r1_id < r2_id) or (r1_id == r2_id):
                world.connect_rooms(room1, e1, room2, e2)

    # Create default player if none was loaded from the level
    if not player_created and data.get("rooms"):
        first_id = data["rooms"][0]["id"]
        world.player = Player(rooms[first_id], np.zeros(2))
        Camera.target_room = rooms[first_id]

    return world

class PerformanceMonitor:
    def __init__(self):
        self.frame_times = []
        self.max_samples = 10
        self.font = pygame.font.Font(None, 36)
        self.last_print_time = 0
        self.print_interval = 1.0  # Print every second when enabled

    def update(self, dt: float, current_time: float):
        """Update frame time history and print stats if needed."""
        if len(self.frame_times) >= self.max_samples:
            self.frame_times.pop(0)
        self.frame_times.append(dt)

        # Print stats periodically if enabled
        if SHOW_PERFORMANCE > 0 and current_time - self.last_print_time >= self.print_interval:
            self.print_stats()
            self.last_print_time = current_time

    def get_average_frame_time(self) -> float:
        """Get average frame time in milliseconds."""
        if not self.frame_times:
            return 0
        return sum(self.frame_times) / len(self.frame_times) * 1000  # Convert to ms

    def get_fps(self) -> float:
        """Get average FPS."""
        avg_frame_time = self.get_average_frame_time()
        if avg_frame_time == 0:
            return 0
        return 1000 / avg_frame_time

    def print_stats(self):
        """Print performance statistics."""
        print(f"Average frame time: {self.get_average_frame_time():.2f}ms")

    def draw(self, screen: pygame.Surface):
        """Draw FPS counter on screen if enabled."""
        if SHOW_PERFORMANCE > 1:
            fps_text = self.font.render(f"FPS: {self.get_fps():.2f}", True, (255, 255, 255))
            screen.blit(fps_text, (10, 10))


def main():
    global SHOW_PERFORMANCE, DRAW_CONNECTED_EDGES, DRAW_ROOM_NUMBERS, DEBUG_VISIBILITY, VISUALIZE_CONSTRUCTION
    global UPDATE_ENTITES, DEBUG_COLLISIONS

    # Disable automatic garbage collection to prevent periodic stutters
    # We'll run GC manually when we have frame time to spare
    gc.disable()
    
    pygame.init()
    global screen
    screen = pygame.display.set_mode((800, 600))
    clock = pygame.time.Clock()

    # Load saved debug state if it exists
    saved_state = None
    try:
        with open('debug_persistence.json', 'r') as f:
            saved_state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    # Create persistent rendering layers
    room_layer     = pygame.Surface((800, 600))
    entity_layer   = pygame.Surface((800, 600), pygame.SRCALPHA)
    mask_layer1    = pygame.Surface((800, 600), pygame.SRCALPHA)
    mask_layer2    = pygame.Surface((800, 600), pygame.SRCALPHA)
    entities_mask  = pygame.Surface((800, 600), pygame.SRCALPHA)
    work_layer     = pygame.Surface((800, 600), pygame.SRCALPHA)

    #world = create_large_test_level()
    global world
    world = create_large_test_level()#load_level_from_file("cool_level_1.json")
    Camera.target_room = world.player.parent_room

    # Initialize performance monitor
    perf_monitor = PerformanceMonitor()
    start_time = pygame.time.get_ticks() / 1000.0

    # Initialize navigation manager - lets us avoid redoing pathfinding all the time
    global nav_manager
    nav_manager = NavigationManager()

    if saved_state:
        try:
            world.player.pos = np.array(saved_state["position"])
            world.player.direction = np.array(saved_state["direction"])
            world.player.parent_room.entities.remove(world.player)
            for the_room in world.graph.nodes:
                if the_room.room_number == saved_state["room_number"]:
                    the_room.entities.append(world.player)
                    Camera.target_room = the_room
                    world.player.parent_room = the_room
            Camera.transform = np.array(saved_state["camera_transform"])
        except KeyError:
            print("Invalid save state file, deleting it")
            os.unlink('debug_persistence.json')

    running = True
    while running:
        current_time = pygame.time.get_ticks() / 1000.0
        dt = clock.tick(240) / 1000.0  # Convert to seconds
        dt = min(dt, 0.2) # Don't let physics explode if framerate is extremely low (such as when using breakpoints!)

        # Update performance monitor
        perf_monitor.update(dt, current_time)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_F2:
                    DRAW_CONNECTED_EDGES = not DRAW_CONNECTED_EDGES
                elif event.key == pygame.K_F3:
                    DRAW_ROOM_NUMBERS = not DRAW_ROOM_NUMBERS
                elif event.key == pygame.K_F4:
                    SHOW_PERFORMANCE = (SHOW_PERFORMANCE + 1) % 3
                    # Force immediate print on toggle
                    perf_monitor.last_print_time = -perf_monitor.print_interval
                elif event.key == pygame.K_F5:
                    DEBUG_VISIBILITY = not DEBUG_VISIBILITY
                elif event.key == pygame.K_F6:
                    DEBUG_COLLISIONS = not DEBUG_COLLISIONS
                elif event.key == pygame.K_F7:
                    VISUALIZE_CONSTRUCTION = not VISUALIZE_CONSTRUCTION
                elif event.key == pygame.K_F9:
                    UPDATE_ENTITES = not UPDATE_ENTITES

        # Also check for held mouse button for continuous fire
        mouse_buttons = pygame.mouse.get_pressed()
        if mouse_buttons[0]:  # Left mouse button held
            world.player.try_shoot(current_time)
        if mouse_buttons[2]:  # Right mouse button held
            world.player.try_lightning(current_time)

        # Update entities (including the player)
        if UPDATE_ENTITES:
            for the_entity in world.collect_nearby_entities(6):
                the_entity.update(dt)
        else:
            world.player.update(dt)

        # Update camera to follow player
        Camera.update(world.player.pos, dt)

        # Clear all surfaces
        screen.fill((0, 0, 0))
        room_layer.fill((0, 0, 0, 0))
        entity_layer.fill((0, 0, 0, 0))
        entities_mask.fill((0, 0, 0, 0))
        mask_layer1.fill((0,0,0,0))
        mask_layer2.fill((0,0,0,0))
        work_layer.fill((0,0,0,0))

        # Draw world
        world.root_room.draw(
            room_layer=room_layer,
            entity_layer=entity_layer,
            mask_layer1=mask_layer1,
            mask_layer2=mask_layer2,
            entities_mask=entities_mask,
            work_layer=work_layer,
            local_to_screen=Camera.transform,
            viewpoint=world.player.pos
        )

        # Composite layers onto screen in order
        screen.blit(room_layer, (0, 0))

        # Mask off the entity layer by the whole-screen visibility mask
        entity_layer.blit(entities_mask, (0,0), special_flags=BLEND_RGBA_MULT)
        screen.blit(entity_layer, (0, 0))
        
        # Draw player's cooldown indicator on top of everything else
        world.player.draw(screen, Camera.transform)

        # Draw performance stats if enabled (directly to screen since it's UI)
        perf_monitor.draw(screen)

        pygame.display.flip()
        
        # Run garbage collection incrementally when we have spare frame time
        # Only collect gen0 (fast) to avoid long pauses
        gc.collect(0)

    pygame.quit()


if __name__ == "__main__":
    main()

# IDEAS SCRATCHPAD
# Let edges connect to multiple other edges - whenever we need to use the edge connection for something other than rendering, pick one at random.
# When the player looks through such an edge everything on the other side will appear to be chaotically shifting every frame.
# Maybe instead have it shift once every 5 frames or something? Either that, or certain angles lead to one connection or the other, sort of like a lenticular image.
# Beside looking cool this has a gameplay effect - if you are standing in a room shooting through such an edge at a target on the other side, half your bullets go
# to the wrong place, but if the multiplicity effect is one way, the same does not apply to the other guy!
