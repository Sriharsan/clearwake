"""Stand-in for triton.language: names exist so that annotations such as `tl.constexpr` can be read. Nothing here runs a kernel."""


class constexpr:
    pass


def __getattr__(name):
    return constexpr
