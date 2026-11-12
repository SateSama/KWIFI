def format_bytes(value):
    value = float(value)
    for unit in ("o", "Ko", "Mo", "Go", "To"):
        if value < 1024 or unit == "To":
            if unit == "o":
                return "%d %s" % (value, unit)
            return "%.2f %s" % (value, unit)
        value /= 1024
    return "%.2f To" % value


def format_rate(value):
    if value >= 1024 * 1024:
        return "%.2f Mo/s" % (value / (1024 * 1024))
    if value >= 1024:
        return "%.1f Ko/s" % (value / 1024)
    return "%d o/s" % value
