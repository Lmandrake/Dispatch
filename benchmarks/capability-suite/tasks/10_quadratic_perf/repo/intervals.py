"""Booking conflict detection."""


def find_overlaps(intervals):
    """Return every pair of bookings that overlap.

    ``intervals`` is a list of ``(booking_id, start, end)`` with ``start < end``
    (numbers). Intervals are half-open ``[start, end)``: one ending exactly when
    another starts does NOT overlap. Booking ids are unique and mutually comparable.

    Returns a list of ``(id_a, id_b)`` tuples with ``id_a < id_b``, sorted
    ascending, each overlapping pair exactly once.
    """
    out = []
    for i in range(len(intervals)):
        a_id, a_s, a_e = intervals[i]
        for j in range(i + 1, len(intervals)):
            b_id, b_s, b_e = intervals[j]
            if a_s < b_e and b_s < a_e:
                out.append((a_id, b_id) if a_id < b_id else (b_id, a_id))
    return sorted(out)
