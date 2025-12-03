# Agent Instructions

## Performance Optimization

When working on rendering performance or any performance-related issues:

1. **Use `perf_test.py`** to measure before/after impact
3. Run `python perf_test.py --name "experment_description"` after changes to track how much each optimization affected performance
4. The report shows green for improvements, red for regressions
5. Pay attention to p90 and max times for stutter issues, not just averages

Key expensive areas identified:
- `hubA_near_edge`: Long corridor sightlines (often 100ms+)
- `hubB_center`: Large 8-sided hub with many connections
- `mirror_room`: Self-connecting room creates infinite recursion potential

## Code Style

- Don't add unnecessary comments
- Be careful of "bad splices" - match surrounding code style
- Check if new functionality should be commonized
- The main game loop is in `main.py`, rendering happens in `Room.draw()`

## Running the Game

```bash
python main.py
```

## Level Files

- `level.json`, `cool_level_1.json`, etc. are level files
- `leveledit.py` is the level editor
- `create_large_test_level()` in main.py generates a procedural test level
