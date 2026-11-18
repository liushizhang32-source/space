"""Local CA and private-network configuration. Never exports private keys."""
import argparse,datetime,hashlib,ipaddress,json,secrets,socket,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from orchestrator.bailian_app import default_root
from orchestrator.ipad_app import Devices

def private_ip():
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as s:
        s.connect(('1.1.1.1',80));value=s.getsockname()[0]
    ip=ipaddress.ip_address(value)
    if not (ip in ipaddress.ip_network('10.0.0.0/8') or ip in ipaddress.ip_network('172.16.0.0/12') or ip in ipaddress.ip_network('192.168.0.0/16')):raise RuntimeError('需要私人Wi-Fi局域网IPv4，不在公网接口启动')
    return value
def prepare(root,ip):
    root=Path(root);root.mkdir(parents=True,exist_ok=True);now=datetime.datetime.now(datetime.timezone.utc)
    keypath=root/'ca.key';capath=root/'paperbook-ca.crt';der=root/'paperbook-ca.cer'
    if keypath.exists():key=serialization.load_pem_private_key(keypath.read_bytes(),None);ca=x509.load_pem_x509_certificate(capath.read_bytes())
    else:
        key=rsa.generate_private_key(public_exponent=65537,key_size=3072);name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Paperbook Household Local CA')])
        ca=x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=5)).not_valid_after(now+datetime.timedelta(days=3650)).add_extension(x509.BasicConstraints(ca=True,path_length=0),True).add_extension(x509.KeyUsage(False,False,False,False,False,True,True,False,False),True).sign(key,hashes.SHA256())
        keypath.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));capath.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    der.write_bytes(ca.public_bytes(serialization.Encoding.DER));serverkey=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    cert=x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Paperbook iPad LAN')])).issuer_name(ca.subject).public_key(serverkey.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=5)).not_valid_after(now+datetime.timedelta(days=90)).add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(ip)),x509.IPAddress(ipaddress.ip_address('127.0.0.1')),x509.DNSName('localhost')]),False).add_extension(x509.BasicConstraints(ca=False,path_length=None),True).add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),False).sign(key,hashes.SHA256())
    (root/'server.key').write_bytes(serverkey.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));(root/'server.crt').write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return dict(ip=ip,port=8766,setup_port=8767,cert=str(root/'server.crt'),key=str(root/'server.key'),ca=str(capath),public_ca=str(der),fingerprint=ca.fingerprint(hashes.SHA256()).hex(),url=f'https://{ip}:8766',setup_url=f'http://{ip}:8767')
def main():
    import qrcode
    root=default_root()/'ipad-security';config=prepare(root,private_ip());devices=Devices(root)
    if not devices.data['pin']:
        pin=secrets.token_hex(6);devices.set_pin(pin);print('首次家长口令（请保存，不含百炼Key）：'+pin)
    code=devices.pairing();config['initial_pair_code']=code;config['pair_expires']=devices.expires
    out=Path(__file__).resolve().parents[1]/'.runtime';out.mkdir(exist_ok=True)
    (out/'ipad-network.json').write_text(json.dumps(config,indent=2),encoding='utf-8');qrcode.make(config['setup_url']).save(out/'ipad-qr.png')
    page=f'''<!doctype html><meta charset="utf-8"><title>纸书智伴 iPad 连接</title><h1>同一Wi-Fi扫码连接</h1><p>电脑与iPad访问：{config['url']}</p><img width="300" src="ipad-qr.png"><p>首次证书引导：{config['setup_url']}</p><p>CA SHA256：{config['fingerprint']}</p><p>五分钟一次性配对码：{code}</p><p>在iPad安装证书后，进入设置→通用→关于本机→证书信任设置，手动启用此CA完全信任。须与电脑显示的指纹比对。</p>'''
    (out/'IPAD_ACCESS.html').write_text(page,encoding='utf-8');print('电脑/iPad：'+config['url']);print('扫码入口：'+str(out/'IPAD_ACCESS.html'));print('模型：WAITING_FOR_KEY，配置后仍需账户权限/费用确认');print('CA SHA256：'+config['fingerprint'])
if __name__=='__main__':main()
