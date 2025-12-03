def perturb_world(world: GameWorld, perturbation_magnitude = 0.2):
    """Jostle all the vertices of all the rooms in the world, ensuring they remain convex and connected edges remain
    the same length."""
    # Store all connections before perturbing
    connections = []
    for room1 in world.graph.nodes:
        for edge_idx1, edge in enumerate(room1.edges):
            if edge.target_room and id(room1) < id(edge.target_room):  # Only store each connection once
                connections.append((
                    room1, edge_idx1,
                    edge.target_room, edge.target_edge_idx
                ))

    # Clear all connections
    for room in world.graph.nodes:
        for edge in room.edges:
            edge.target_room = None
            edge.target_edge_idx = None
            edge.transform = np.eye(3)

    # Randomly perturb vertices of all rooms

    def is_convex(vertices):
        """Check if a polygon is convex using cross product method."""
        n = len(vertices)
        sign = 0

        for i in range(n):
            p1 = np.array(vertices[i])
            p2 = np.array(vertices[(i + 1) % n])
            p3 = np.array(vertices[(i + 2) % n])

            # Calculate cross product of vectors p1->p2 and p2->p3
            v1 = p2 - p1
            v2 = p3 - p2
            cross = np.cross(v1, v2)

            if sign == 0:
                sign = np.sign(cross)
            elif sign * cross <= 0:
                return False
        return True

    for room in world.graph.nodes:
        # Calculate room's average radius
        radius = np.mean([np.linalg.norm(v) for v in room.vertices])
        max_perturbation = radius * perturbation_magnitude

        # Keep trying until we get a valid perturbation that maintains convexity
        for attempt in range(10):  # Limit attempts to avoid infinite loop
            new_vertices = []
            for x, y in room.vertices:
                dx = (random.random() * 2 - 1) * max_perturbation
                dy = (random.random() * 2 - 1) * max_perturbation
                new_vertices.append((x + dx, y + dy))

            if is_convex(new_vertices):
                room.vertices = new_vertices
                break

    # Normalize lengths of connected edges
    def normalize_edge_length(v1, v2, target_length):
        """Adjust two vertices to make their edge a specific length while preserving midpoint."""
        vec = np.array(v2) - np.array(v1)
        current_length = np.linalg.norm(vec)
        scale = target_length / current_length

        # Get midpoint and scaled half-vector
        mid = (np.array(v1) + np.array(v2)) / 2
        half_vec = vec * scale / 2

        # Return new points that preserve midpoint
        return mid - half_vec, mid + half_vec

    # First pass: calculate average length for each connected edge pair
    edge_lengths = {}  # (room_id, edge_idx) -> [length]
    for room1, edge1_idx, room2, edge2_idx in connections:
        # Get vertices for both edges
        start1, end1 = room1.get_edge_vertices(edge1_idx)
        start2, end2 = room2.get_edge_vertices(edge2_idx)

        # Calculate lengths
        length1 = np.linalg.norm(np.array(end1) - np.array(start1))
        length2 = np.linalg.norm(np.array(end2) - np.array(start2))

        # Store lengths (we'll average them later)
        key1 = (id(room1), edge1_idx)
        key2 = (id(room2), edge2_idx)
        edge_lengths.setdefault(key1, []).append(length1)
        edge_lengths.setdefault(key2, []).append(length2)

    # Calculate target lengths (average of all connected edges)
    target_lengths = {key: np.mean(lengths) for key, lengths in edge_lengths.items()}

    # Second pass: adjust vertices to match target lengths
    vertices_to_update = {}  # (room_id, vertex_idx) -> [new_positions]

    for room1, edge1_idx, room2, edge2_idx in connections:
        # Get target lengths for both edges
        key1 = (id(room1), edge1_idx)
        key2 = (id(room2), edge2_idx)
        target_length = (target_lengths[key1] + target_lengths[key2]) / 2

        # Normalize first edge
        start1, end1 = room1.get_edge_vertices(edge1_idx)
        new_start1, new_end1 = normalize_edge_length(start1, end1, target_length)

        # Store new vertex positions
        vertices_to_update.setdefault((id(room1), edge1_idx), []).append(new_start1)
        vertices_to_update.setdefault((id(room1), (edge1_idx + 1) % room1.num_sides), []).append(new_end1)

        # Normalize second edge
        start2, end2 = room2.get_edge_vertices(edge2_idx)
        new_start2, new_end2 = normalize_edge_length(start2, end2, target_length)

        # Store new vertex positions
        vertices_to_update.setdefault((id(room2), edge2_idx), []).append(new_start2)
        vertices_to_update.setdefault((id(room2), (edge2_idx + 1) % room2.num_sides), []).append(new_end2)

    # Update vertices (averaging any vertices that got multiple positions)
    for room in world.graph.nodes:
        for i in range(room.num_sides):
            key = (id(room), i)
            if key in vertices_to_update:
                positions = vertices_to_update[key]
                room.vertices[i] = tuple(np.mean(positions, axis=0))

    # Reconnect all rooms with new transforms
    for room1, edge1_idx, room2, edge2_idx in connections:
        world.connect_rooms(room1, edge1_idx, room2, edge2_idx)

    return world

def debug_room(room):
    """Debug helper that prints detailed information about a room and its edges."""
    print(f"\nRoom {room.room_number}:")
    print("Vertices:", room.vertices)

    for i, edge in enumerate(room.edges):
        start = room.vertices[i]
        end = room.vertices[(i + 1) % room.num_sides]
        edge_vec = np.array(end) - np.array(start)

        print(f"\nEdge {i}:")
        print("  Start:", start)
        print("  End:", end)
        print("  Vector:", edge_vec)
        print("  Length:", np.linalg.norm(edge_vec))

        if edge.target_room:
            print("  Connected to room:", edge.target_room.room_number)
            print("  Target edge idx:", edge.target_edge_idx)
            print("  Transform matrix:")
            print(edge.transform)

            # Check the corresponding edge in the target room
            target_start = edge.target_room.vertices[edge.target_edge_idx]
            target_end = edge.target_room.vertices[(edge.target_edge_idx + 1) % edge.target_room.num_sides]
            print("  Target edge:")
            print("    Start:", target_start)
            print("    End:", target_end)

            # Test transform
            transformed_start = edge.transform @ np.array([target_start[0], target_start[1], 1])
            transformed_end = edge.transform @ np.array([target_end[0], target_end[1], 1])
            print("  Transform check:")
            print("    Target start transformed:", transformed_start[:2])
            print("    Target end transformed:", transformed_end[:2])
            print("    Should match:", start, end)

            # Check inverse transform
            target_edge = edge.target_room.edges[edge.target_edge_idx]
            if not np.allclose(np.linalg.inv(edge.transform), target_edge.transform):
                print("  WARNING: Transform and inverse don't match!")
                print("    Our transform to them:", edge.transform)
                print("    Their transform to us:", target_edge.transform)
                print("    Our inverse:", np.linalg.inv(edge.transform))
        else:
            print("  No connection")


def check_room_connections(world):
    """Verify consistency of room connections in the world."""
    print("\nChecking room connections...")
    visited = set()

    def visit_room(room, transform=np.eye(3), depth=0):
        if depth > 10 or id(room) in visited:
            return
        visited.add(id(room))

        # Debug this room
        debug_room(room)

        # Visit connected rooms
        for edge in room.edges:
            if edge.target_room and id(edge.target_room) not in visited:
                new_transform = transform @ edge.transform
                visit_room(edge.target_room, new_transform, depth + 1)

    visit_room(world._root_room)


# Example usage:
def test_debug():
    world = create_test_level()
    check_room_connections(world)
    return world
