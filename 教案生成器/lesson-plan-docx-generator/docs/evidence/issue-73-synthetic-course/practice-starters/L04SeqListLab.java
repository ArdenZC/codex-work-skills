import java.util.ArrayList;
import java.util.List;

/** Student starter for L04. Fixed capacity: invalid indexes throw; a full insert returns false. */
public final class L04SeqListLab {
    private final String[] data = new String[5];
    private int size;

    public int size() { return size; }

    public boolean insert(int index, String id) {
        // TODO: require 0 <= index <= size; return false when full; shift right and increment size.
        throw new UnsupportedOperationException("complete insert");
    }

    public int find(String id) {
        // TODO: scan only [0, size); return the first matching index or -1.
        throw new UnsupportedOperationException("complete find");
    }

    public List<String> items() {
        List<String> result = new ArrayList<>();
        for (int i = 0; i < size; i++) result.add(data[i]);
        return result;
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
        L04SeqListLab list = new L04SeqListLab();
        expect(list.items());
        if (list.find("B-101") != -1) throw new AssertionError("empty find must miss");
        for (String id : List.of("B-101", "B-205", "B-309", "E-301")) {
            if (!list.insert(list.size(), id)) throw new AssertionError("insert into available capacity");
        }
        if (list.find("B-309") != 2 || list.find("E-304") != -1) throw new AssertionError("find result");
        if (!list.insert(2, "E-304")) throw new AssertionError("middle insert");
        expect(list.items(), "B-101", "B-205", "E-304", "B-309", "E-301");
        List<String> fullBefore = list.items();
        int fullSizeBefore = list.size();
        if (list.insert(5, "B-999")) throw new AssertionError("full insert must return false");
        if (!list.items().equals(fullBefore) || list.size() != fullSizeBefore) {
            throw new AssertionError("rejected full insert must leave items and size unchanged");
        }
        expectIndexError(() -> list.insert(-1, "B-999"));
        if (!list.items().equals(fullBefore) || list.size() != fullSizeBefore) {
            throw new AssertionError("negative-index rejection must leave items and size unchanged");
        }
        expectIndexError(() -> list.insert(6, "B-999"));
        if (!list.items().equals(fullBefore) || list.size() != fullSizeBefore) {
            throw new AssertionError("past-end rejection must leave items and size unchanged");
        }
        System.out.println("L04 PASS: insert/find, fixed capacity, and index boundaries");
    }
}
