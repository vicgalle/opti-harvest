"""Replay the shipped west-bank routes and check their collection rules."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from island import Island, read_grid
from island_route import check_walk, read_walk


def main():
    terrain = read_grid(ROOT / 'examples/ginger-island/terrain.txt')
    for name in ('harvest', 'single-lap', 'side-only', 'high-yield', 'shorter-600'):
        board = Island(terrain, side_only=name == 'side-only')
        houses, flowers = board.decode(read_grid(HERE / f'{name}.txt'))
        walk = read_walk(board.start, (HERE / f'{name}-walk.txt').read_text())
        board.verify(houses, flowers)
        check_walk(board, houses, flowers, walk)
        if flowers & board.edge_beds:
            raise ValueError(f'{name} has a flower exposed to the survey boundary')
        visited = set(walk)
        steps = len(walk) - 1
        if name == 'single-lap' and (steps < 4 or len(visited) != steps):
            raise ValueError('single-lap revisits a standing tile before returning home')
        diagonals = sum(not (board.sides[p] & visited) for p in houses)
        print(f'{name} has {len(houses)} houses, {len(flowers)} roses, {board.pots(flowers)} pots, '
              f'{steps} steps, {len(visited)} distinct tiles and {diagonals} required diagonal pickups.')


if __name__ == '__main__':
    main()
