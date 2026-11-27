/* Exhaustively count distinct side-neighbor sites for every closed square-grid
   walk. Rotating its first step east removes a factor of four. */
#include <stdio.h>
#include <stdlib.h>

enum { MAX_STEPS = 18, WIDTH = 2 * MAX_STEPS + 5, MID = WIDTH / 2 };
static const int origin = MID * WIDTH + MID;
static const int steps[] = {1, -1, WIDTH, -WIDTH};
static int visits[WIDTH * WIDTH], contacts[WIDTH * WIDTH];
static int x_occupied[WIDTH], y_occupied[WIDTH];
static int best[MAX_STEPS + 1], best_from_edge[MAX_STEPS + 1], limit;
static long long total[MAX_STEPS + 1];

static int visit(int tile) {
    if (++visits[tile] > 1) return 0;
    ++x_occupied[tile % WIDTH];
    ++y_occupied[tile / WIDTH];
    int delta = -(contacts[tile] > 0);
    for (int i = 0; i < 4; ++i) {
        int neighbor = tile + steps[i];
        if (++contacts[neighbor] == 1 && !visits[neighbor]) ++delta;
    }
    return delta;
}

static void leave(int tile) {
    if (--visits[tile]) return;
    --x_occupied[tile % WIDTH];
    --y_occupied[tile / WIDTH];
    for (int i = 0; i < 4; ++i) --contacts[tile + steps[i]];
}

static int min(int a, int b) { return a < b ? a : b; }

/* Put a straight plot boundary against each extreme of the visited set.
   Every distinct visited tile there has a different off-plot neighbor. */
static int cheapest_edge(void) {
    int west = MID, east = MID, north = MID, south = MID;
    while (x_occupied[west - 1]) --west;
    while (x_occupied[east + 1]) ++east;
    while (y_occupied[north - 1]) --north;
    while (y_occupied[south + 1]) ++south;
    return min(min(x_occupied[west], x_occupied[east]),
               min(y_occupied[north], y_occupied[south]));
}

static void enumerate(int tile, int length, int boundary) {
    if (tile == origin) {
        ++total[length];
        if (boundary > best[length]) best[length] = boundary;
        if (boundary > best_from_edge[length]) {
            int on_plot = boundary - cheapest_edge();
            if (on_plot > best_from_edge[length]) best_from_edge[length] = on_plot;
        }
    }
    if (length == limit) return;
    for (int i = 0; i < 4; ++i) {
        int next = tile + steps[i];
        int remaining = abs(next % WIDTH - MID) + abs(next / WIDTH - MID);
        if (length + 1 + remaining > limit) continue;
        int added = visit(next);
        enumerate(next, length + 1, boundary + added);
        leave(next);
    }
}

int main(int argc, char **argv) {
    limit = argc > 1 ? atoi(argv[1]) : 12;
    if (limit < 2 || limit > MAX_STEPS || limit % 2) {
        fprintf(stderr, "Choose an even maximum length from 2 to %d.\n", MAX_STEPS);
        return 1;
    }
    int boundary = visit(origin);
    boundary += visit(origin + 1);
    enumerate(origin + 1, 1, boundary);
    puts("steps  closed_walks  side_neighbors  on_plot_neighbors_from_edge");
    for (int length = 2; length <= limit; length += 2)
        printf("%5d %13lld %15d %28d\n",
               length, 4 * total[length], best[length], best_from_edge[length]);
    return 0;
}
