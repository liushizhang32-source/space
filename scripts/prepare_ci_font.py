"""Fetch one public licensed font at a fixed upstream commit, verify raw SHA."""
import argparse,hashlib,json,pathlib,urllib.request
COMMIT='523d033d6cb47f4a80c58a35753646f5c3608a78'
URL=f'https://raw.githubusercontent.com/notofonts/noto-cjk/{COMMIT}/Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Regular.otf'
SHA='2c76254f6fc379fddfce0a7e84fb5385bb135d3e399294f6eeb6680d0365b74b'
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True,type=pathlib.Path);args=parser.parse_args()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with urllib.request.urlopen(URL,timeout=60) as response:raw=response.read(32*1024*1024)
    if hashlib.sha256(raw).hexdigest()!=SHA:raise ValueError('Noto font SHA mismatch')
    args.output.write_bytes(raw)
    args.output.with_suffix('.provenance.json').write_text(json.dumps(dict(url=URL,sha256=SHA,license='SIL Open Font License 1.1',upstream_commit=COMMIT),indent=2),encoding='utf-8')
if __name__=='__main__':main()
