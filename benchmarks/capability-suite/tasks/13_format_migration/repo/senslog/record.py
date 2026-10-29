"""The in-memory record type shared by every format version."""
from dataclasses import dataclass

INT64_MIN = -(2 ** 63)
INT64_MAX = 2 ** 63 - 1


@dataclass(frozen=True)
class Record:
    """One sensor reading.

    sensor     -- sensor id, 0..65535
    timestamp  -- seconds since the Unix epoch (int)
    value      -- int (must fit in a signed 64-bit integer) or float
    label      -- free-text label, may be empty
    calibrated -- whether the reading came from a calibrated channel
    """

    sensor: int
    timestamp: int
    value: int | float
    label: str = ""
    calibrated: bool = False

    def __post_init__(self):
        if not isinstance(self.sensor, int) or isinstance(self.sensor, bool):
            raise TypeError("sensor must be an int")
        if not 0 <= self.sensor <= 0xFFFF:
            raise ValueError(f"sensor id out of range: {self.sensor}")
        if not isinstance(self.timestamp, int) or isinstance(self.timestamp, bool):
            raise TypeError("timestamp must be an int")
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
            raise TypeError("value must be an int or a float")
        if isinstance(self.value, int) and not INT64_MIN <= self.value <= INT64_MAX:
            raise ValueError(f"integer value does not fit in 64 bits: {self.value}")
        if not isinstance(self.label, str):
            raise TypeError("label must be a str")
        if not isinstance(self.calibrated, bool):
            raise TypeError("calibrated must be a bool")

    @property
    def is_float(self):
        return isinstance(self.value, float)

    def replace(self, **changes):
        """Return a copy with some fields changed."""
        fields = {
            "sensor": self.sensor,
            "timestamp": self.timestamp,
            "value": self.value,
            "label": self.label,
            "calibrated": self.calibrated,
        }
        fields.update(changes)
        return Record(**fields)
