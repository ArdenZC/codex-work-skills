# Content 2.4 practice starters

These Java SE 17 files are student starting points for the matching two-hour practice lessons. The input records, graph/tree structure, method signatures, failure contracts, and assertions are supplied; students complete only the marked `TODO` methods before running the checks.

From this directory, for example:

```sh
javac L14MSTLab.java
java L14MSTLab
```

The same pattern applies to the matching lesson file and class name. Each `main` prints `PASS` only after its expected-output assertions succeed. Run the class after implementing its TODOs; the placeholder methods intentionally throw until then. The frozen course records are repeated exactly as a synthetic fixture and are not additional business facts. Any `TEST-*`, `C-204`, or `NO-SUCH-ID` values are explicitly test-only payloads/queries; they do not represent course records.

| Lesson | Starter | Main checks |
| --- | --- | --- |
| L04 | `L04SeqListLab.java` | insert/find, fixed-capacity full result, valid/invalid indexes |
| L05 | `L05LinkedListLab.java` | empty/singleton/list boundaries, insert/remove/reverse, size and link invariants; empty `removeAt(0)` must throw and leave IDs, size, and structure unchanged |
| L06 | `L06StackQueueLab.java` | bracket error indexes, empty/full no-mutation, FIFO wrap-around |
| L11 | `L11TreeTraversalLab.java` | construct the G tree, then empty/single/left/right/G-tree preorder, inorder, postorder, level order |
| L12 | `L12BSTLab.java` | find, duplicate insert, leaf/one-child/two-child/missing deletion, per-delete size/inorder, successor-right-child reconnect |
| L13 | `L13GraphTraversalLab.java` | DFS/BFS order from A and E, whole-graph components |
| L14 | `L14MSTLab.java` | Prim/Kruskal edge sets and weights, input-edge membership, weight sum, copy-only deletion, isolated-F forest; partners edit separate starter copies, exchange and review methods, then merge both method bodies into one runnable file |
| L18 | `L18InsertionSortLab.java` | sorted IDs, stability, 8 key comparisons, 6 right shifts |
| L19 | `L19QuickSortLab.java` | Lomuto output and 7/6 deterministic comparison counts on two orders |
| L20 | `L20HashIndexLab.java` | collision slots, duplicate rejection, full-key lookup, bounded miss, full-table no-mutation overflow |

The output checks are classroom scaffolds, not a substitute for a teacher checking learner work or for the generated lesson review status.
