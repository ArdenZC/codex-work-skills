import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Deque;
import java.util.List;

/** Student starter for L06. The queue array length is 6 and usable capacity is 5. */
public final class L06StackQueueLab {
    public static int bracketErrorIndex(String text) {
        // TODO: scan Java String indices from 0; skip non-bracket chars; return -1 on success.
        // On a bad closing bracket return its index; on leftover openings return the top index.
        throw new UnsupportedOperationException("complete bracketErrorIndex");
    }

    public static final class RingQueue {
        private final String[] data = new String[6];
        private int front;
        private int rear;
        private int size;

        public int front() { return front; }
        public int rear() { return rear; }
        public int size() { return size; }
        public boolean isEmpty() { return front == rear; }
        public boolean isFull() { return (rear + 1) % data.length == front; }

        public boolean offer(String id) {
            // TODO: when full return false without changing state; otherwise enqueue at rear.
            throw new UnsupportedOperationException("complete offer");
        }

        public String poll() {
            // TODO: when empty return null without changing state; otherwise dequeue at front.
            throw new UnsupportedOperationException("complete poll");
        }

        public List<String> logicalItems() {
            List<String> result = new ArrayList<>();
            for (int i = 0; i < size; i++) result.add(data[(front + i) % data.length]);
            return result;
        }

        public String[] physicalSnapshot() { return data.clone(); }
    }

    private static void check(boolean ok, String message) {
        if (!ok) throw new AssertionError(message);
    }

    public static void main(String[] args) {
        check(bracketErrorIndex("([{}])") == -1, "valid nested brackets");
        check(bracketErrorIndex("([)]") == 2, "mismatched closing bracket at index 2");
        check(bracketErrorIndex("a+)") == 2, "early closing bracket at index 2");
        check(bracketErrorIndex("((a)") == 0, "leftover opening bracket at index 0");

        RingQueue q = new RingQueue();
        String[] emptyBefore = q.physicalSnapshot();
        check(q.poll() == null && q.front() == 0 && q.rear() == 0 && q.size() == 0
                && q.logicalItems().isEmpty() && Arrays.equals(q.physicalSnapshot(), emptyBefore),
                "empty poll leaves physical and logical state unchanged");
        for (String id : List.of("B-101", "B-205", "B-309", "E-301", "E-304")) check(q.offer(id), "offer " + id);
        String[] fullSnapshot = q.physicalSnapshot();
        List<String> fullBefore = q.logicalItems();
        int frontBefore = q.front(), rearBefore = q.rear(), sizeBefore = q.size();
        check(!q.offer("B-101"), "full offer is rejected");
        check(q.logicalItems().equals(fullBefore) && q.front() == frontBefore
                && q.rear() == rearBefore && q.size() == sizeBefore,
                "full offer leaves all logical and pointer state unchanged");
        check(Arrays.equals(q.physicalSnapshot(), fullSnapshot), "full offer leaves every physical slot unchanged");
        check(q.poll().equals("B-101") && q.poll().equals("B-205") && q.poll().equals("B-309"), "FIFO dequeue");
        check(q.physicalSnapshot()[0] == null && q.physicalSnapshot()[1] == null
                && q.physicalSnapshot()[2] == null, "poll clears each vacated slot");
        check(q.offer("B-101") && q.offer("B-205"), "two new requests wrap rear to slot 1");
        check(q.logicalItems().equals(List.of("E-301", "E-304", "B-101", "B-205")), "wrapped FIFO order");
        check(q.front() == 3 && q.rear() == 1 && q.size() == 4, "wrapped pointers");
        System.out.println("L06 PASS: bracket indices and circular queue boundary/wrap checks");
    }
}
