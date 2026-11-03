import base64
import uuid
from unittest.mock import patch
from urllib.parse import urlencode
import rsa
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
from fastapi.testclient import TestClient
from tests import support
from server import accounts,alipay_pay,referrals,referral_recharge as rr
from server.main import app


def test_signed_notify_replay_and_forgery_boundary():
    a=accounts.create_user(uuid.uuid4().hex+'@example.test','testing-pass-123','a')['id']
    b=accounts.create_user(uuid.uuid4().hex+'@example.test','testing-pass-123','b')['id']
    referrals.bind_signup(b,referrals.ensure_code(a),'shared')
    rr.configure('2020-01-01T00:00:00+00:00',True)
    with accounts._connect() as c:
        c.execute("UPDATE referral_campaign SET enabled=1,effective_at='2020-01-01T00:00:00+00:00'")
    oid=uuid.uuid4().hex
    with accounts._connect() as c:
        c.execute("INSERT INTO alipay_orders(out_trade_no,app_id,subject,total_amount,status,refunded_amount,created_at,updated_at) VALUES(?,'test-app','test','10.00','CREATED','0.00',?,?)",(oid,accounts.utc_now(),accounts.utc_now()))
        c.execute("INSERT INTO alipay_recharges(out_trade_no,user_id,package_id,credits,amount,status,created_at) VALUES(?,?,'test',100,'10.00','PENDING',?)",(oid,b,accounts.utc_now()))
    pub,priv=rsa.newkeys(1024)
    pem=RSAPublicNumbers(pub.e,pub.n).public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
    public=''.join(pem.decode().splitlines()[1:-1])
    cfg={'app_id':'test-app','seller_id':'test-seller','gateway':alipay_pay.PRODUCTION_GATEWAY,'alipay_public_key':public}
    params={'app_id':'test-app','seller_id':'test-seller','out_trade_no':oid,'trade_no':'trade-'+oid,'trade_status':'TRADE_SUCCESS',
            'total_amount':'10.00','buyer_pay_amount':'10.00','gmt_payment':accounts.utc_now(),'notify_id':uuid.uuid4().hex,'sign_type':'RSA2'}
    params['sign']=base64.b64encode(rsa.sign(alipay_pay._sign_content(params).encode(),priv,'SHA-256')).decode()
    with patch.object(alipay_pay,'load_payment_config',return_value=cfg):
        client=TestClient(app)
        tampered=dict(params,total_amount='100.00')
        assert client.post('/api/pay/alipay/notify',content=urlencode(tampered),headers={'Content-Type':'application/x-www-form-urlencoded'}).text=='fail'
        assert accounts.wallet_summary(a)['bonus']==0
        for _ in range(3):
            assert client.post('/api/pay/alipay/notify',content=urlencode(params),headers={'Content-Type':'application/x-www-form-urlencoded'}).text=='success'
    assert accounts.wallet_summary(a)['bonus']==10
    assert accounts.wallet_summary(b)['paid']==100


def test_refund_and_admin_operations_require_admin():
    client=TestClient(app)
    assert client.post('/api/pay/alipay/orders/unknown/refund',json={'refund_amount':'1.00'}).status_code==401
    assert client.get('/api/pay/alipay/orders/unknown/refund-query?out_request_no=x').status_code==401
    assert client.get('/api/admin/referral-recharge').status_code==401
    email=uuid.uuid4().hex+'@example.test'
    client.post('/api/auth/register',json={'email':email,'password':'testing-pass-123','display_name':'test'})
    assert client.post('/api/pay/alipay/orders/unknown/refund',json={'refund_amount':'1.00'}).status_code==403
    assert client.get('/api/admin/referral-recharge').status_code==403
