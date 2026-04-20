"""v7.18 patch — stream backlog auto-prune at dispatcher startup.

Called from event_dispatcher.main() before init_stream_consumer_groups().
XTRIMs each stream:<agent> + stream:<agent>-worker / -agent stream variants
to drop messages older than MAX_AGE_HOURS (default 6h). Prevents stale
[RECOVER] envelopes from prior dispatcher restarts being replayed forever.

Uses XTRIM MINID to keep only entries with timestamp ID >= cutoff.
Redis stream IDs are `<ms-timestamp>-<seq>`, so the cutoff is just a ms epoch.
"""
import time


def prune_stale_streams(redis_client, max_age_hours: float = 6.0) -> dict:
    """XTRIM all stream:<agent> keys to drop entries older than max_age_hours.

    Returns dict of {stream_name: (before_len, after_len, dropped)}.
    """
    cutoff_ms = int((time.time() - max_age_hours * 3600) * 1000)
    minid = f"{cutoff_ms}-0"
    results = {}

    try:
        # SCAN for all stream:* keys
        cursor = 0
        stream_keys = []
        while True:
            cursor, batch = redis_client.scan(cursor=cursor, match="stream:*", count=100)
            stream_keys.extend(batch)
            if cursor == 0:
                break

        for key in stream_keys:
            key_str = key.decode() if isinstance(key, bytes) else key
            try:
                if redis_client.type(key).decode() != "stream":
                    continue
            except Exception:
                continue
            try:
                before = redis_client.xlen(key)
                if before == 0:
                    continue
                # XTRIM with MINID drops everything before the cutoff
                redis_client.xtrim(key, minid=minid, approximate=True)
                after = redis_client.xlen(key)
                dropped = before - after
                if dropped > 0:
                    results[key_str] = (before, after, dropped)
                    print(f"[stream-prune] {key_str}: {before} → {after} (dropped {dropped} stale)")
            except Exception as e:
                print(f"[stream-prune] {key_str} failed: {e}")
                continue
    except Exception as e:
        print(f"[stream-prune] scan failed: {e}")
        return {}

    if results:
        total_dropped = sum(v[2] for v in results.values())
        print(f"[stream-prune] complete — pruned {total_dropped} entries across {len(results)} streams")
    else:
        print("[stream-prune] no stale entries found (all streams within last 6h)")
    return results
