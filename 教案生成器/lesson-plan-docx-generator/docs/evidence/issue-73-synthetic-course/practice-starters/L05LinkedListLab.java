import java.util.ArrayList;
import java.util.List;

/** Student starter for L05. Fill the three TODO methods, then run the assertions. */
public final class L05LinkedListLab {
    private static final class Node {
        final String id;
        Node next;

        Node(String id) { this.id = id; }
    }

    private final Node dummy = new Node(null);
    private int size;

    public int size() { return size; }

    public void insertAt(int index, String id) {
        // TODO: require 0 <= index <= size; find the predecessor; link the new node; size++.
        throw new UnsupportedOperationException("complete insertAt");
    }

    public String removeAt(int index) {
        // TODO: require 0 <= index < size; unlink and detach the node; size--; return its id.
        throw new UnsupportedOperationException("complete removeAt");
    }

    public void reverse() {
        // TODO: use prev/cur/next; save next before changing cur.next; reconnect dummy.next.
        throw new UnsupportedOperationException("complete reverse");
    }

    public List<String> ids() {
        List<String> result = new ArrayList<>();
        for (Node p = dummy.next; p != null; p = p.next) result.add(p.id);
        return result;
    }

    public void assertInvariant() {
        int count = 0;
        Node tail = null;
        for (Node p = dummy.next; p != null; p = p.next) {
            if (++count > size) throw new AssertionError("cycle or size mismatch");
            tail = p;
        }
        if (count != size) throw new AssertionError("node count must equal size");
        if (tail != null && tail.next != null) throw new AssertionError("tail.next must be null");
    }

    private static void expect(List<String> actual, String... expected) {
        List<String> want = List.of(expected);
        if (!actual.equals(want)) throw new AssertionError("expected " + want + ", got " + actual);
    }

    private static void expectIndexError(Runnable action) {
        try { action.run(); }
        catch (IndexOutOfBoundsException expected) { return; }
        throw new AssertionError("expected IndexOutOfBoundsException");
    }

    public static void main(String[] args) {
        L05LinkedListLab list = new L05LinkedListLab();
        list.assertInvariant();
        list.reverse();
        List<String> emptyBefore = list.ids();
        int emptySizeBefore = list.size;
        try { list.removeAt(0); throw new AssertionError("empty deletion must fail"); }
        catch (IndexOutOfBoundsException expected) { }
        list.assertInvariant();
        expect(list.ids(), emptyBefore.toArray(String[]::new));
        if (list.size != emptySizeBefore) throw new AssertionError("empty deletion changed size");
        L05LinkedListLab singleton = new L05LinkedListLab();
        singleton.insertAt(0, "TEST-SINGLE");
        singleton.assertInvariant();
        singleton.reverse();
        singleton.assertInvariant();
        expect(singleton.ids(), "TEST-SINGLE");
        if (!"TEST-SINGLE".equals(singleton.removeAt(0))) throw new AssertionError("singleton deletion failed");
        singleton.assertInvariant();
        for (String id : List.of("B-101", "B-205", "B-309", "E-301", "E-304")) {
            list.insertAt(list.size(), id);
            list.assertInvariant();
        }
        expect(list.ids(), "B-101", "B-205", "B-309", "E-301", "E-304");
        list.insertAt(0, "TEST-HEAD");
        list.assertInvariant();
        list.insertAt(3, "TEST-MIDDLE");
        list.assertInvariant();
        expect(list.ids(), "TEST-HEAD", "B-101", "B-205", "TEST-MIDDLE", "B-309", "E-301", "E-304");
        if (!"TEST-HEAD".equals(list.removeAt(0))) throw new AssertionError("head deletion failed");
        list.assertInvariant();
        if (!"E-304".equals(list.removeAt(list.size() - 1))) throw new AssertionError("tail deletion failed");
        list.assertInvariant();
        List<String> beforeInvalid = list.ids();
        int sizeBeforeInvalid = list.size();
        expectIndexError(() -> list.insertAt(-1, "TEST-HEAD"));
        if (!list.ids().equals(beforeInvalid) || list.size() != sizeBeforeInvalid) throw new AssertionError("negative insert changed list");
        expectIndexError(() -> list.insertAt(list.size() + 1, "TEST-HEAD"));
        if (!list.ids().equals(beforeInvalid) || list.size() != sizeBeforeInvalid) throw new AssertionError("past-end insert changed list");
        expectIndexError(() -> list.removeAt(-1));
        if (!list.ids().equals(beforeInvalid) || list.size() != sizeBeforeInvalid) throw new AssertionError("negative remove changed list");
        expectIndexError(() -> list.removeAt(list.size()));
        if (!list.ids().equals(beforeInvalid) || list.size() != sizeBeforeInvalid) throw new AssertionError("past-end remove changed list");
        list.assertInvariant();
        list.reverse();
        list.assertInvariant();
        expect(list.ids(), "E-301", "B-309", "TEST-MIDDLE", "B-205", "B-101");
        list.reverse();
        list.assertInvariant();
        expect(list.ids(), "B-101", "B-205", "TEST-MIDDLE", "B-309", "E-301");
        list.assertInvariant();
        System.out.println("L05 PASS: insert/remove/reverse and size/link invariants");
    }
}
