import json,math
from .errors import IntegrationError
def loads(raw):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise IntegrationError('DUPLICATE_JSON_KEY')
            result[key]=value
        return result
    def bad(_):raise IntegrationError('NONFINITE_JSON_NUMBER')
    try:
        if isinstance(raw,bytes):raw=raw.decode('utf-8')
        if len(raw)>4*1024*1024:raise IntegrationError('JSON_TOO_LARGE')
        return json.loads(raw,object_pairs_hook=pairs,parse_constant=bad)
    except (UnicodeError,json.JSONDecodeError,RecursionError):raise IntegrationError('INVALID_JSON') from None
def encoded(value):return json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')
