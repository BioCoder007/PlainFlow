import json
import pkg.util as util


def main(text):
    cleaned = util.clean(text)
    return json.dumps(cleaned)
