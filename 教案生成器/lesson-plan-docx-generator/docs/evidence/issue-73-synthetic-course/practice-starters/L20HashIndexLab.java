import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/** Student starter for L20. Duplicate keys are rejected without replacing the existing record. */
public final class L20HashIndexLab {
    record Entry(String resourceId, String name, String status, int quantity) {}
    record Lookup(Entry entry, List<Integer> slotsVisited) {}

    private final Entry[] table = new Entry[7];

    static int hash(String key) {
        int sum = 0;
        for (char c : key.toCharArray()) sum += c;
        return sum % 7;
    }

    public boolean insert(Entry entry) {
        // TODO: bounded linear probe; place at first empty slot; reject same resourceId without mutation.
        throw new UnsupportedOperationException("complete insert");
    }

    public Lookup lookup(String resourceId) {
        // TODO: visit at most 7 slots; stop at an empty slot; compare the full key.
        throw new UnsupportedOperationException("complete lookup");
    }

    static List<Integer> slots(Lookup lookup) { return lookup.slotsVisited(); }

    public static void main(String[] args) {
        List<Entry> frozen = List.of(
                new Entry("B-101", "算法入门", "在馆", 12),
                new Entry("B-205", "数据结构", "借出", 5),
                new Entry("B-309", "程序设计", "在馆", 12),
                new Entry("E-301", "示波器", "在用", 3),
                new Entry("E-304", "万用表", "在馆", 5));
        L20HashIndexLab index = new L20HashIndexLab();
        for (Entry entry : frozen) if (!index.insert(entry)) throw new AssertionError("unexpected insertion failure");
        if (hash("B-205") != 3 || hash("E-301") != 3) throw new AssertionError("collision input hash");
        if (index.table[3] != frozen.get(1) || index.table[4] != frozen.get(3)) throw new AssertionError("collision slots");
        if (index.insert(new Entry("B-205", "替代记录", "未知", -1))) throw new AssertionError("duplicate key must be rejected");
        if (!index.table[3].equals(frozen.get(1))) throw new AssertionError("duplicate must preserve original entry");
        Lookup hit = index.lookup("E-301");
        if (!frozen.get(3).equals(hit.entry()) || !slots(hit).equals(List.of(3, 4))) throw new AssertionError("E-301 probe path");
        Lookup miss = index.lookup("NO-SUCH-ID");
        if (miss.entry() != null || miss.slotsVisited().size() > 7) throw new AssertionError("bounded missing lookup");
        Lookup collisionChainMiss = index.lookup("C-204");
        if (hash("C-204") != 3 || collisionChainMiss.entry() != null
                || !slots(collisionChainMiss).equals(List.of(3, 4, 5, 6, 0))) {
            throw new AssertionError("miss must follow the occupied cluster before stopping at slot 0");
        }
        L20HashIndexLab full = new L20HashIndexLab();
        for (int i = 0; i < 7; i++) {
            if (!full.insert(new Entry("TEST-" + i, "测试", "测试", i))) throw new AssertionError("fill test table");
        }
        Entry[] fullBeforeOverflow = full.table.clone();
        if (full.insert(new Entry("TEST-OVERFLOW", "测试", "测试", 8))) throw new AssertionError("full table rejects insert");
        if (!Arrays.equals(full.table, fullBeforeOverflow)) throw new AssertionError("full table rejection must preserve all slots");
        Lookup fullMiss = full.lookup("TEST-MISSING");
        if (fullMiss.entry() != null || fullMiss.slotsVisited().size() != 7) throw new AssertionError("full miss stops after seven slots");
        System.out.println("L20 PASS: collision/miss chain, duplicate rejection, full table and bounded probe");
    }
}
