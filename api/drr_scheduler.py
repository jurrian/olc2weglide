import asyncio
import logging
import time
from collections import defaultdict, deque


class EWMA:
    def __init__(self, alpha=0.2):
        self.alpha = alpha; self.value = None
    def update(self, x):
        self.value = x if self.value is None else self.alpha*x + (1-self.alpha)*self.value
        return self.value

class RollingQuantile:
    def __init__(self, maxlen=500):
        self.samples = deque(maxlen=maxlen)
    def update(self, x):
        self.samples.append(x)
    def quantile(self, q):
        if not self.samples: return None
        s = sorted(self.samples)
        idx = min(len(s)-1, max(0, int(q*(len(s)-1))))
        return s[idx]

class AdaptiveCap:
    def __init__(self, floor=4, ceiling=64):
        self.cap = floor; self.floor=floor; self.ceiling=ceiling
        self.win = deque(maxlen=200)
    def record(self, ok: bool):
        self.win.append(ok)
        if len(self.win) < 20: return
        err = 1 - (sum(self.win)/len(self.win))
        if err > 0.05:
            self.cap = max(self.floor, max(self.floor, int(self.cap*0.7)))
        else:
            self.cap = min(self.ceiling, self.cap+1)

class DRRScheduler:
    def __init__(self, adaptive: AdaptiveCap):
        self.q = defaultdict(deque)       # user_id -> deque of items
        self.weights = defaultdict(lambda: 1)
        self.deficit = defaultdict(int)
        self.quantum = 1                  # 1 request per turn
        self.active_users = deque()
        self.inflight = 0
        self.adaptive = adaptive
        # service metrics
        self.s_mean = EWMA(alpha=0.2)
        self.qstats = RollingQuantile()
        self.lock = asyncio.Lock()

    def enqueue_batch(self, user_id, items, weight=1):
        self.weights[user_id] = weight
        was_empty = not self.q[user_id]
        for it in items:
            self.q[user_id].append(it)
        if was_empty and self.q[user_id]:
            self.active_users.append(user_id)

    def enqueue_one(self, user_id, coro, weight=1):
        loop = asyncio.get_event_loop()
        future = loop.create_future()

        async def wrapper():
            try:
                result = await coro
                future.set_result(result)
            except Exception as e:
                future.set_exception(e)

        self.weights[user_id] = weight
        was_empty = not self.q[user_id]
        self.q[user_id].append(wrapper())
        if was_empty and self.q[user_id]:
            self.active_users.append(user_id)
        return future

    async def _pop_next(self):
        # DRR round-robin over active users
        if not self.active_users: return None, None
        for _ in range(len(self.active_users)):
            uid = self.active_users[0]
            if not self.q[uid]:
                self.active_users.popleft()
                continue
            self.deficit[uid] += self.quantum * self.weights[uid]
            if self.deficit[uid] <= 0:
                self.active_users.rotate(-1)
                continue
            item = self.q[uid].popleft()
            self.deficit[uid] -= 1
            # keep uid active if more items remain
            if self.q[uid]:
                self.active_users.rotate(-1)
            else:
                self.active_users.popleft()
            return uid, item
        return None, None

    async def run(self):
        # one background task; schedule up to adaptive.cap inflight
        while True:
            async with self.lock:
                can_launch = max(0, self.adaptive.cap - self.inflight)
            if can_launch <= 0:
                await asyncio.sleep(0.01); continue
            uid, item = await self._pop_next()
            if uid is None:
                await asyncio.sleep(0.01); continue
            async with self.lock:
                self.inflight += 1
            started = time.perf_counter()
            ok = True
            try:
                await item
            except Exception as e:
                ok = False
                logging.error(f"Error in drr scheduled task for user {uid}: {e}")
            finally:
                dt = time.perf_counter() - started
                self.s_mean.update(dt)
                self.qstats.update(dt)
                self.adaptive.record(ok)
                async with self.lock:
                    self.inflight -= 1

    # ---- metrics for UI ----
    def global_load(self):
        return self.inflight, self.adaptive.cap
    def active_user_count(self):
        return sum(1 for u in self.q if self.q[u]) + (1 if self.inflight else 0)
    def service_times(self):
        return self.s_mean.value, self.qstats.quantile(0.5), self.qstats.quantile(0.9)

    def user_effective_rate(self, user_id):
        # approximate: share = weight / sum(weights of active users)
        active = [u for u in self.q if self.q[u]]
        if not active: return (self.adaptive.cap, 1.0)
        sumw = sum(self.weights[u] for u in active)
        share = self.weights[user_id]/sumw if sumw else 1.0
        return (self.adaptive.cap * share, share)

    def eta_seconds(self, user_id, N):
        s_mean, s50, s90 = self.service_times()
        s_mean = s_mean or 1.0
        s50 = s50 or s_mean
        s90 = s90 or s_mean*1.5
        r_user, _ = self.user_effective_rate(user_id)  # requests/sec
        r_user = max(0.001, r_user)
        eta50 = N / r_user * (s50 / s_mean)
        eta90 = N / r_user * (s90 / s_mean)
        # plus wait-to-start if there is work ahead of you
        work_ahead = sum(len(self.q[u]) for u in self.q if u != user_id)
        global_rate = max(0.001, self.adaptive.cap)   # items per service-time unit
        wait_start = work_ahead / global_rate * (s50)  # crude but robust
        return (wait_start + eta50, wait_start + eta90)


drr_scheduler = DRRScheduler(AdaptiveCap(floor=4, ceiling=32))
