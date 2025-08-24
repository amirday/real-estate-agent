from typing import Iterable, List, Optional


def safe_float(x, default=None):
    if x is None or x == "":
        return default
    return float(x)


def median(values: List[float]) -> Optional[float]:
    arr = sorted(v for v in values if v is not None)
    n = len(arr)
    if n == 0:
        return None
    mid = n // 2
    if n % 2 == 1:
        return arr[mid]
    return (arr[mid - 1] + arr[mid]) / 2.0


def iqr(values: List[float]) -> Optional[float]:
    arr = sorted(v for v in values if v is not None)
    n = len(arr)
    if n < 4:
        return 0.0
    def percentile(p):
        k = (n - 1) * p
        f = int(k)
        c = min(f + 1, n - 1)
        if f == c:
            return arr[f]
        d0 = arr[f] * (c - k)
        d1 = arr[c] * (k - f)
        return d0 + d1
    q1 = percentile(0.25)
    q3 = percentile(0.75)
    return max(0.0, q3 - q1)


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))

