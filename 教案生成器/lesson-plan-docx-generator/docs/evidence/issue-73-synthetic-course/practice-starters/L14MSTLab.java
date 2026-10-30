import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

/** Student starter for L14. DSU, frozen graph, copy-on-write deletion, and assertions are supplied. */
public final class L14MSTLab {
    record Edge(String a, String b, int weight) {
        String minEndpoint() { return a.compareTo(b) <= 0 ? a : b; }
        String maxEndpoint() { return a.compareTo(b) <= 0 ? b : a; }
        String key() { return minEndpoint() + maxEndpoint(); }
    }
    record Result(List<Edge> edges, int totalWeight) {
        boolean isTree(Set<String> vertices) {
            if (edges.size() != vertices.size() - 1) return false;
            DisjointSet check = new DisjointSet(vertices);
            for (Edge e : edges) if (!check.union(e.a(), e.b())) return false;
            return check.componentCount() == 1;
        }
        boolean isForest(Set<String> vertices, int expectedComponents) {
            if (edges.size() != vertices.size() - expectedComponents) return false;
            DisjointSet check = new DisjointSet(vertices);
            for (Edge e : edges) if (!check.union(e.a(), e.b())) return false;
            return check.componentCount() == expectedComponents;
        }
    }

    private static final Comparator<Edge> ORDER = Comparator.comparingInt(Edge::weight)
            .thenComparing(Edge::minEndpoint).thenComparing(Edge::maxEndpoint);
    private static final Set<String> A_TO_E = Set.of("A", "B", "C", "D", "E");
    private static final Set<String> A_TO_F = Set.of("A", "B", "C", "D", "E", "F");
    private static final List<Edge> ORIGINAL = List.of(
            new Edge("A", "B", 4), new Edge("A", "C", 2), new Edge("B", "C", 1),
            new Edge("B", "D", 5), new Edge("C", "D", 8), new Edge("C", "E", 10),
            new Edge("D", "E", 2));

    private static final class DisjointSet {
        private final Map<String, String> parent = new HashMap<>();
        private final Map<String, Integer> size = new HashMap<>();
        private int components;
        DisjointSet(Set<String> vertices) {
            for (String v : vertices) { parent.put(v, v); size.put(v, 1); }
            components = vertices.size();
        }
        private String find(String v) {
            String p = parent.get(v);
            if (p == null) throw new IllegalArgumentException("unknown vertex " + v);
            if (!p.equals(v)) parent.put(v, find(p));
            return parent.get(v);
        }
        boolean union(String a, String b) {
            String ra = find(a), rb = find(b);
            if (ra.equals(rb)) return false;
            if (size.get(ra) < size.get(rb)) { String t = ra; ra = rb; rb = t; }
            parent.put(rb, ra); size.put(ra, size.get(ra) + size.get(rb)); components--;
            return true;
        }
        int componentCount() { return components; }
    }

    static Result prim(Set<String> vertices, List<Edge> edges, String start) {
        // TODO: seed the start component first, then seed remaining vertices in ascending order.
        // Each round choose the lightest edge U -> vertices\U; resolve ties with ORDER.
        // When no crossing edge remains, finish that component and continue to build a forest.
        throw new UnsupportedOperationException("complete prim");
    }

    static Result kruskal(Set<String> vertices, List<Edge> edges) {
        // TODO: sort by ORDER; use the supplied DSU; reject an edge whose union returns false.
        // Stop at |V|-1 accepted edges; a disconnected input returns a forest.
        throw new UnsupportedOperationException("complete kruskal");
    }

    private static List<Edge> withoutBC(List<Edge> source) {
        List<Edge> copy = new ArrayList<>(source);
        copy.removeIf(e -> e.key().equals("BC"));
        return List.copyOf(copy);
    }

    private static Set<String> edgeKeys(Result result) {
        return result.edges().stream().map(Edge::key).collect(Collectors.toSet());
    }

    private static void expectTree(
            Result result, List<Edge> input, int weight, Set<String> vertices,
            Set<String> expectedEdges, String label) {
        int edgeWeightSum = result.edges().stream().mapToInt(Edge::weight).sum();
        if (!input.containsAll(result.edges()) || edgeWeightSum != result.totalWeight()
                || result.totalWeight() != weight || !result.isTree(vertices)
                || !edgeKeys(result).equals(expectedEdges)) {
            throw new AssertionError(label + ": input membership, edge sum, tree, or edge set mismatch: " + result);
        }
    }

    private static void expectForest(
            Result result, List<Edge> input, int weight, Set<String> vertices,
            Set<String> expectedEdges, String label) {
        int edgeWeightSum = result.edges().stream().mapToInt(Edge::weight).sum();
        boolean isolatedF = result.edges().stream()
                .noneMatch(e -> e.a().equals("F") || e.b().equals("F"));
        if (!input.containsAll(result.edges()) || edgeWeightSum != result.totalWeight()
                || result.totalWeight() != weight || result.isTree(vertices)
                || !result.isForest(vertices, 2) || !edgeKeys(result).equals(expectedEdges) || !isolatedF) {
            throw new AssertionError(label + ": input membership, edge sum, forest components, or F-isolation mismatch: " + result);
        }
    }

    public static void main(String[] args) {
        Result primOriginal = prim(A_TO_E, ORIGINAL, "A");
        Result kruskalOriginal = kruskal(A_TO_E, ORIGINAL);
        Set<String> originalTree = Set.of("AC", "BC", "BD", "DE");
        expectTree(primOriginal, ORIGINAL, 10, A_TO_E, originalTree, "Prim original");
        expectTree(kruskalOriginal, ORIGINAL, 10, A_TO_E, originalTree, "Kruskal original");
        List<Edge> changed = withoutBC(ORIGINAL);
        Result primChanged = prim(A_TO_E, changed, "A");
        Result kruskalChanged = kruskal(A_TO_E, changed);
        Set<String> changedTree = Set.of("AB", "AC", "BD", "DE");
        expectTree(primChanged, changed, 13, A_TO_E, changedTree, "Prim without BC");
        expectTree(kruskalChanged, changed, 13, A_TO_E, changedTree, "Kruskal without BC");
        Result primForest = prim(A_TO_F, ORIGINAL, "A");
        Result kruskalForest = kruskal(A_TO_F, ORIGINAL);
        expectForest(primForest, ORIGINAL, 10, A_TO_F, originalTree, "Prim A-F forest");
        expectForest(kruskalForest, ORIGINAL, 10, A_TO_F, originalTree, "Kruskal A-F forest");
        if (!ORIGINAL.stream().anyMatch(e -> e.key().equals("BC"))) throw new AssertionError("main graph was modified");
        System.out.println("L14 PASS: A-E={AC,BC,BD,DE}/10; without BC={AB,AC,BD,DE}/13; A-F forest/10");
    }
}
