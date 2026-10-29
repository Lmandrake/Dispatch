"""Sensor calibration routines.

GENERATED from the bench calibration sheet (rev 14). Each sensor has its own
routine because the vendor curves differ in small ways; keep them separate.
"""

LOW_LIMIT = 0.0
HIGH_LIMIT = 4095.0


def calibrate_s000(raw):
    """Convert a raw S000 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S000 reading out of range: %r" % (raw,))
    x = x - 14.48
    x = x * 0.0735
    x = x + -3.55
    return round(x, 3)


def calibrate_s001(raw):
    """Convert a raw S001 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S001 reading out of range: %r" % (raw,))
    x = x - 24.26
    x = x * 0.0758
    x = x + -3.557
    return round(x, 3)


def calibrate_s002(raw):
    """Convert a raw S002 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S002 reading out of range: %r" % (raw,))
    x = x - 28.56
    x = x * 0.0488
    x = x + -4.547
    return round(x, 4)


def calibrate_s003(raw):
    """Convert a raw S003 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S003 reading out of range: %r" % (raw,))
    x = x - 18.51
    x = x * 0.0309
    x = x + 3.996
    return round(x, 3)


def calibrate_s004(raw):
    """Convert a raw S004 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S004 reading out of range: %r" % (raw,))
    x = x - 28.05
    x = x * 0.01
    x = x + -3.73
    return round(x, 3)


def calibrate_s005(raw):
    """Convert a raw S005 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S005 reading out of range: %r" % (raw,))
    x = x - 6.44
    x = x * 0.063
    x = x + 1.312
    return round(x, 4)


def calibrate_s006(raw):
    """Convert a raw S006 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S006 reading out of range: %r" % (raw,))
    x = x - 36.31
    x = x * 0.0476
    x = x + 3.933
    return round(x, 4)


def calibrate_s007(raw):
    """Convert a raw S007 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S007 reading out of range: %r" % (raw,))
    x = x - 19.99
    x = x * 0.0201
    x = x + -4.797
    return round(x, 3)


def calibrate_s008(raw):
    """Convert a raw S008 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S008 reading out of range: %r" % (raw,))
    x = x - 32.73
    x = x * 0.0399
    x = x + -3.112
    return round(x, 4)


def calibrate_s009(raw):
    """Convert a raw S009 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S009 reading out of range: %r" % (raw,))
    x = x - 19.17
    x = x * 0.0716
    x = x + -0.605
    return round(x, 4)


def calibrate_s010(raw):
    """Convert a raw S010 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S010 reading out of range: %r" % (raw,))
    x = x - 19.1
    x = x * 0.0318
    x = x + 0.793
    return round(x, 4)


def calibrate_s011(raw):
    """Convert a raw S011 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S011 reading out of range: %r" % (raw,))
    x = x - 39.12
    x = x * 0.0742
    x = x + -2.139
    return round(x, 3)


def calibrate_s012(raw):
    """Convert a raw S012 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S012 reading out of range: %r" % (raw,))
    x = x - 3.35
    x = x * 0.0684
    x = x + 3.581
    return round(x, 4)


def calibrate_s013(raw):
    """Convert a raw S013 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S013 reading out of range: %r" % (raw,))
    x = x - 10.96
    x = x * 0.0431
    x = x + -0.269
    return round(x, 4)


def calibrate_s014(raw):
    """Convert a raw S014 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S014 reading out of range: %r" % (raw,))
    x = x - 36.89
    x = x * 0.0531
    x = x + -4.681
    return round(x, 3)


def calibrate_s015(raw):
    """Convert a raw S015 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S015 reading out of range: %r" % (raw,))
    x = x - 9.98
    x = x * 0.0646
    x = x + 1.047
    return round(x, 3)


def calibrate_s016(raw):
    """Convert a raw S016 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S016 reading out of range: %r" % (raw,))
    x = x - 21.42
    x = x * 0.0254
    x = x + -4.673
    return round(x, 3)


def calibrate_s017(raw):
    """Convert a raw S017 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S017 reading out of range: %r" % (raw,))
    x = x - 13.46
    x = x * 0.0543
    x = x + -4.68
    return round(x, 3)


def calibrate_s018(raw):
    """Convert a raw S018 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S018 reading out of range: %r" % (raw,))
    x = x - 28.03
    x = x * 0.0744
    x = x + -1.565
    return round(x, 3)


def calibrate_s019(raw):
    """Convert a raw S019 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S019 reading out of range: %r" % (raw,))
    x = x - 6.31
    x = x * 0.0312
    x = x + 1.758
    return round(x, 4)


def calibrate_s020(raw):
    """Convert a raw S020 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S020 reading out of range: %r" % (raw,))
    x = x - 21.89
    x = x * 0.0743
    x = x + -0.359
    return round(x, 4)


def calibrate_s021(raw):
    """Convert a raw S021 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S021 reading out of range: %r" % (raw,))
    x = x - 25.58
    x = x * 0.0649
    x = x + -3.719
    return round(x, 4)


def calibrate_s022(raw):
    """Convert a raw S022 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S022 reading out of range: %r" % (raw,))
    x = x - 20.81
    x = x * 0.0775
    x = x + -4.695
    return round(x, 3)


def calibrate_s023(raw):
    """Convert a raw S023 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S023 reading out of range: %r" % (raw,))
    x = x - 7.35
    x = x * 0.0368
    x = x + 2.39
    return round(x, 4)


def calibrate_s024(raw):
    """Convert a raw S024 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S024 reading out of range: %r" % (raw,))
    x = x - 31.87
    x = x * 0.0175
    x = x + 4.451
    return round(x, 3)


def calibrate_s025(raw):
    """Convert a raw S025 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S025 reading out of range: %r" % (raw,))
    x = x - 16.77
    x = x * 0.074
    x = x + -3.368
    return round(x, 4)


def calibrate_s026(raw):
    """Convert a raw S026 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S026 reading out of range: %r" % (raw,))
    x = x - 39.74
    x = x * 0.0744
    x = x + 0.61
    return round(x, 3)


def calibrate_s027(raw):
    """Convert a raw S027 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S027 reading out of range: %r" % (raw,))
    x = x - 31.46
    x = x * 0.0456
    x = x + 0.689
    return round(x, 3)


def calibrate_s028(raw):
    """Convert a raw S028 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S028 reading out of range: %r" % (raw,))
    x = x - 30.41
    x = x * 0.0175
    x = x + 3.549
    return round(x, 4)


def calibrate_s029(raw):
    """Convert a raw S029 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S029 reading out of range: %r" % (raw,))
    x = x - 0.39
    x = x * 0.0258
    x = x + 3.449
    return round(x, 3)


def calibrate_s030(raw):
    """Convert a raw S030 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S030 reading out of range: %r" % (raw,))
    x = x - 28.65
    x = x * 0.0608
    x = x + 1.451
    return round(x, 4)


def calibrate_s031(raw):
    """Convert a raw S031 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S031 reading out of range: %r" % (raw,))
    x = x - 10.88
    x = x * 0.0333
    x = x + -3.149
    return round(x, 3)


def calibrate_s032(raw):
    """Convert a raw S032 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S032 reading out of range: %r" % (raw,))
    x = x - 6.57
    x = x * 0.0861
    x = x + 1.255
    return round(x, 4)


def calibrate_s033(raw):
    """Convert a raw S033 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S033 reading out of range: %r" % (raw,))
    x = x - 2.97
    x = x * 0.0571
    x = x + -4.877
    return round(x, 4)


def calibrate_s034(raw):
    """Convert a raw S034 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S034 reading out of range: %r" % (raw,))
    x = x - 30.36
    x = x * 0.0261
    x = x + -3.854
    return round(x, 3)


def calibrate_s035(raw):
    """Convert a raw S035 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S035 reading out of range: %r" % (raw,))
    x = x - 26.95
    x = x * 0.0624
    x = x + 0.956
    return round(x, 3)


def calibrate_s036(raw):
    """Convert a raw S036 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S036 reading out of range: %r" % (raw,))
    x = x - 21.71
    x = x * 0.0388
    x = x + 2.864
    return round(x, 3)


def calibrate_s037(raw):
    """Convert a raw S037 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S037 reading out of range: %r" % (raw,))
    x = x - 30.55
    x = x * 0.0846
    x = x + 1.877
    return round(x, 4)


def calibrate_s038(raw):
    """Convert a raw S038 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S038 reading out of range: %r" % (raw,))
    x = x - 3.71
    x = x * 0.0828
    x = x + -4.227
    return round(x, 3)


def calibrate_s039(raw):
    """Convert a raw S039 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S039 reading out of range: %r" % (raw,))
    x = x - 6.74
    x = x * 0.0512
    x = x + 1.614
    return round(x, 3)


def calibrate_s040(raw):
    """Convert a raw S040 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S040 reading out of range: %r" % (raw,))
    x = x - 38.32
    x = x * 0.0616
    x = x + 2.02
    return round(x, 3)


def calibrate_s041(raw):
    """Convert a raw S041 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S041 reading out of range: %r" % (raw,))
    x = x - 2.0
    x = x * 0.0658
    x = x + 4.198
    return round(x, 4)


def calibrate_s042(raw):
    """Convert a raw S042 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S042 reading out of range: %r" % (raw,))
    x = x - 26.04
    x = x * 0.0744
    x = x + -2.13
    return round(x, 4)


def calibrate_s043(raw):
    """Convert a raw S043 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S043 reading out of range: %r" % (raw,))
    x = x - 9.28
    x = x * 0.0881
    x = x + 3.158
    return round(x, 3)


def calibrate_s044(raw):
    """Convert a raw S044 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S044 reading out of range: %r" % (raw,))
    x = x - 11.11
    x = x * 0.0123
    x = x + -4.869
    return round(x, 4)


def calibrate_s045(raw):
    """Convert a raw S045 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S045 reading out of range: %r" % (raw,))
    x = x - 31.08
    x = x * 0.0389
    x = x + -4.063
    return round(x, 3)


def calibrate_s046(raw):
    """Convert a raw S046 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S046 reading out of range: %r" % (raw,))
    x = x - 14.48
    x = x * 0.0581
    x = x + 1.913
    return round(x, 3)


def calibrate_s047(raw):
    """Convert a raw S047 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S047 reading out of range: %r" % (raw,))
    x = x - 37.94
    x = x * 0.0343
    x = x + -4.72
    return round(x, 4)


def calibrate_s048(raw):
    """Convert a raw S048 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S048 reading out of range: %r" % (raw,))
    x = x - 17.43
    x = x * 0.0571
    x = x + 3.325
    return round(x, 3)


def calibrate_s049(raw):
    """Convert a raw S049 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S049 reading out of range: %r" % (raw,))
    x = x - 13.76
    x = x * 0.0172
    x = x + -4.696
    return round(x, 4)


def calibrate_s050(raw):
    """Convert a raw S050 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S050 reading out of range: %r" % (raw,))
    x = x - 2.72
    x = x * 0.0804
    x = x + -4.974
    return round(x, 4)


def calibrate_s051(raw):
    """Convert a raw S051 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S051 reading out of range: %r" % (raw,))
    x = x - 3.5
    x = x * 0.052
    x = x + 0.907
    return round(x, 4)


def calibrate_s052(raw):
    """Convert a raw S052 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S052 reading out of range: %r" % (raw,))
    x = x - 9.21
    x = x * 0.0193
    x = x + -3.741
    return round(x, 3)


def calibrate_s053(raw):
    """Convert a raw S053 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S053 reading out of range: %r" % (raw,))
    x = x - 9.72
    x = x * 0.063
    x = x + 1.629
    return round(x, 4)


def calibrate_s054(raw):
    """Convert a raw S054 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S054 reading out of range: %r" % (raw,))
    x = x - 22.54
    x = x * 0.035
    x = x + 1.269
    return round(x, 4)


def calibrate_s055(raw):
    """Convert a raw S055 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S055 reading out of range: %r" % (raw,))
    x = x - 37.14
    x = x * 0.0257
    x = x + -2.468
    return round(x, 4)


def calibrate_s056(raw):
    """Convert a raw S056 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S056 reading out of range: %r" % (raw,))
    x = x - 35.52
    x = x * 0.0487
    x = x + -3.075
    return round(x, 4)


def calibrate_s057(raw):
    """Convert a raw S057 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S057 reading out of range: %r" % (raw,))
    x = x - 4.19
    x = x * 0.021
    x = x + -3.239
    return round(x, 3)


def calibrate_s058(raw):
    """Convert a raw S058 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S058 reading out of range: %r" % (raw,))
    x = x - 37.92
    x = x * 0.0268
    x = x + 3.095
    return round(x, 3)


def calibrate_s059(raw):
    """Convert a raw S059 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S059 reading out of range: %r" % (raw,))
    x = x - 4.8
    x = x * 0.0792
    x = x + 0.927
    return round(x, 4)


def calibrate_s060(raw):
    """Convert a raw S060 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S060 reading out of range: %r" % (raw,))
    x = x - 19.45
    x = x * 0.0659
    x = x + 3.696
    return round(x, 4)


def calibrate_s061(raw):
    """Convert a raw S061 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S061 reading out of range: %r" % (raw,))
    x = x - 8.62
    x = x * 0.011
    x = x + 1.442
    return round(x, 4)


def calibrate_s062(raw):
    """Convert a raw S062 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S062 reading out of range: %r" % (raw,))
    x = x - 6.17
    x = x * 0.0722
    x = x + 4.191
    return round(x, 3)


def calibrate_s063(raw):
    """Convert a raw S063 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S063 reading out of range: %r" % (raw,))
    x = x - 13.51
    x = x * 0.0114
    x = x + -2.482
    return round(x, 3)


def calibrate_s064(raw):
    """Convert a raw S064 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S064 reading out of range: %r" % (raw,))
    x = x - 11.43
    x = x * 0.0366
    x = x + 0.884
    return round(x, 4)


def calibrate_s065(raw):
    """Convert a raw S065 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S065 reading out of range: %r" % (raw,))
    x = x - 8.93
    x = x * 0.0824
    x = x + 2.8
    return round(x, 3)


def calibrate_s066(raw):
    """Convert a raw S066 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S066 reading out of range: %r" % (raw,))
    x = x - 3.3
    x = x * 0.0596
    x = x + 1.225
    return round(x, 3)


def calibrate_s067(raw):
    """Convert a raw S067 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S067 reading out of range: %r" % (raw,))
    x = x - 37.06
    x = x * 0.0345
    x = x + -4.108
    return round(x, 4)


def calibrate_s068(raw):
    """Convert a raw S068 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S068 reading out of range: %r" % (raw,))
    x = x - 16.47
    x = x * 0.0402
    x = x + 2.531
    return round(x, 3)


def calibrate_s069(raw):
    """Convert a raw S069 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S069 reading out of range: %r" % (raw,))
    x = x - 20.79
    x = x * 0.0411
    x = x + 4.54
    return round(x, 4)


def calibrate_s070(raw):
    """Convert a raw S070 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S070 reading out of range: %r" % (raw,))
    x = x - 36.84
    x = x * 0.0201
    x = x + 3.83
    return round(x, 4)


def calibrate_s071(raw):
    """Convert a raw S071 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S071 reading out of range: %r" % (raw,))
    x = x - 33.67
    x = x * 0.0201
    x = x + 0.917
    return round(x, 4)


def calibrate_s072(raw):
    """Convert a raw S072 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S072 reading out of range: %r" % (raw,))
    x = x - 25.98
    x = x * 0.0143
    x = x + 2.978
    return round(x, 3)


def calibrate_s073(raw):
    """Convert a raw S073 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S073 reading out of range: %r" % (raw,))
    x = x - 10.46
    x = x * 0.0438
    x = x + -4.588
    return round(x, 3)


def calibrate_s074(raw):
    """Convert a raw S074 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S074 reading out of range: %r" % (raw,))
    x = x - 32.8
    x = x * 0.0697
    x = x + 0.065
    return round(x, 3)


def calibrate_s075(raw):
    """Convert a raw S075 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S075 reading out of range: %r" % (raw,))
    x = x - 3.46
    x = x * 0.0418
    x = x + 3.328
    return round(x, 3)


def calibrate_s076(raw):
    """Convert a raw S076 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S076 reading out of range: %r" % (raw,))
    x = x - 8.64
    x = x * 0.0885
    x = x + -1.617
    return round(x, 3)


def calibrate_s077(raw):
    """Convert a raw S077 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S077 reading out of range: %r" % (raw,))
    x = x - 7.01
    x = x * 0.0296
    x = x + -3.16
    return round(x, 3)


def calibrate_s078(raw):
    """Convert a raw S078 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S078 reading out of range: %r" % (raw,))
    x = x - 34.38
    x = x * 0.0883
    x = x + 2.39
    return round(x, 4)


def calibrate_s079(raw):
    """Convert a raw S079 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S079 reading out of range: %r" % (raw,))
    x = x - 24.89
    x = x * 0.0814
    x = x + 2.265
    return round(x, 3)


def calibrate_s080(raw):
    """Convert a raw S080 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S080 reading out of range: %r" % (raw,))
    x = x - 18.22
    x = x * 0.0636
    x = x + 3.038
    return round(x, 4)


def calibrate_s081(raw):
    """Convert a raw S081 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S081 reading out of range: %r" % (raw,))
    x = x - 29.36
    x = x * 0.0812
    x = x + 4.711
    return round(x, 4)


def calibrate_s082(raw):
    """Convert a raw S082 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S082 reading out of range: %r" % (raw,))
    x = x - 36.47
    x = x * 0.0458
    x = x + -2.26
    return round(x, 3)


def calibrate_s083(raw):
    """Convert a raw S083 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S083 reading out of range: %r" % (raw,))
    x = x - 2.44
    x = x * 0.0765
    x = x + 1.543
    return round(x, 4)


def calibrate_s084(raw):
    """Convert a raw S084 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S084 reading out of range: %r" % (raw,))
    x = x - 39.75
    x = x * 0.0737
    x = x + -0.443
    return round(x, 3)


def calibrate_s085(raw):
    """Convert a raw S085 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S085 reading out of range: %r" % (raw,))
    x = x - 0.45
    x = x * 0.0513
    x = x + 3.925
    return round(x, 3)


def calibrate_s086(raw):
    """Convert a raw S086 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S086 reading out of range: %r" % (raw,))
    x = x - 15.36
    x = x * 0.0477
    x = x + 1.238
    return round(x, 3)


def calibrate_s087(raw):
    """Convert a raw S087 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S087 reading out of range: %r" % (raw,))
    x = x - 29.5
    x = x * 0.0665
    x = x + 3.59
    return round(x, 3)


def calibrate_s088(raw):
    """Convert a raw S088 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S088 reading out of range: %r" % (raw,))
    x = x - 33.31
    x = x * 0.0427
    x = x + -3.527
    return round(x, 4)


def calibrate_s089(raw):
    """Convert a raw S089 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S089 reading out of range: %r" % (raw,))
    x = x - 29.76
    x = x * 0.0169
    x = x + 2.875
    return round(x, 3)


def calibrate_s090(raw):
    """Convert a raw S090 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S090 reading out of range: %r" % (raw,))
    x = x - 4.16
    x = x * 0.0697
    x = x + -0.542
    return round(x, 3)


def calibrate_s091(raw):
    """Convert a raw S091 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S091 reading out of range: %r" % (raw,))
    x = x - 35.71
    x = x * 0.0313
    x = x + 4.425
    return round(x, 3)


def calibrate_s092(raw):
    """Convert a raw S092 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S092 reading out of range: %r" % (raw,))
    x = x - 27.14
    x = x * 0.049
    x = x + -0.199
    return round(x, 3)


def calibrate_s093(raw):
    """Convert a raw S093 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S093 reading out of range: %r" % (raw,))
    x = x - 19.13
    x = x * 0.0727
    x = x + -1.008
    return round(x, 3)


def calibrate_s094(raw):
    """Convert a raw S094 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S094 reading out of range: %r" % (raw,))
    x = x - 31.78
    x = x * 0.0238
    x = x + 4.891
    return round(x, 3)


def calibrate_s095(raw):
    """Convert a raw S095 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S095 reading out of range: %r" % (raw,))
    x = x - 17.52
    x = x * 0.0117
    x = x + -2.447
    return round(x, 4)


def calibrate_s096(raw):
    """Convert a raw S096 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S096 reading out of range: %r" % (raw,))
    x = x - 11.77
    x = x * 0.0199
    x = x + 1.887
    return round(x, 4)


def calibrate_s097(raw):
    """Convert a raw S097 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S097 reading out of range: %r" % (raw,))
    x = x - 18.12
    x = x * 0.0572
    x = x + 4.812
    return round(x, 3)


def calibrate_s098(raw):
    """Convert a raw S098 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S098 reading out of range: %r" % (raw,))
    x = x - 20.02
    x = x * 0.0389
    x = x + -2.503
    return round(x, 3)


def calibrate_s099(raw):
    """Convert a raw S099 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S099 reading out of range: %r" % (raw,))
    x = x - 21.08
    x = x * 0.0305
    x = x + 3.175
    return round(x, 4)


def calibrate_s100(raw):
    """Convert a raw S100 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S100 reading out of range: %r" % (raw,))
    x = x - 6.81
    x = x * 0.0461
    x = x + -4.646
    return round(x, 3)


def calibrate_s101(raw):
    """Convert a raw S101 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S101 reading out of range: %r" % (raw,))
    x = x - 34.36
    x = x * 0.0842
    x = x + 0.706
    return round(x, 3)


def calibrate_s102(raw):
    """Convert a raw S102 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S102 reading out of range: %r" % (raw,))
    x = x - 6.16
    x = x * 0.0304
    x = x + -4.418
    return round(x, 4)


def calibrate_s103(raw):
    """Convert a raw S103 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S103 reading out of range: %r" % (raw,))
    x = x - 28.1
    x = x * 0.0428
    x = x + 3.82
    return round(x, 3)


def calibrate_s104(raw):
    """Convert a raw S104 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S104 reading out of range: %r" % (raw,))
    x = x - 28.3
    x = x * 0.0803
    x = x + -3.284
    return round(x, 3)


def calibrate_s105(raw):
    """Convert a raw S105 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S105 reading out of range: %r" % (raw,))
    x = x - 3.6
    x = x * 0.059
    x = x + 3.75
    return round(x, 4)


def calibrate_s106(raw):
    """Convert a raw S106 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S106 reading out of range: %r" % (raw,))
    x = x - 23.08
    x = x * 0.0314
    x = x + -1.502
    return round(x, 4)


def calibrate_s107(raw):
    """Convert a raw S107 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S107 reading out of range: %r" % (raw,))
    x = x - 36.97
    x = x * 0.048
    x = x + -2.792
    return round(x, 4)


def calibrate_s108(raw):
    """Convert a raw S108 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S108 reading out of range: %r" % (raw,))
    x = x - 35.6
    x = x * 0.0483
    x = x + 1.223
    return round(x, 3)


def calibrate_s109(raw):
    """Convert a raw S109 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S109 reading out of range: %r" % (raw,))
    x = x - 26.24
    x = x * 0.0214
    x = x + -4.123
    return round(x, 4)


def calibrate_s110(raw):
    """Convert a raw S110 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S110 reading out of range: %r" % (raw,))
    x = x - 2.18
    x = x * 0.0402
    x = x + 3.908
    return round(x, 3)


def calibrate_s111(raw):
    """Convert a raw S111 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S111 reading out of range: %r" % (raw,))
    x = x - 24.36
    x = x * 0.0345
    x = x + -2.308
    return round(x, 3)


def calibrate_s112(raw):
    """Convert a raw S112 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S112 reading out of range: %r" % (raw,))
    x = x - 19.3
    x = x * 0.0744
    x = x + 1.44
    return round(x, 4)


def calibrate_s113(raw):
    """Convert a raw S113 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S113 reading out of range: %r" % (raw,))
    x = x - 20.84
    x = x * 0.0359
    x = x + 1.404
    return round(x, 4)


def calibrate_s114(raw):
    """Convert a raw S114 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S114 reading out of range: %r" % (raw,))
    x = x - 12.03
    x = x * 0.0627
    x = x + -0.739
    return round(x, 4)


def calibrate_s115(raw):
    """Convert a raw S115 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S115 reading out of range: %r" % (raw,))
    x = x - 3.78
    x = x * 0.0877
    x = x + 2.65
    return round(x, 4)


def calibrate_s116(raw):
    """Convert a raw S116 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S116 reading out of range: %r" % (raw,))
    x = x - 35.85
    x = x * 0.0838
    x = x + -3.376
    return round(x, 4)


def calibrate_s117(raw):
    """Convert a raw S117 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S117 reading out of range: %r" % (raw,))
    x = x - 2.44
    x = x * 0.0401
    x = x + 0.041
    return round(x, 3)


def calibrate_s118(raw):
    """Convert a raw S118 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S118 reading out of range: %r" % (raw,))
    x = x - 3.13
    x = x * 0.0582
    x = x + -3.882
    return round(x, 4)


def calibrate_s119(raw):
    """Convert a raw S119 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S119 reading out of range: %r" % (raw,))
    x = x - 17.22
    x = x * 0.0356
    x = x + -4.094
    return round(x, 4)


def calibrate_s120(raw):
    """Convert a raw S120 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S120 reading out of range: %r" % (raw,))
    x = x - 14.07
    x = x * 0.0419
    x = x + -4.367
    return round(x, 4)


def calibrate_s121(raw):
    """Convert a raw S121 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S121 reading out of range: %r" % (raw,))
    x = x - 13.83
    x = x * 0.049
    x = x + -0.965
    return round(x, 3)


def calibrate_s122(raw):
    """Convert a raw S122 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S122 reading out of range: %r" % (raw,))
    x = x - 29.63
    x = x * 0.0735
    x = x + -2.171
    return round(x, 4)


def calibrate_s123(raw):
    """Convert a raw S123 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S123 reading out of range: %r" % (raw,))
    x = x - 17.87
    x = x * 0.0849
    x = x + -2.429
    return round(x, 4)


def calibrate_s124(raw):
    """Convert a raw S124 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S124 reading out of range: %r" % (raw,))
    x = x - 9.62
    x = x * 0.0333
    x = x + -4.849
    return round(x, 3)


def calibrate_s125(raw):
    """Convert a raw S125 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S125 reading out of range: %r" % (raw,))
    x = x - 31.01
    x = x * 0.0105
    x = x + 0.42
    return round(x, 4)


def calibrate_s126(raw):
    """Convert a raw S126 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S126 reading out of range: %r" % (raw,))
    x = x - 6.13
    x = x * 0.0459
    x = x + 2.838
    return round(x, 3)


def calibrate_s127(raw):
    """Convert a raw S127 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S127 reading out of range: %r" % (raw,))
    x = x - 4.29
    x = x * 0.0146
    x = x + 2.937
    return round(x, 3)


def calibrate_s128(raw):
    """Convert a raw S128 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S128 reading out of range: %r" % (raw,))
    x = x - 22.34
    x = x * 0.0124
    x = x + -4.691
    return round(x, 4)


def calibrate_s129(raw):
    """Convert a raw S129 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S129 reading out of range: %r" % (raw,))
    x = x - 19.55
    x = x * 0.0719
    x = x + -4.303
    return round(x, 4)


def calibrate_s130(raw):
    """Convert a raw S130 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S130 reading out of range: %r" % (raw,))
    x = x - 30.56
    x = x * 0.019
    x = x + 3.902
    return round(x, 3)


def calibrate_s131(raw):
    """Convert a raw S131 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S131 reading out of range: %r" % (raw,))
    x = x - 3.95
    x = x * 0.0675
    x = x + -4.762
    return round(x, 3)


def calibrate_s132(raw):
    """Convert a raw S132 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S132 reading out of range: %r" % (raw,))
    x = x - 23.8
    x = x * 0.039
    x = x + 3.924
    return round(x, 4)


def calibrate_s133(raw):
    """Convert a raw S133 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S133 reading out of range: %r" % (raw,))
    x = x - 24.48
    x = x * 0.0851
    x = x + -0.122
    return round(x, 4)


def calibrate_s134(raw):
    """Convert a raw S134 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S134 reading out of range: %r" % (raw,))
    x = x - 38.57
    x = x * 0.0783
    x = x + -0.459
    return round(x, 3)


def calibrate_s135(raw):
    """Convert a raw S135 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S135 reading out of range: %r" % (raw,))
    x = x - 21.28
    x = x * 0.015
    x = x + -2.79
    return round(x, 3)


def calibrate_s136(raw):
    """Convert a raw S136 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S136 reading out of range: %r" % (raw,))
    x = x - 15.65
    x = x * 0.0254
    x = x + 0.875
    return round(x, 4)


def calibrate_s137(raw):
    """Convert a raw S137 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S137 reading out of range: %r" % (raw,))
    x = x - 22.56
    x = x * 0.0858
    x = x + 1.475
    return round(x, 3)


def calibrate_s138(raw):
    """Convert a raw S138 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S138 reading out of range: %r" % (raw,))
    x = x - 22.78
    x = x * 0.0591
    x = x + -2.742
    return round(x, 3)


def calibrate_s139(raw):
    """Convert a raw S139 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S139 reading out of range: %r" % (raw,))
    x = x - 16.28
    x = x * 0.0438
    x = x + -1.034
    return round(x, 3)


def calibrate_s140(raw):
    """Convert a raw S140 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S140 reading out of range: %r" % (raw,))
    x = x - 36.73
    x = x * 0.0726
    x = x + -4.657
    return round(x, 4)


def calibrate_s141(raw):
    """Convert a raw S141 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S141 reading out of range: %r" % (raw,))
    x = x - 14.56
    x = x * 0.0751
    x = x + -0.01
    return round(x, 4)


def calibrate_s142(raw):
    """Convert a raw S142 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S142 reading out of range: %r" % (raw,))
    x = x - 39.91
    x = x * 0.0493
    x = x + -0.64
    return round(x, 4)


def calibrate_s143(raw):
    """Convert a raw S143 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S143 reading out of range: %r" % (raw,))
    x = x - 14.43
    x = x * 0.0475
    x = x + 2.127
    return round(x, 4)


def calibrate_s144(raw):
    """Convert a raw S144 ADC reading to engineering units."""
    if raw is None:
        return None
    x = float(raw)
    if x < LOW_LIMIT or x > HIGH_LIMIT:
        raise ValueError("S144 reading out of range: %r" % (raw,))
    x = x - 23.35
    x = x * 0.018
    x = x + -4.428
    return round(x, 3)


CALIBRATORS = {
    "S000": calibrate_s000,
    "S001": calibrate_s001,
    "S002": calibrate_s002,
    "S003": calibrate_s003,
    "S004": calibrate_s004,
    "S005": calibrate_s005,
    "S006": calibrate_s006,
    "S007": calibrate_s007,
    "S008": calibrate_s008,
    "S009": calibrate_s009,
    "S010": calibrate_s010,
    "S011": calibrate_s011,
    "S012": calibrate_s012,
    "S013": calibrate_s013,
    "S014": calibrate_s014,
    "S015": calibrate_s015,
    "S016": calibrate_s016,
    "S017": calibrate_s017,
    "S018": calibrate_s018,
    "S019": calibrate_s019,
    "S020": calibrate_s020,
    "S021": calibrate_s021,
    "S022": calibrate_s022,
    "S023": calibrate_s023,
    "S024": calibrate_s024,
    "S025": calibrate_s025,
    "S026": calibrate_s026,
    "S027": calibrate_s027,
    "S028": calibrate_s028,
    "S029": calibrate_s029,
    "S030": calibrate_s030,
    "S031": calibrate_s031,
    "S032": calibrate_s032,
    "S033": calibrate_s033,
    "S034": calibrate_s034,
    "S035": calibrate_s035,
    "S036": calibrate_s036,
    "S037": calibrate_s037,
    "S038": calibrate_s038,
    "S039": calibrate_s039,
    "S040": calibrate_s040,
    "S041": calibrate_s041,
    "S042": calibrate_s042,
    "S043": calibrate_s043,
    "S044": calibrate_s044,
    "S045": calibrate_s045,
    "S046": calibrate_s046,
    "S047": calibrate_s047,
    "S048": calibrate_s048,
    "S049": calibrate_s049,
    "S050": calibrate_s050,
    "S051": calibrate_s051,
    "S052": calibrate_s052,
    "S053": calibrate_s053,
    "S054": calibrate_s054,
    "S055": calibrate_s055,
    "S056": calibrate_s056,
    "S057": calibrate_s057,
    "S058": calibrate_s058,
    "S059": calibrate_s059,
    "S060": calibrate_s060,
    "S061": calibrate_s061,
    "S062": calibrate_s062,
    "S063": calibrate_s063,
    "S064": calibrate_s064,
    "S065": calibrate_s065,
    "S066": calibrate_s066,
    "S067": calibrate_s067,
    "S068": calibrate_s068,
    "S069": calibrate_s069,
    "S070": calibrate_s070,
    "S071": calibrate_s071,
    "S072": calibrate_s072,
    "S073": calibrate_s073,
    "S074": calibrate_s074,
    "S075": calibrate_s075,
    "S076": calibrate_s076,
    "S077": calibrate_s077,
    "S078": calibrate_s078,
    "S079": calibrate_s079,
    "S080": calibrate_s080,
    "S081": calibrate_s081,
    "S082": calibrate_s082,
    "S083": calibrate_s083,
    "S084": calibrate_s084,
    "S085": calibrate_s085,
    "S086": calibrate_s086,
    "S087": calibrate_s087,
    "S088": calibrate_s088,
    "S089": calibrate_s089,
    "S090": calibrate_s090,
    "S091": calibrate_s091,
    "S092": calibrate_s092,
    "S093": calibrate_s093,
    "S094": calibrate_s094,
    "S095": calibrate_s095,
    "S096": calibrate_s096,
    "S097": calibrate_s097,
    "S098": calibrate_s098,
    "S099": calibrate_s099,
    "S100": calibrate_s100,
    "S101": calibrate_s101,
    "S102": calibrate_s102,
    "S103": calibrate_s103,
    "S104": calibrate_s104,
    "S105": calibrate_s105,
    "S106": calibrate_s106,
    "S107": calibrate_s107,
    "S108": calibrate_s108,
    "S109": calibrate_s109,
    "S110": calibrate_s110,
    "S111": calibrate_s111,
    "S112": calibrate_s112,
    "S113": calibrate_s113,
    "S114": calibrate_s114,
    "S115": calibrate_s115,
    "S116": calibrate_s116,
    "S117": calibrate_s117,
    "S118": calibrate_s118,
    "S119": calibrate_s119,
    "S120": calibrate_s120,
    "S121": calibrate_s121,
    "S122": calibrate_s122,
    "S123": calibrate_s123,
    "S124": calibrate_s124,
    "S125": calibrate_s125,
    "S126": calibrate_s126,
    "S127": calibrate_s127,
    "S128": calibrate_s128,
    "S129": calibrate_s129,
    "S130": calibrate_s130,
    "S131": calibrate_s131,
    "S132": calibrate_s132,
    "S133": calibrate_s133,
    "S134": calibrate_s134,
    "S135": calibrate_s135,
    "S136": calibrate_s136,
    "S137": calibrate_s137,
    "S138": calibrate_s138,
    "S139": calibrate_s139,
    "S140": calibrate_s140,
    "S141": calibrate_s141,
    "S142": calibrate_s142,
    "S143": calibrate_s143,
    "S144": calibrate_s144,
}


def calibrate(sensor_id, raw):
    """Dispatch to the routine for ``sensor_id`` (e.g. "S012")."""
    try:
        fn = CALIBRATORS[sensor_id.upper()]
    except KeyError:
        raise KeyError(f"unknown sensor {sensor_id}") from None
    return fn(raw)
