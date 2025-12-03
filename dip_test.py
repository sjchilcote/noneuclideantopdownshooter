#!/usr/bin/env python3
"""
Dip Test Script - Frame Time Variance Analysis
===============================================

This script runs continuous rendering at hubA_center for 60 seconds
to detect periodic FPS dips and measure frame time variance.

USAGE
-----
    python dip_test.py
    python dip_test.py --duration 30   # Run for 30 seconds instead

METRICS
-------
- Min/Max frame time
- Percentiles: 10th, 25th, 50th (median), 75th, 90th
- Variance and standard deviation
- Dip count: frames that took >2x the median time
"""

import argparse
import gc
import math
from collections import defaultdict
import random
import statistics
import time

import numpy as np
import pygame
from pygame import BLEND_RGBA_MULT

from main import (
    Camera,
    Room,
    Player,
    GameWorld,
)

SCREEN_SIZE = (800, 600)


def create_test_level_hubA():
    """Create the large test level and return (world, hubA room)."""
    random.seed(42)
    
    world = GameWorld()
    
    hubA = world.create_room(6)
    hubB = world.create_room(8)
    hubC = world.create_room(5)
    hubD = world.create_room(7)
    hubE = world.create_room(4)

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

    connect_with_corridor(hubA, 0, hubB, 4, length=5)
    connect_with_corridor(hubB, 2, hubC, 1, length=6)
    connect_with_corridor(hubC, 0, hubD, 3, length=4)
    connect_with_corridor(hubD, 2, hubE, 1, length=5)
    connect_with_corridor(hubE, 3, hubA, 5, length=6)
    connect_with_corridor(hubA, 1, hubC, 2, length=4)
    connect_with_corridor(hubB, 6, hubD, 4, length=5)

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

    mirror_corridor = world.create_room(4)
    world.connect_rooms(hubC, 4, mirror_corridor, 0)
    mirror_room = world.create_room(8)
    world.connect_rooms(mirror_corridor, 2, mirror_room, 0)
    world.connect_rooms(mirror_room, 3, mirror_room, 7)

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

    world.player = Player(hubA, np.zeros(2))
    
    return world, hubA


_preallocated_center = np.array(SCREEN_SIZE, dtype=float) / 2
_preallocated_transform = np.array([
    [1.0, 0.0, 0.0],
    [0.0, 1.0, 0.0],
    [0.0, 0.0, 1.0]
], dtype=float)

def render_frame(world, room, pos, surfaces, breakdown=None):
    """Render a single frame and return the time taken in ms.
    If breakdown dict is provided, records timing for each phase."""
    room_layer, entity_layer, mask_layer1, mask_layer2, entities_mask, work_layer, screen = surfaces
    
    t0 = time.perf_counter()
    
    Camera.target_room = room
    # Reuse preallocated arrays to reduce GC pressure
    _preallocated_transform[0, 2] = _preallocated_center[0] - pos[0]
    _preallocated_transform[1, 2] = _preallocated_center[1] - pos[1]
    Camera.transform = _preallocated_transform
    
    t1 = time.perf_counter()
    
    screen.fill((0, 0, 0))
    room_layer.fill((0, 0, 0, 0))
    entity_layer.fill((0, 0, 0, 0))
    entities_mask.fill((0, 0, 0, 0))
    mask_layer1.fill((0, 0, 0, 0))
    mask_layer2.fill((0, 0, 0, 0))
    work_layer.fill((0, 0, 0, 0))
    
    t2 = time.perf_counter()
    
    draw_cache = set()
    
    # Instrumented draw - measure each operation
    from main import Room, DRAW_CONNECTED_EDGES, DRAW_ROOM_NUMBERS, DEBUG_VISIBILITY, VISUALIZE_CONSTRUCTION
    
    viewport_rect = room_layer.get_rect()
    rooms_to_draw = []
    stack = [(room, Camera.transform, pos, None, None, None, 0)]
    
    # Phase 1: Traversal - with sub-phase timing
    t_trav_start = time.perf_counter()
    inv_count = 0
    inv_time = 0
    t_matmul = 0
    t_frustum = 0
    iterations = 0
    
    # Preallocate reusable arrays
    _homog_vec = np.array([0.0, 0.0, 1.0])
    _center_vec = np.array([0, 0, 1])
    
    while stack:
        iterations += 1
        r, l2s, vp, eei, ves, vcr, depth = stack.pop()
        if depth > 12:
            continue
        tx, ty = round(l2s[0, 2], 1), round(l2s[1, 2], 1)
        cos_theta = round(l2s[0, 0], 2)
        cache_key = (id(r), tx, ty, cos_theta)
        if cache_key in draw_cache:
            continue
        draw_cache.add(cache_key)
        
        full = (eei is None)
        if (not full) and (vcr is not None):
            ang = Room._angle_between_rays(np.array(vcr[0], dtype=float), np.array(vcr[1], dtype=float))
            if math.degrees(ang) > 170.0:
                full = True
        if full:
            vis_reg = r.vertices.copy()
        else:
            s_pt, e_pt = np.array(r.get_edge_vertices(eei)[0]), np.array(r.get_edge_vertices(eei)[1])
            ev = e_pt - s_pt
            f_bs = s_pt + ves[0] * ev
            f_be = s_pt + ves[1] * ev
            r1, r2 = np.array(vcr[0], dtype=float), np.array(vcr[1], dtype=float)
            if np.linalg.norm(r1) > 1e-9: r1 /= np.linalg.norm(r1)
            if np.linalg.norm(r2) > 1e-9: r2 /= np.linalg.norm(r2)
            vant = vp if vp is not None else 0.5 * (f_bs + f_be)
            ext = 10.0
            maxd = Room._furthest_vertex_distance(vant, r.vertices)
            rl = maxd * ext
            vis_reg = np.array([f_bs, f_bs + r1 * rl, f_be + r2 * rl, f_be])

        t0 = time.perf_counter()
        scr = (l2s @ r.vertices_h.T).T[:, :2]
        t_matmul += time.perf_counter() - t0
        
        x_min, y_min = scr.min(axis=0)
        x_max, y_max = scr.max(axis=0)
        room_rect = pygame.Rect(x_min, y_min, x_max - x_min, y_max - y_min)
        if not viewport_rect.colliderect(room_rect):
            continue

        center_screen = (l2s @ _center_vec)[:2]
        projected_radius = np.linalg.norm(scr - center_screen, axis=1).max()
        push_children = projected_radius >= 10 or depth == 0

        rooms_to_draw.append((r, l2s, vp, full, vis_reg, depth, eei, ves, vcr))

        if push_children:
            for i, edge in enumerate(r.edges):
                if i == eei or edge.target_room is None:
                    continue
                nxt_l2s = l2s @ edge.transform
                if not hasattr(edge, 'inv_transform'):
                    t_inv_start = time.perf_counter()
                    try:
                        edge.inv_transform = np.linalg.inv(edge.transform)
                    except np.linalg.LinAlgError:
                        continue
                    inv_time += (time.perf_counter() - t_inv_start) * 1000
                    inv_count += 1
                nxt_inv = edge.inv_transform
                _homog_vec[0], _homog_vec[1] = vp[0], vp[1]
                vp_next = (nxt_inv @ _homog_vec)[:2]
                s_pt, e_pt = np.array(r.get_edge_vertices(i)[0]), np.array(r.get_edge_vertices(i)[1])
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
                    t_f0 = time.perf_counter()
                    fr = Room._compute_edge_frustum_intersection(np.array(vp), vis_reg[0], vis_reg[-1], s_pt, e_pt)
                    t_frustum += time.perf_counter() - t_f0
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
    
    t_trav_end = time.perf_counter()
    
    if breakdown is not None:
        breakdown.setdefault('inv_count', []).append(inv_count)
        breakdown.setdefault('inv_time', []).append(inv_time)
        breakdown.setdefault('t_matmul', []).append(t_matmul * 1000)
        breakdown.setdefault('t_frustum', []).append(t_frustum * 1000)
        breakdown.setdefault('iterations', []).append(iterations)
    
    # Phase 2: Rendering
    t_render_start = time.perf_counter()
    for (r, l2s, vp, full, vis_reg, depth, eei, ves, vcr) in rooms_to_draw:
        room_center_screen = l2s @ np.array([0.0, 0.0, 1.0])
        scr = (l2s @ r.vertices_h.T).T[:, :2]
        x_min, y_min = scr.min(axis=0)
        x_max, y_max = scr.max(axis=0)
        pad = 10
        clip_rect = pygame.Rect(int(x_min) - pad, int(y_min) - pad,
                                int(x_max - x_min) + pad * 2, int(y_max - y_min) + pad * 2)
        clip_rect = clip_rect.clip(viewport_rect)
        if clip_rect.width <= 0 or clip_rect.height <= 0:
            continue
        work_layer.fill((0, 0, 0, 0), clip_rect)
        ts = r.scaled_texture.get_width()
        tx = int(room_center_screen[0] - ts // 2)
        ty = int(room_center_screen[1] - ts // 2)
        work_layer.blit(r.scaled_texture, (tx, ty))
        for i, edge in enumerate(r.edges):
            s_coord = scr[i]
            e_coord = scr[(i + 1) % r.num_sides]
            if edge.target_room is None:
                pygame.draw.line(work_layer, (255, 255, 255), s_coord, e_coord, 4)
        mask_layer1.fill((0, 0, 0, 0), clip_rect)
        mask_layer2.fill((0, 0, 0, 0), clip_rect)
        room_poly = scr.tolist()
        pygame.draw.polygon(mask_layer1, (255, 255, 255, 255), room_poly)
        if not full:
            frustum_poly = (l2s @ np.hstack((vis_reg, np.ones((vis_reg.shape[0], 1)))).T).T[:, :2]
            pygame.draw.polygon(mask_layer2, (255, 255, 255, 255), frustum_poly.tolist())
        else:
            mask_layer2.fill((255, 255, 255, 255), clip_rect)
        mask_layer1.blit(mask_layer2, clip_rect, clip_rect, special_flags=pygame.BLEND_RGBA_MIN)
        work_layer.blit(mask_layer1, clip_rect, clip_rect, special_flags=pygame.BLEND_RGBA_MIN)
        room_layer.blit(work_layer, clip_rect, clip_rect)
        entities_mask.blit(mask_layer1, clip_rect, clip_rect, special_flags=pygame.BLEND_RGBA_MAX)
    
    t_render_end = time.perf_counter()
    
    room_count = len(draw_cache)
    traversal_time = (t_trav_end - t_trav_start) * 1000
    render_time = (t_render_end - t_render_start) * 1000
    
    t3 = time.perf_counter()
    
    screen.blit(room_layer, (0, 0))
    entity_layer.blit(entities_mask, (0, 0), special_flags=BLEND_RGBA_MULT)
    screen.blit(entity_layer, (0, 0))
    
    t4 = time.perf_counter()
    
    pygame.display.flip()
    
    t5 = time.perf_counter()
    
    if breakdown is not None:
        breakdown['setup'].append((t1 - t0) * 1000)
        breakdown['clear'].append((t2 - t1) * 1000)
        breakdown['draw'].append((t3 - t2) * 1000)
        breakdown['composite'].append((t4 - t3) * 1000)
        breakdown['flip'].append((t5 - t4) * 1000)
        breakdown['room_count'].append(room_count)
        breakdown.setdefault('traversal', []).append(traversal_time)
        breakdown.setdefault('render', []).append(render_time)
    
    return (t5 - t0) * 1000


def percentile(data: list, p: float) -> float:
    """Calculate the p-th percentile."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * (p / 100)
    f = int(k)
    c = f + 1 if f + 1 < len(sorted_data) else f
    return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])


def colorize(text: str, color: str) -> str:
    colors = {
        "green": "\033[92m",
        "red": "\033[91m",
        "yellow": "\033[93m",
        "cyan": "\033[96m",
        "reset": "\033[0m",
        "bold": "\033[1m",
    }
    return f"{colors.get(color, '')}{text}{colors['reset']}"


def run_dip_test(duration_seconds: int = 60):
    """Run continuous rendering and collect frame time stats."""
    
    # Disable GC during test to isolate rendering performance
    gc.disable()
    
    pygame.init()
    # Disable vsync to get raw rendering performance
    screen = pygame.display.set_mode(SCREEN_SIZE, vsync=0)
    pygame.display.set_caption("Dip Test - hubA_center")
    
    room_layer = pygame.Surface(SCREEN_SIZE)
    entity_layer = pygame.Surface(SCREEN_SIZE, pygame.SRCALPHA)
    mask_layer1 = pygame.Surface(SCREEN_SIZE, pygame.SRCALPHA)
    mask_layer2 = pygame.Surface(SCREEN_SIZE, pygame.SRCALPHA)
    entities_mask = pygame.Surface(SCREEN_SIZE, pygame.SRCALPHA)
    work_layer = pygame.Surface(SCREEN_SIZE, pygame.SRCALPHA)
    
    surfaces = (room_layer, entity_layer, mask_layer1, mask_layer2, entities_mask, work_layer, screen)
    
    world, hubA = create_test_level_hubA()
    pos = np.zeros(2)
    
    frame_times = []
    breakdown = {'setup': [], 'clear': [], 'draw': [], 'composite': [], 'flip': [], 'room_count': []}
    
    print(f"Running dip test at hubA_center for {duration_seconds} seconds...")
    print("Press Ctrl+C to stop early.\n")
    
    # Warmup
    for _ in range(10):
        render_frame(world, hubA, pos, surfaces)
    
    start_time = time.perf_counter()
    last_report = start_time
    frames_since_report = 0
    
    try:
        while True:
            current_time = time.perf_counter()
            elapsed = current_time - start_time
            
            if elapsed >= duration_seconds:
                break
            
            # Check for quit events
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    raise KeyboardInterrupt
            
            frame_time = render_frame(world, hubA, pos, surfaces, breakdown)
            frame_times.append(frame_time)
            frames_since_report += 1
            
            # Progress report every 5 seconds
            if current_time - last_report >= 5.0:
                recent_times = frame_times[-frames_since_report:]
                recent_avg = sum(recent_times) / len(recent_times)
                recent_max = max(recent_times)
                print(f"  [{int(elapsed):2d}s] {frames_since_report} frames, "
                      f"avg: {recent_avg:.2f}ms, max: {recent_max:.2f}ms")
                last_report = current_time
                frames_since_report = 0
                
    except KeyboardInterrupt:
        print("\nStopped early.")
    
    pygame.quit()
    gc.enable()
    
    return frame_times, breakdown


def print_report(frame_times: list, breakdown: dict = None):
    """Print detailed variance analysis."""
    if not frame_times:
        print("No frames recorded.")
        return
    
    n = len(frame_times)
    
    # Basic stats
    min_time = min(frame_times)
    max_time = max(frame_times)
    avg_time = sum(frame_times) / n
    
    # Percentiles
    p10 = percentile(frame_times, 10)
    p25 = percentile(frame_times, 25)
    p50 = percentile(frame_times, 50)  # median
    p75 = percentile(frame_times, 75)
    p90 = percentile(frame_times, 90)
    
    # Variance stats
    variance = statistics.variance(frame_times) if n > 1 else 0
    stdev = statistics.stdev(frame_times) if n > 1 else 0
    
    # Dip detection: frames taking >2x median
    dip_threshold = p50 * 2
    dips = [t for t in frame_times if t > dip_threshold]
    dip_count = len(dips)
    dip_rate = (dip_count / n) * 100
    
    # Severe dip: >3x median
    severe_threshold = p50 * 3
    severe_dips = [t for t in frame_times if t > severe_threshold]
    severe_count = len(severe_dips)
    
    print("\n" + "=" * 60)
    print(colorize("  DIP TEST RESULTS - hubA_center", "bold"))
    print("=" * 60)
    
    print(f"\n{colorize('Summary:', 'bold')}")
    print(f"  Total frames:    {n}")
    print(f"  Duration:        {sum(frame_times)/1000:.1f}s")
    print(f"  Avg FPS:         {1000/avg_time:.1f}")
    
    print(f"\n{colorize('Frame Times (ms):', 'bold')}")
    print(f"  Min:             {min_time:.3f}")
    print(f"  Max:             {max_time:.3f}")
    print(f"  Average:         {avg_time:.3f}")
    
    print(f"\n{colorize('Percentiles (ms):', 'bold')}")
    print(f"  10th:            {p10:.3f}")
    print(f"  25th:            {p25:.3f}")
    print(f"  50th (median):   {p50:.3f}")
    print(f"  75th:            {p75:.3f}")
    print(f"  90th:            {p90:.3f}")
    
    print(f"\n{colorize('Variance Analysis:', 'bold')}")
    print(f"  Variance:        {variance:.3f}")
    print(f"  Std Deviation:   {stdev:.3f}")
    print(f"  Coeff of Var:    {(stdev/avg_time)*100:.1f}%")
    
    # Color-code dip stats
    dip_color = "green" if dip_rate < 1 else ("yellow" if dip_rate < 5 else "red")
    severe_color = "green" if severe_count == 0 else "red"
    
    print(f"\n{colorize('Dip Detection:', 'bold')}")
    print(f"  Threshold (2x median): {dip_threshold:.2f}ms")
    print(f"  Dip count:       {colorize(str(dip_count), dip_color)} ({dip_rate:.2f}%)")
    print(f"  Severe (3x):     {colorize(str(severe_count), severe_color)}")
    
    if dips:
        print(f"  Worst dips:      {', '.join(f'{t:.1f}ms' for t in sorted(dips, reverse=True)[:5])}")
    
    # Frame time histogram (simple text-based)
    print(f"\n{colorize('Distribution:', 'bold')}")
    buckets = [0, 10, 15, 20, 25, 30, 40, 50, 100, float('inf')]
    bucket_counts = [0] * (len(buckets) - 1)
    for t in frame_times:
        for i in range(len(buckets) - 1):
            if buckets[i] <= t < buckets[i + 1]:
                bucket_counts[i] += 1
                break
    
    max_count = max(bucket_counts) if bucket_counts else 1
    for i in range(len(buckets) - 1):
        lo = buckets[i]
        hi = buckets[i + 1]
        count = bucket_counts[i]
        pct = (count / n) * 100
        bar_len = int((count / max_count) * 30)
        bar = "█" * bar_len
        
        if hi == float('inf'):
            label = f"  {lo:3.0f}ms+      "
        else:
            label = f"  {lo:3.0f}-{hi:<3.0f}ms   "
        
        print(f"{label} {bar:30s} {count:5d} ({pct:5.1f}%)")
    
    # Phase breakdown
    if breakdown:
        print(f"\n{colorize('Phase Breakdown (avg / max ms):', 'bold')}")
        for phase in ['setup', 'clear', 'draw', 'traversal', 'render', 'composite', 'flip']:
            times = breakdown[phase]
            if times:
                avg = sum(times) / len(times)
                mx = max(times)
                # Highlight phases with high max times
                color = "red" if mx > 50 else ("yellow" if mx > 20 else "green")
                print(f"  {phase:12s}  {avg:7.3f} / {colorize(f'{mx:7.3f}', color)}")
        
        # Room count analysis
        room_counts = breakdown.get('room_count', [])
        if room_counts:
            print(f"\n{colorize('Room Count Analysis:', 'bold')}")
            print(f"  Min/Max:     {min(room_counts)} / {max(room_counts)}")
            print(f"  Unique vals: {sorted(set(room_counts))}")
            
            # Correlate draw time with room count
            draw_times = breakdown['draw']
            if len(draw_times) == len(room_counts):
                # Find slow frames and their room counts
                slow_threshold = percentile(draw_times, 90)
                slow_frames = [(dt, rc) for dt, rc in zip(draw_times, room_counts) if dt > slow_threshold]
                fast_frames = [(dt, rc) for dt, rc in zip(draw_times, room_counts) if dt < percentile(draw_times, 10)]
                
                if slow_frames:
                    avg_slow_count = sum(rc for _, rc in slow_frames) / len(slow_frames)
                    avg_fast_count = sum(rc for _, rc in fast_frames) / len(fast_frames) if fast_frames else 0
                    print(f"  Avg rooms in slow (p90+) frames: {avg_slow_count:.1f}")
                    print(f"  Avg rooms in fast (p10-) frames: {avg_fast_count:.1f}")
        
        # Iterations analysis
        iters = breakdown.get('iterations', [])
        if iters:
            print(f"\n{colorize('Traversal Details:', 'bold')}")
            print(f"  Iterations min/max: {min(iters)} / {max(iters)}")
            t_mm = breakdown.get('t_matmul', [])
            t_fr = breakdown.get('t_frustum', [])
            if t_mm:
                print(f"  Matrix mult avg/max: {sum(t_mm)/len(t_mm):.3f} / {max(t_mm):.3f} ms")
            if t_fr:
                print(f"  Frustum calc avg/max: {sum(t_fr)/len(t_fr):.3f} / {max(t_fr):.3f} ms")
    
    print("=" * 60 + "\n")
    
    # Return key metrics for comparison
    return {
        "avg": avg_time,
        "p50": p50,
        "p90": p90,
        "max": max_time,
        "stdev": stdev,
        "dip_count": dip_count,
        "dip_rate": dip_rate,
    }


def main():
    parser = argparse.ArgumentParser(description="Frame time variance analysis")
    parser.add_argument("--duration", "-d", type=int, default=60,
                        help="Test duration in seconds (default: 60)")
    args = parser.parse_args()
    
    frame_times, breakdown = run_dip_test(args.duration)
    print_report(frame_times, breakdown)


if __name__ == "__main__":
    main()
