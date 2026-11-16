"""Lock-screen geometry per device, as fractions of the wallpaper.

Clock numeral box measured from an iOS lock screen at the default
(un-stretched) clock size; the same proportions hold across the
Dynamic Island iPhones at 19.5:9.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Device:
    name: str
    width: int
    height: int
    date_top: float = 0.110     # top of the date line above the clock
    clock_top: float = 0.153    # top of the time numerals
    clock_bottom: float = 0.238  # baseline of the time numerals
    clock_x0: float = 0.258
    clock_x1: float = 0.745

    @property
    def clock_h(self) -> float:
        return self.clock_bottom - self.clock_top


DEVICES = {
    "iphone_17_pro_max": Device("iPhone 16/17 Pro Max", 1320, 2868),
    "iphone_17_pro": Device("iPhone 16/17 Pro", 1206, 2622),
    "iphone_17": Device("iPhone 15/16/17", 1179, 2556),
}
