def _strip(s):
    return s.strip()


def clean(obj, name="strip"):
    getattr(obj, name)()
    return _strip(obj)
