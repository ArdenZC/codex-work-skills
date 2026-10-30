import java.util.ArrayList;
import java.util.List;

/** Student starter for L12. Duplicate keys are rejected and do not change size. */
public final class L12BSTLab {
    enum InsertResult { INSERTED, DUPLICATE }
    enum DeleteResult { DELETED, NOT_FOUND }

    private static final class Node {
        final int key;
        Node left, right;
        Node(int key) { this.key = key; }
    }

    private Node root;
    private int size;
    public int size() { return size; }

    public boolean find(int key) {
        // TODO: follow the BST ordering rule; stop at matching key or null.
        throw new UnsupportedOperationException("complete find");
    }

    public InsertResult insert(int key) {
        // TODO: insert once; return DUPLICATE without changing size when the key exists.
        throw new UnsupportedOperationException("complete insert");
    }

    public DeleteResult delete(int key) {
        // TODO: cover leaf, one-child, two-child (right-subtree minimum successor), and missing key.
        throw new UnsupportedOperationException("complete delete");
    }

    public List<Integer> inorder() {
        List<Integer> out = new ArrayList<>();
        collect(root, out);
        return out;
    }

    private static void collect(Node node, List<Integer> out) {
        if (node == null) return;
        collect(node.left, out); out.add(node.key); collect(node.right, out);
    }

    private static void expect(List<Integer> actual, Integer... expected) {
        List<Integer> want = List.of(expected);
        if (!actual.equals(want)) throw new AssertionError("expected " + want + ", got " + actual);
    }

    public static void main(String[] args) {
        L12BSTLab bst = new L12BSTLab();
        for (int key : new int[] {45, 25, 65, 15, 35, 55, 75, 30}) bst.insert(key);
        if (!bst.find(30) || bst.find(32)) throw new AssertionError("find path/absence check");
        if (bst.insert(35) != InsertResult.DUPLICATE || bst.size() != 8) throw new AssertionError("duplicate size check");
        if (bst.delete(15) != DeleteResult.DELETED || bst.size() != 7) {
            throw new AssertionError("leaf deletion must reduce size to 7");
        }
        expect(bst.inorder(), 25, 30, 35, 45, 55, 65, 75);
        if (bst.delete(25) != DeleteResult.DELETED || bst.size() != 6) {
            throw new AssertionError("one-child deletion must reduce size to 6");
        }
        expect(bst.inorder(), 30, 35, 45, 55, 65, 75);
        if (bst.delete(45) != DeleteResult.DELETED || bst.size() != 5) {
            throw new AssertionError("two-child deletion must reduce size to 5");
        }
        expect(bst.inorder(), 30, 35, 55, 65, 75);
        int before = bst.size();
        List<Integer> beforeMissingDelete = bst.inorder();
        if (bst.delete(99) != DeleteResult.NOT_FOUND || bst.size() != before
                || !bst.inorder().equals(beforeMissingDelete)) {
            throw new AssertionError("missing deletion must preserve size and tree structure");
        }

        L12BSTLab successorWithRightChild = new L12BSTLab();
        for (int key : new int[] {20, 10, 30, 25, 27, 40}) successorWithRightChild.insert(key);
        if (successorWithRightChild.delete(20) != DeleteResult.DELETED
                || successorWithRightChild.size() != 5) {
            throw new AssertionError("two-child deletion with a successor right child");
        }
        expect(successorWithRightChild.inorder(), 10, 25, 27, 30, 40);
        System.out.println("L12 PASS: search/insert/delete and size/inorder assertions");
    }
}
