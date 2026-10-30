import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.List;
import java.util.Queue;

/** Student starter for L11. Input IDs are unique and every non-root ID has one parent. */
public final class L11TreeTraversalLab {
    static final class Node {
        final String id;
        Node left;
        Node right;
        Node(String id) { this.id = id; }
    }

    static List<String> preorder(Node root) {
        // TODO: null base case; emit root before left and right.
        throw new UnsupportedOperationException("complete preorder");
    }

    static List<String> inorder(Node root) {
        // TODO: null base case; emit root between left and right.
        throw new UnsupportedOperationException("complete inorder");
    }

    static List<String> postorder(Node root) {
        // TODO: null base case; emit root after left and right.
        throw new UnsupportedOperationException("complete postorder");
    }

    static List<String> levelOrder(Node root) {
        // TODO: use ArrayDeque; enqueue only non-null children, left before right.
        throw new UnsupportedOperationException("complete levelOrder");
    }

    static Node sampleTree() {
        // TODO: create G,C,M,A,E,J,P and link G-(C,M), C-(A,E), M-(J,P).
        // Return G so the traversal assertions also validate the constructed tree.
        throw new UnsupportedOperationException("construct the G tree");
    }

    static void expect(List<String> actual, String... expected) {
        List<String> want = List.of(expected);
        if (!actual.equals(want)) throw new AssertionError("expected " + want + ", got " + actual);
    }

    public static void main(String[] args) {
        Node g = sampleTree();
        expect(preorder(null)); expect(inorder(null)); expect(postorder(null)); expect(levelOrder(null));
        Node q = new Node("Q");
        expect(preorder(q), "Q"); expect(inorder(q), "Q"); expect(postorder(q), "Q"); expect(levelOrder(q), "Q");
        Node rightChain = new Node("T"); rightChain.right = new Node("R");
        expect(preorder(rightChain), "T", "R");
        expect(inorder(rightChain), "T", "R");
        expect(postorder(rightChain), "R", "T");
        expect(levelOrder(rightChain), "T", "R");
        Node leftChain = new Node("T"); leftChain.left = new Node("L");
        expect(preorder(leftChain), "T", "L");
        expect(inorder(leftChain), "L", "T");
        expect(postorder(leftChain), "L", "T");
        expect(levelOrder(leftChain), "T", "L");
        expect(preorder(g), "G", "C", "A", "E", "M", "J", "P");
        expect(inorder(g), "A", "C", "E", "G", "J", "M", "P");
        expect(postorder(g), "A", "E", "C", "J", "P", "M", "G");
        expect(levelOrder(g), "G", "C", "M", "A", "E", "J", "P");
        System.out.println("L11 PASS: empty/singleton/left/right/G traversal assertions");
    }
}
