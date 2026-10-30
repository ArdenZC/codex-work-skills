import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Deque;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** Student starter for L13. Neighbors are visited in ascending vertex order. */
public final class L13GraphTraversalLab {
    private final Map<String, Set<String>> adj = new LinkedHashMap<>();

    public L13GraphTraversalLab() {
        for (String v : List.of("A", "B", "C", "D", "E", "F")) adj.put(v, new LinkedHashSet<>());
        for (String[] e : List.<String[]>of(new String[] {"A", "B"}, new String[] {"A", "C"},
                new String[] {"B", "C"}, new String[] {"B", "D"}, new String[] {"C", "D"},
                new String[] {"C", "E"}, new String[] {"D", "E"})) addEdge(e[0], e[1]);
    }

    private void addEdge(String a, String b) { adj.get(a).add(b); adj.get(b).add(a); }

    public List<String> dfs(String start) {
        // TODO: mark each vertex on first entry; preserve ascending-neighbor order.
        throw new UnsupportedOperationException("complete dfs");
    }

    public List<String> bfs(String start) {
        // TODO: mark before enqueue so a shared neighbor is queued only once.
        throw new UnsupportedOperationException("complete bfs");
    }

    public List<List<String>> components() {
        // TODO: scan A..F and start another traversal for each unvisited vertex.
        throw new UnsupportedOperationException("complete components");
    }

    private static void expect(List<String> actual, String... expected) {
        List<String> want = List.of(expected);
        if (!actual.equals(want)) throw new AssertionError("expected " + want + ", got " + actual);
    }

    public static void main(String[] args) {
        L13GraphTraversalLab graph = new L13GraphTraversalLab();
        expect(graph.dfs("A"), "A", "B", "C", "D", "E");
        expect(graph.bfs("A"), "A", "B", "C", "D", "E");
        expect(graph.dfs("E"), "E", "C", "A", "B", "D");
        expect(graph.bfs("E"), "E", "C", "D", "A", "B");
        List<List<String>> want = List.of(List.of("A", "B", "C", "D", "E"), List.of("F"));
        if (!graph.components().equals(want)) throw new AssertionError("component partition mismatch");
        System.out.println("L13 PASS: DFS/BFS order and component assertions");
    }
}
