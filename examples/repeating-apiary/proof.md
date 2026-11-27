# The shortest closed walk for collecting honey from the side

Count one step for a move north, south, east or west. A jar can be picked up from an adjacent tile in those four directions. The farmer can stand still to pick up several jars. A closed walk returns to its starting tile and can visit tiles or traverse edges more than once.

For any such walk of length $L\ge12$, at most **$2L-4$** distinct tiles next to it can hold houses. Being able to enter the lap from outside uses one of these tiles. Keeping both the outside and a courtyard inside the lap accessible uses two.

| Access requirement | Maximum number of houses beside the lap |
|---|---:|
| Entry from outside on foot | $2L-5$ |
| Entry from outside and an opening into an enclosed courtyard | $2L-6$ |

These are upper bounds for every shape. The [seven-row strips and square courtyard](README.md) attain them at the lengths specified there. Terrain and buildings can remove potential house sites. Diagonal collection or an open walk would change the problem.

## Counting neighboring tiles

Let $R$ be the distinct tiles visited on a walk, $n=|R|$, and $e$ the number of unordered cardinal neighbor pairs within $R$. Count every adjacent pair, including pairs the walk never traverses. Let $Q$ be the unvisited tiles sharing a side with $R$. A tile $q\in Q$ touches $a_q$ visited tiles. Setting $s=\sum_{q\in Q}(a_q-1)$ gives

$$
|Q| = 4n-2e-s.
$$

Indeed, the $n$ tiles have four sides each, each internal edge uses two sides, and the last term removes duplicate contacts.

### A simple cycle

First suppose the walk is a simple cycle of length $n\ge10$. Call the $c=e-n$ extra internal edges *chords*. Two or more chords already give $|Q|\le2n-4$. For zero or one chord, count the cycle's right-angle turns. It has at least four.

At a turn through tiles $a,b,d$, the fourth vertex $q=a+d-b$ of the unit square touches both $a$ and $d$. When $q$ is outside the cycle's visited tiles, charge the turn to $q$. A site with two visited neighbors can receive at most one turn, since the pair determines the intervening corner. A site with three visited neighbors can receive at most two. With four visited neighbors it can receive at most three. Charging it four times would force every edge of the eight-tile cycle surrounding that site to be in the walk. A simple cycle containing all those edges has length eight. Thus the number of externally charged turns is at most $s$.

If $q$ is itself visited, at least one of its two contacts with $a,d$ is a chord. Otherwise the walk would be the four-tile square. With zero chords, all the turns charge an external site, so $s\ge4$. With a single chord, each uncharged turn belongs to a unit square whose other three edges are consecutive cycle edges. This square has two such turns. Two such squares on opposite sides of the sole chord would make the entire cycle a six-tile rectangle. Thus at most two turns are uncharged and $s\ge2$. In each case $2c+s\ge4$, giving $|Q|\le2n-4$.

### Repeated tiles, crossings and backtracking

The graph on $R$ is connected. If it is a tree, every edge is a bridge and a closed walk crosses each bridge at least twice. Then $e=n-1$, $L\ge2(n-1)$, and $|Q|\le2n+2\le L+4\le2L-4$.

A connected graph with a cycle has $e\ge n$. If $n\le L-2$, the counting identity immediately gives $|Q|\le2L-4$. The same bound holds when $n=L-1$ and $e\ge n+1$.

The remaining case has $n=L-1$ and $e=n$, so the graph has exactly one cycle. In the cyclic list of $L$ positions a single tile occurs twice and every other tile occurs once. Splitting the walk at the repeated tile gives two closed pieces. They cannot both be simple cycles, as that would give the graph two cycles. One piece therefore goes out and immediately back. The other is a simple cycle of length $L-2\ge10$. Adding the one extra tile to that cycle removes the tile itself from its old neighborhood and adds at most three new sites. Its boundary grows by at most two, giving $|Q|\le2(L-2)-4+2\le2L-4$.

### Entrances and the return trip

To enter a lap on foot from the exterior, the last step onto the visited set comes from a tile in $Q$ that must stay open. When the lap separates the courtyard from outside, the first step off the lap toward the courtyard also needs an open tile in $Q$. Its connected component off the lap is different from the exterior component, so the two openings cost two different potential houses.

If the **walk itself** starts on a straight plot boundary and stays on the plot, it can serve at most **$2L-6$** on-plot houses for $L\ge14$. If two visited tiles touch the boundary line, each has a distinct off-plot neighbor. If just one visited tile $p$ touches the line, its only neighbor in the walk points into the plot. Delete one two-step visit to $p$, rotating the start of the cyclic walk if necessary. This leaves either the identical visited set or the old set minus $p$. Reattaching a single side-adjacent tile adds at most two neighbors. Applying the preceding bound to the $L-2$ walk gives $|Q|\le2(L-2)-4+2=2L-6$.

All closed cardinal walks have even length. A strip with $2L-5$ houses therefore takes at least $L$ steps from a lap tile and at least $L+2$ from its boundary gate. The printed walks attain both bounds. Walks shorter than 12 cannot serve the smallest strip's 35 houses, since connectivity alone gives $|Q|\le2n+2\le2L+2$.

## Exhaustive check

An independent enumerator walks the square lattice directly, recording distinct visited tiles and their cardinal neighbors. It includes self-touching walks, repeated vertices, repeated edges and immediate reversals. At each even length, the total number of oriented walks agrees with $\binom{L}{L/2}^2$.

| Steps | Closed walks | Maximum distinct side-neighbors |
|---:|---:|---:|
| 2 | 4 | 6 |
| 4 | 36 | 8 |
| 6 | 400 | 10 |
| 8 | 4,900 | 13 |
| 10 | 63,504 | 16 |
| 12 | 853,776 | 20 |
| 14 | 11,778,624 | 24 |
| 16 | 165,636,900 | 28 |
| 18 | 2,363,904,400 | 32 |

The eight-step cycle around a single tile illustrates why the qualification on the theorem's length matters. Run from the repository root with a C99 compiler.

```sh
cc -std=c99 -O3 examples/repeating-apiary/check_walks.c -o /tmp/check-bee-walks
/tmp/check-bee-walks 18
```
