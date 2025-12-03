#!/usr/bin/env python3
"""
Performance Test Script for Non-Euclidean Top-Down Shooter
===========================================================

This script benchmarks rendering performance across 10 strategic positions
in the large test level. Use it to measure the impact of optimizations.

USAGE
-----
Quick benchmark (no save):
    python perf_test.py

Save results as named experiment:
    python perf_test.py --name "baseline"
    python perf_test.py -n "removed_redundant_blits"

WORKFLOW
--------
1. Run with --name "baseline" before making changes
2. Make your optimization
3. Run with --name "description_of_change"
4. Review the report - green % means improvement, red means regression
5. If regression, undo and try again. If improvement, commit!

TEST POSITIONS (10 locations, 10 frames each)
---------------------------------------------
- hubA_center:        Main starting hub (6-sided)
- hubA_near_edge:     Looking into corridor (expensive long sightlines!)
- hubB_center:        Largest hub (8-sided, many connections)
- corridor_mid:       Corridor midpoint (sightlines both ways)
- mirror_room_center: Self-connecting room (infinite reflections)
- mirror_room_edge:   Near the self-connection edge
- cycle_room:         Loop structure
- spiral_center:      Deep in spiral
- cluster_center:     Dense interconnected rooms
- maze_mid:           Complex branching maze

METRICS
-------
- Average frame time: Overall performance
- 75th/90th percentile: Stutter detection (high p90 = inconsistent frames)
- Maximum: Worst-case spikes
- Per-position avg/max: Identify which areas are problematic

The history compares against the best "improvement" experiment as baseline.
Experiments marked with ✓ beat the previous baseline, ✗ regressed.

OUTPUT FILES
------------
- perf_history.json: Persistent experiment history (can delete to reset)
"""

import argparse
import json
import os
import random
import time
from datetime import datetime

import numpy as np
import pygame
from pygame import BLEND_RGBA_MULT

from main import (
    Camera,
    Room,
    Player,
    GameWorld,
)

PERF_DATA_FILE = "perf_history.json"
FRAMES_PER_POSITION = 10
SCREEN_SIZE = (800, 600)


def create_large_test_level_with_refs() -> tuple:
    """
    Create the large test level and return (world, named_rooms_dict).
    Named rooms dict contains references to interesting locations.
    """
    random.seed(42)  # Deterministic for consistent benchmarks
    
    world = GameWorld()
    refs = {}
    
    # Create hubs
    hubA = world.create_room(6)
    hubB = world.create_room(8)
    hubC = world.create_room(5)
    hubD = world.create_room(7)
    hubE = world.create_room(4)
    
    refs["hubA"] = hubA
    refs["hubB"] = hubB
    refs["hubC"] = hubC
    refs["hubD"] = hubD
    refs["hubE"] = hubE

    # Helper to connect two rooms via a corridor chain
    def connect_with_corridor(r1, edge1, r2, edge2, length):
        prev = world.create_room(4)
        world.connect_rooms(r1, edge1, prev, 0)
        corridor_rooms = [prev]
        for _ in range(length):
            new_corr = world.create_room(random.choice([3, 4, 5]))
            safe_edge = 1 % prev.num_sides
            target_edge = 3 if new_corr.num_sides > 3 else new_corr.num_sides - 1
            world.connect_rooms(prev, safe_edge, new_corr, target_edge)
            corridor_rooms.append(new_corr)
            prev = new_corr
        world.connect_rooms(prev, 2, r2, edge2)
        return corridor_rooms

    # Connect hubs by long corridors
    corridor_A_B = connect_with_corridor(hubA, 0, hubB, 4, length=5)
    refs["corridor_mid"] = corridor_A_B[len(corridor_A_B) // 2]
    
    connect_with_corridor(hubB, 2, hubC, 1, length=6)
    connect_with_corridor(hubC, 0, hubD, 3, length=4)
    connect_with_corridor(hubD, 2, hubE, 1, length=5)
    connect_with_corridor(hubE, 3, hubA, 5, length=6)
    connect_with_corridor(hubA, 1, hubC, 2, length=4)
    connect_with_corridor(hubB, 6, hubD, 4, length=5)

    # Additional branching corridors from hubs
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

    # Cycle loop branching off hubB
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
    refs["cycle_room"] = cycle_rooms[len(cycle_rooms) // 2]

    # Spiral loop branching off hubD
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
    refs["spiral_center"] = spiral_rooms[3]

    # Mirror corridor: self-connecting room
    mirror_corridor = world.create_room(4)
    world.connect_rooms(hubC, 4, mirror_corridor, 0)
    mirror_room = world.create_room(8)
    world.connect_rooms(mirror_corridor, 2, mirror_room, 0)
    world.connect_rooms(mirror_room, 3, mirror_room, 7)
    refs["mirror_room"] = mirror_room

    # Dense cluster branching off hubE
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
    refs["cluster_center"] = cluster_center

    # Maze-like branch off hubA
    maze_start = world.create_room(4)
    world.connect_rooms(hubA, 3, maze_start, 0)
    maze_rooms = [maze_start]
    prev = maze_start
    for _ in range(8):
        new_room = world.create_room(random.choice([3, 4, 5]))
        safe_edge = 1 if prev.num_sides > 1 else 0
        target_edge = 3 if new_room.num_sides > 3 else new_room.num_sides - 1
        world.connect_rooms(prev, safe_edge, new_room, target_edge)
        maze_rooms.append(new_room)
        prev = new_room
    world.connect_rooms(prev, 2, hubD, 5)
    refs["maze_mid"] = maze_rooms[4]

    # Set the player's starting position at hubA
    world.player = Player(hubA, np.zeros(2))
    
    return world, refs


def get_test_positions(world, refs: dict) -> list:
    """Get 10 strategic (room, position, name) tuples to test rendering."""
    positions = []
    
    # 1. HubA center - main starting hub (6-sided)
    positions.append((refs["hubA"], np.zeros(2), "hubA_center"))
    
    # 2. HubA near edge - looking into corridor
    hubA = refs["hubA"]
    edge_pos = hubA.vertices[0] * 0.7
    positions.append((hubA, edge_pos, "hubA_near_edge"))
    
    # 3. HubB - largest hub (8-sided, many connections)
    positions.append((refs["hubB"], np.zeros(2), "hubB_center"))
    
    # 4. Corridor midpoint - long sightlines both ways
    positions.append((refs["corridor_mid"], np.zeros(2), "corridor_mid"))
    
    # 5. Mirror room - self-connecting (infinite reflections)
    positions.append((refs["mirror_room"], np.zeros(2), "mirror_room_center"))
    
    # 6. Mirror room near self-connection edge
    mirror = refs["mirror_room"]
    mirror_edge_pos = mirror.vertices[3] * 0.6
    positions.append((mirror, mirror_edge_pos, "mirror_room_edge"))
    
    # 7. Cycle room - loop structure
    positions.append((refs["cycle_room"], np.zeros(2), "cycle_room"))
    
    # 8. Spiral center - deep in spiral structure
    positions.append((refs["spiral_center"], np.zeros(2), "spiral_center"))
    
    # 9. Dense cluster - many interconnected rooms
    positions.append((refs["cluster_center"], np.zeros(2), "cluster_center"))
    
    # 10. Maze midpoint - complex branching
    positions.append((refs["maze_mid"], np.zeros(2), "maze_mid"))
    
    return positions


def render_frame(world, room, pos, surfaces):
    """Render a single frame and return the time taken."""
    room_layer, entity_layer, mask_layer1, mask_layer2, entities_mask, work_layer, screen = surfaces
    
    # Set up camera
    Camera.target_room = room
    center = np.array(SCREEN_SIZE) / 2
    Camera.transform = np.array([
        [1, 0, center[0] - pos[0]],
        [0, 1, center[1] - pos[1]],
        [0, 0, 1]
    ], dtype=float)
    
    # Clear surfaces
    screen.fill((0, 0, 0))
    room_layer.fill((0, 0, 0, 0))
    entity_layer.fill((0, 0, 0, 0))
    entities_mask.fill((0, 0, 0, 0))
    mask_layer1.fill((0, 0, 0, 0))
    mask_layer2.fill((0, 0, 0, 0))
    work_layer.fill((0, 0, 0, 0))
    
    start_time = time.perf_counter()
    
    # Draw world
    room.draw(
        room_layer=room_layer,
        entity_layer=entity_layer,
        mask_layer1=mask_layer1,
        mask_layer2=mask_layer2,
        entities_mask=entities_mask,
        work_layer=work_layer,
        local_to_screen=Camera.transform,
        viewpoint=pos
    )
    
    # Composite layers
    screen.blit(room_layer, (0, 0))
    entity_layer.blit(entities_mask, (0, 0), special_flags=BLEND_RGBA_MULT)
    screen.blit(entity_layer, (0, 0))
    
    pygame.display.flip()
    
    end_time = time.perf_counter()
    return (end_time - start_time) * 1000  # Return ms


def percentile(data: list, p: float) -> float:
    """Calculate the p-th percentile of a list of numbers."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * (p / 100)
    f = int(k)
    c = f + 1 if f + 1 < len(sorted_data) else f
    return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])


def run_benchmark() -> dict:
    """Run the benchmark and return frame time results."""
    pygame.init()
    screen = pygame.display.set_mode(SCREEN_SIZE)
    pygame.display.set_caption("Performance Test")
    
    # Create rendering surfaces
    room_layer = pygame.Surface(SCREEN_SIZE)
    entity_layer = pygame.Surface(SCREEN_SIZE, pygame.SRCALPHA)
    mask_layer1 = pygame.Surface(SCREEN_SIZE, pygame.SRCALPHA)
    mask_layer2 = pygame.Surface(SCREEN_SIZE, pygame.SRCALPHA)
    entities_mask = pygame.Surface(SCREEN_SIZE, pygame.SRCALPHA)
    work_layer = pygame.Surface(SCREEN_SIZE, pygame.SRCALPHA)
    
    surfaces = (room_layer, entity_layer, mask_layer1, mask_layer2, entities_mask, work_layer, screen)
    
    # Create the test level
    world, refs = create_large_test_level_with_refs()
    
    # Get test positions
    positions = get_test_positions(world, refs)
    
    results = {
        "positions": [],
        "frame_times_ms": [],
        "avg_frame_time_ms": 0.0,
        "p75_frame_time_ms": 0.0,
        "p90_frame_time_ms": 0.0,
        "max_frame_time_ms": 0.0,
    }
    
    all_frame_times = []
    
    for room, pos, name in positions:
        position_times = []
        
        # Warm-up frame
        render_frame(world, room, pos, surfaces)
        
        # Timed frames
        for _ in range(FRAMES_PER_POSITION):
            frame_time = render_frame(world, room, pos, surfaces)
            position_times.append(frame_time)
            all_frame_times.append(frame_time)
        
        avg_time = sum(position_times) / len(position_times)
        results["positions"].append({
            "name": name,
            "avg_ms": avg_time,
            "max_ms": max(position_times),
            "times_ms": position_times
        })
    
    results["frame_times_ms"] = all_frame_times
    results["avg_frame_time_ms"] = sum(all_frame_times) / len(all_frame_times) if all_frame_times else 0.0
    results["p75_frame_time_ms"] = percentile(all_frame_times, 75)
    results["p90_frame_time_ms"] = percentile(all_frame_times, 90)
    results["max_frame_time_ms"] = max(all_frame_times) if all_frame_times else 0.0
    
    pygame.quit()
    return results


def load_history() -> dict:
    """Load experiment history from file."""
    if os.path.exists(PERF_DATA_FILE):
        try:
            with open(PERF_DATA_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"experiments": [], "baseline_avg_ms": None}


def save_history(history: dict):
    """Save experiment history to file."""
    with open(PERF_DATA_FILE, 'w') as f:
        json.dump(history, f, indent=2)


def save_experiment(name: str, results: dict):
    """Save experiment results to history, overwriting if name exists."""
    history = load_history()
    
    experiment = {
        "name": name,
        "timestamp": datetime.now().isoformat(),
        "avg_frame_time_ms": results["avg_frame_time_ms"],
        "p75_frame_time_ms": results["p75_frame_time_ms"],
        "p90_frame_time_ms": results["p90_frame_time_ms"],
        "max_frame_time_ms": results["max_frame_time_ms"],
        "positions": results["positions"],
        "is_improvement": True  # Default to True
    }
    
    # Check if this is an improvement compared to baseline
    if history["baseline_avg_ms"] is not None:
        if results["avg_frame_time_ms"] < history["baseline_avg_ms"]:
            experiment["is_improvement"] = True
            history["baseline_avg_ms"] = results["avg_frame_time_ms"]
        else:
            experiment["is_improvement"] = False
    else:
        history["baseline_avg_ms"] = results["avg_frame_time_ms"]
    
    # Find and replace existing experiment with same name, or append
    found = False
    for i, exp in enumerate(history["experiments"]):
        if exp["name"] == name:
            history["experiments"][i] = experiment
            found = True
            break
    
    if not found:
        history["experiments"].append(experiment)
    
    # Recalculate baseline: it's the best improvement so far
    improvements = [e for e in history["experiments"] if e.get("is_improvement", True)]
    if improvements:
        history["baseline_avg_ms"] = min(e["avg_frame_time_ms"] for e in improvements)
    
    save_history(history)


def colorize(text: str, color: str) -> str:
    """Add ANSI color codes to text."""
    colors = {
        "green": "\033[92m",
        "red": "\033[91m",
        "yellow": "\033[93m",
        "reset": "\033[0m",
        "bold": "\033[1m",
    }
    return f"{colors.get(color, '')}{text}{colors['reset']}"


def print_report(results: dict, experiment_name: str = None):
    """Print the performance report with history."""
    history = load_history()
    
    print("\n" + "=" * 60)
    print(colorize("  RENDERING PERFORMANCE REPORT", "bold"))
    print("=" * 60)
    
    # Current run results
    print(f"\n{colorize('Current Run:', 'bold')}")
    if experiment_name:
        print(f"  Experiment: {experiment_name}")
    print(f"  Average frame time: {results['avg_frame_time_ms']:.3f} ms")
    print(f"  75th percentile:    {results['p75_frame_time_ms']:.3f} ms")
    print(f"  90th percentile:    {results['p90_frame_time_ms']:.3f} ms")
    print(f"  Maximum:            {results['max_frame_time_ms']:.3f} ms")
    print(f"  Estimated FPS:      {1000 / results['avg_frame_time_ms']:.1f} (avg) / {1000 / results['p90_frame_time_ms']:.1f} (p90)")
    print(f"  Samples per position: {FRAMES_PER_POSITION}")
    
    print(f"\n  {colorize('Per-position breakdown:', 'bold')}")
    print(f"    {'Position':25s} {'Avg':>10s} {'Max':>10s}")
    print(f"    {'-'*25} {'-'*10} {'-'*10}")
    for pos in results["positions"]:
        print(f"    {pos['name']:25s} {pos['avg_ms']:>9.3f}ms {pos['max_ms']:>9.3f}ms")
    
    # History comparison
    if history["experiments"]:
        print(f"\n{colorize('Experiment History:', 'bold')}")
        print("-" * 60)
        
        baseline = history.get("baseline_avg_ms")
        
        for exp in history["experiments"]:
            name = exp["name"]
            avg_ms = exp["avg_frame_time_ms"]
            timestamp = exp.get("timestamp", "unknown")[:10]  # Just the date
            is_improvement = exp.get("is_improvement", True)
            
            # Calculate diff from baseline
            if baseline and baseline > 0:
                diff_ms = avg_ms - baseline
                diff_pct = (diff_ms / baseline) * 100
                
                if abs(diff_pct) < 0.5:
                    diff_str = colorize(f" (baseline)", "yellow")
                elif diff_ms < 0:
                    diff_str = colorize(f" ({diff_pct:+.1f}%)", "green")
                else:
                    diff_str = colorize(f" ({diff_pct:+.1f}%)", "red")
            else:
                diff_str = ""
            
            status = colorize("✓", "green") if is_improvement else colorize("✗", "red")
            print(f"  {status} {name:25s} {avg_ms:7.3f} ms  [{timestamp}]{diff_str}")
        
        if baseline:
            print("-" * 60)
            print(f"  Best baseline: {baseline:.3f} ms ({1000/baseline:.1f} FPS)")
    
    print("=" * 60 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Performance test for rendering")
    parser.add_argument("--name", "-n", type=str, default=None,
                        help="Experiment name (saves results if provided)")
    args = parser.parse_args()
    
    print("Running performance benchmark on create_large_test_level()...")
    print(f"Testing 10 positions, {FRAMES_PER_POSITION} frames each...")
    results = run_benchmark()
    
    if args.name:
        save_experiment(args.name, results)
        print(f"Saved experiment: {args.name}")
    
    print_report(results, args.name)


if __name__ == "__main__":
    main()
