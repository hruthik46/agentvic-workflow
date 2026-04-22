"""v7.18 — Stream backlog pruner for Karios dispatcher.

Removes stale entries from all Redis streams on startup to prevent
stale message re-processing after crashes or long downtime.
"""
import time


def prune_stale_streams(r, max_age_hours: float = 6.0) -> dict:
    """XTRIM all stream:* keys, removing entries older than max_age_hours.

    Returns dict of {stream_key: entries_removed}.
    """
    cutoff_ms = int((time.time() - max_age_hours * 3600) * 1000)
    cutoff_id = f"{cutoff_ms}-0"

    results = {}
    try:
        stream_keys = r.keys("stream:*")
    except Exception as e:
        print(f"[stream_prune] Failed to list streams: {e}")
        return results

    for key in stream_keys:
        try:
            before = r.xlen(key)
            if before == 0:
                continue
            # XTRIM by min-id: keep only entries NEWER than cutoff
            r.xtrim(key, minid=cutoff_id)
            after = r.xlen(key)
            removed = before - after
            if removed > 0:
                results[key] = removed
                print(f"[stream_prune] {key}: pruned {removed} stale entries (>{max_age_hours:.0f}h old)")
        except Exception as e:
            print(f"[stream_prune] Failed to prune {key}: {e}")

    if not results:
        print(f"[stream_prune] No stale entries found across {len(stream_keys)} streams")
    return results
