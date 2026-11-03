"""Stand-in for Triton, so that Meta's SAM 3 code can be imported on Windows, where Triton has no build.

Meta imports triton at load time for the video tracker's distance transform and for a few GPU fallbacks. Counting items in a
still photo never calls them. This module only makes the import succeed: calling or launching any Triton kernel raises
TritonUnavailable instead of pretending to work. tools/sam/count.py puts this folder on the path only when the real triton is missing.
"""


class TritonUnavailable(RuntimeError):
    pass


class _Kernel:
    def __init__(self, fn):
        self.fn = fn
        self.__name__ = getattr(fn, "__name__", "kernel")

    def __getitem__(self, grid):
        raise TritonUnavailable(f"Triton kernel '{self.__name__}' is not available on this machine; this code path needs a Triton build.")

    def __call__(self, *args, **kwargs):
        raise TritonUnavailable(f"Triton kernel '{self.__name__}' is not available on this machine; this code path needs a Triton build.")


def jit(fn=None, **options):
    if fn is None:
        return _Kernel
    return _Kernel(fn)


def cdiv(a, b):
    return -(-a // b)


def __getattr__(name):
    raise AttributeError(f"the triton stand-in has no '{name}'")
