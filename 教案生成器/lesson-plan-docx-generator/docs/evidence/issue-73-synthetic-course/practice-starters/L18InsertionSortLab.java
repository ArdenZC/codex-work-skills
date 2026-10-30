import java.util.Arrays;
import java.util.List;

/** Student starter for L18. Count key comparisons and right shifts separately. */
public final class L18InsertionSortLab {
    record Entry(String resourceId, String name, String status, int quantity) {}
    record Counts(int keyComparisons, int rightShifts) {}

    static Counts insertionSort(Entry[] a) {
        // TODO: save key, shift only strictly greater keys, and count each executed key comparison.
        throw new UnsupportedOperationException("complete insertionSort");
    }

    static void expectIds(Entry[] a, String... ids) {
        List<String> actual = Arrays.stream(a).map(Entry::resourceId).toList();
        if (!actual.equals(List.of(ids))) throw new AssertionError("expected " + List.of(ids) + ", got " + actual);
    }

    static Entry[] frozenInput() {
        return new Entry[] {
                new Entry("B-101", "算法入门", "在馆", 12),
                new Entry("B-205", "数据结构", "借出", 5),
                new Entry("B-309", "程序设计", "在馆", 12),
                new Entry("E-301", "示波器", "在用", 3),
                new Entry("E-304", "万用表", "在馆", 5)
        };
    }

    public static void main(String[] args) {
        Entry[] a = frozenInput();
        Counts counts = insertionSort(a);
        expectIds(a, "E-301", "B-205", "E-304", "B-101", "B-309");
        if (!a[1].resourceId().equals("B-205") || !a[2].resourceId().equals("E-304")) {
            throw new AssertionError("quantity-5 records must retain input order");
        }
        if (!a[3].resourceId().equals("B-101") || !a[4].resourceId().equals("B-309")) {
            throw new AssertionError("quantity-12 records must retain input order");
        }
        if (counts.keyComparisons() != 8 || counts.rightShifts() != 6) {
            throw new AssertionError("expected 8 key comparisons and 6 right shifts, got " + counts);
        }
        Entry[] empty = new Entry[0];
        Counts emptyCounts = insertionSort(empty);
        if (emptyCounts.keyComparisons() != 0 || emptyCounts.rightShifts() != 0) throw new AssertionError("empty case");
        Entry[] singleton = {new Entry("TEST-SINGLE", "测试", "测试", 1)};
        Counts singletonCounts = insertionSort(singleton);
        if (singletonCounts.keyComparisons() != 0 || singletonCounts.rightShifts() != 0) throw new AssertionError("singleton case");
        Entry[] alreadySorted = {
                new Entry("E-301", "示波器", "在用", 3), new Entry("B-205", "数据结构", "借出", 5),
                new Entry("E-304", "万用表", "在馆", 5), new Entry("B-101", "算法入门", "在馆", 12),
                new Entry("B-309", "程序设计", "在馆", 12)};
        Counts sortedCounts = insertionSort(alreadySorted);
        if (sortedCounts.keyComparisons() != 4 || sortedCounts.rightShifts() != 0) throw new AssertionError("sorted case");
        System.out.println("L18 PASS: stable output, 8/6 primary counts, empty/single/sorted boundaries");
    }
}
