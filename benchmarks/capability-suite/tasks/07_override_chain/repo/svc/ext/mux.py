"""mux helpers."""


def mux_step(data, factor=3):
    return [x * factor for x in data]
