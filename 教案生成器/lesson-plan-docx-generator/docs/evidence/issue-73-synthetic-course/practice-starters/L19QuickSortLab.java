import java.util.Arrays;
import java.util.List;

/** Student starter for L19. Partition is Lomuto with the final item as pivot and strict <. */
public final class L19QuickSortLab {
    record Entry(String resourceId, String name, String status, int quantity) {}
    private int keyComparisons;

    public int sort(Entry[] a) {
        keyComparisons = 0;
        quickSort(a, 0, a.length - 1);
        return keyComparisons;
    }

    private void quickSort(Entry[] a, int low, int high) {
        if (low >= high) return;
        int p = partition(a, low, high);
        quickSort(a, low, p - 1);
        quickSort(a, p + 1, high);
    }

    private int partition(Entry[] a, int low, int high) {
        // TODO: pivot=a[high]; scan j in [low, high); count each key comparison; move only quantity < pivot.
        throw new UnsupportedOperationException("complete partition");
    }

    static Entry[] originalOrder() {
        return new Entry[] {
                new Entry("B-101", "算法入门", "在馆", 12),
                new Entry("B-205", "数据结构", "借出", 5),
                new Entry("B-309", "程序设计", "在馆", 12),
                new Entry("E-301", "示波器", "在用", 3),
                new Entry("E-304", "万用表", "在馆", 5)
        };
    }

    static Entry[] insertionSortedOrder() {
        return new Entry[] {
                new Entry("E-301", "示波器", "在用", 3),
                new Entry("B-205", "数据结构", "借出", 5),
                new Entry("E-304", "万用表", "在馆", 5),
                new Entry("B-101", "算法入门", "在馆", 12),
                new Entry("B-309", "程序设计", "在馆", 12)
        };
    }

    static void expectIds(Entry[] a) {
        List<String> actual = Arrays.stream(a).map(Entry::resourceId).toList();
        List<String> expected = List.of("E-301", "E-304", "B-205", "B-309", "B-101");
        if (!actual.equals(expected)) throw new AssertionError("expected " + expected + ", got " + actual);
    }

    public static void main(String[] args) {
        L19QuickSortLab sorter = new L19QuickSortLab();
        Entry[] original = originalOrder();
        if (sorter.sort(original) != 7) throw new AssertionError("original-order comparisons must be 7");
        expectIds(original);
        Entry[] insertionSorted = insertionSortedOrder();
        if (sorter.sort(insertionSorted) != 6) throw new AssertionError("L18-order comparisons must be 6");
        expectIds(insertionSorted);
        if (sorter.sort(new Entry[0]) != 0) throw new AssertionError("empty input");
        if (sorter.sort(new Entry[] {new Entry("TEST-SINGLE", "测试", "测试", 1)}) != 0) {
            throw new AssertionError("single-item input");
        }
        Entry[] equalKeys = new Entry[5];
        for (int i = 0; i < equalKeys.length; i++) equalKeys[i] = new Entry("TEST-" + i, "测试", "测试", 7);
        if (sorter.sort(equalKeys) != 10) throw new AssertionError("all-equal input must show quadratic comparisons");
        if (!equalKeys[0].resourceId().equals("TEST-4") || !equalKeys[1].resourceId().equals("TEST-0")) {
            throw new AssertionError("strict Lomuto swaps show quicksort is not stable");
        }
        System.out.println("L19 PASS: 7/6 main counts, empty/single boundaries, equal-key worst case");
    }
}
