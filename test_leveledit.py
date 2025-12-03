import unittest
import tempfile
import json
import pygame
import numpy as np
from unittest.mock import patch, MagicMock

# Import the module to test
import leveledit
from leveledit import EditorWorld, EditorRoom, EntitiesTool, export_level_to_json

# Import the Enemy class from main
from main import Enemy

class TestLevelEditor(unittest.TestCase):
    @patch('pygame.display.set_mode')
    def setUp(self, mock_set_mode):
        # Initialize pygame without a real display
        pygame.init()
        self.screen_size = (800, 600)
        
        # Setup global variables that the level editor uses
        leveledit.camera_offset = [0, 0]
        leveledit.zoom = 1.0
        leveledit.GRID_SIZE = 32
        leveledit.SNAP_TO_GRID = True
        leveledit.EDGE_CAMERA_MOVEMENT = True
        leveledit.SCREEN_CENTER = (self.screen_size[0] // 2, self.screen_size[1] // 2)
        
        # Mock the undo manager
        leveledit.undo_manager = MagicMock()
        
        # Create an editor world
        self.world = EditorWorld()
        
    def tearDown(self):
        # Clean up pygame
        pygame.quit()

    def test_entity_placement_and_export(self):
        """Create a room, simulate 3 clicks to place Enemy objects, export the level, and assert the level contains exactly 3 objects."""
        # Create a room
        room = EditorRoom([(100, 100), (300, 100), (300, 300), (100, 300)])
        self.world.add_room(room)
        
        # Create an entities tool and set it to place Enemy entities
        entities_tool = EntitiesTool()
        
        # Set the selected entity class to Enemy
        for cls in entities_tool.entity_classes:
            if cls.__name__ == "Enemy":
                entities_tool.selected_entity_class = cls
                break
        
        # We need these mocks for reliable entity placement:
        # - screen_to_world to ensure coordinates map correctly
        # - get_polygon_under_cursor to ensure the correct room is detected
        with patch('leveledit.screen_to_world', side_effect=lambda pos, *args: pos), \
             patch('leveledit.get_polygon_under_cursor', return_value=room):
            
            # Place entities at three different positions
            positions = [(150, 150), (200, 200), (250, 150)]
            
            for position in positions:
                # Create mock mouse event
                down_event = MagicMock()
                down_event.type = pygame.MOUSEBUTTONDOWN
                down_event.button = 1
                down_event.pos = position
                
                # Handle the event to place an entity
                entities_tool.handle_event(down_event, self.world, self.screen_size)
        
        # Verify we have 3 entities
        self.assertEqual(len(room.entities), 3, f"Expected 3 entities, got {len(room.entities)}")
        
        # Export to a temporary file
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as temp_file:
            temp_filename = temp_file.name
            export_level_to_json(
                self.world, 
                leveledit.GRID_SIZE, 
                leveledit.SNAP_TO_GRID, 
                leveledit.EDGE_CAMERA_MOVEMENT, 
                temp_filename
            )
        
        # Read the exported file
        with open(temp_filename, 'r') as f:
            data = json.load(f)
        
        # Verify the JSON contents
        self.assertEqual(len(data['rooms']), 1)
        exported_entities = data['rooms'][0]['entities']
        
        # Verify exactly 3 entities were exported
        self.assertEqual(len(exported_entities), 3)
        
        # Check for duplicate entity positions
        entity_positions = [tuple(e['pos']) for e in exported_entities]
        self.assertEqual(len(entity_positions), len(set(entity_positions)))

if __name__ == '__main__':
    unittest.main() 